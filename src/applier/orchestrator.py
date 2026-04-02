"""Application orchestrator - full pipeline: scrape -> score -> generate docs -> fill forms -> track."""

import asyncio
import logging

from src.ai.router import AIRouter
from src.applier.profile.loader import UserProfile
from src.applier.scraper.orchestrator import ScrapingOrchestrator
from src.applier.scoring.pipeline import ScoringPipeline
from src.applier.resume.pipeline import DocumentPipeline
from src.applier.form_filler.engine import FormFillingEngine
from src.applier.tracker.database import ApplicationTracker
from src.utils.security import sanitize_error
from src.applier.tracker.analytics import AnalyticsEngine
from src.notifications.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class ApplicationOrchestrator:
    """Orchestrates the full job application pipeline."""

    def __init__(self, config: dict, ai_router: AIRouter,
                 profile: UserProfile, telegram_bot: TelegramBot | None = None,
                 dry_run: bool = False):
        self.config = config
        self.profile = profile
        self.telegram_bot = telegram_bot
        self.dry_run = dry_run

        self.scraper = ScrapingOrchestrator(config)
        self.scorer = ScoringPipeline(config, ai_router)
        self.doc_pipeline = DocumentPipeline(ai_router, config)
        self.form_engine = FormFillingEngine(config, ai_router)
        self.tracker = ApplicationTracker()
        self.analytics = AnalyticsEngine()

        mode_config = config.get("application_mode", {})
        self.mode = mode_config.get("default", "approve_first")
        self.max_per_day = mode_config.get("max_applications_per_day", 30)
        self.max_per_platform = mode_config.get("max_applications_per_platform", {})

    async def run_pipeline(self) -> dict:
        """Run the full application pipeline."""
        stats = {"scraped": 0, "scored": 0, "applied": 0, "skipped": 0, "errors": 0}

        logger.info("=" * 50)
        logger.info("Starting application pipeline (mode=%s, dry_run=%s)", self.mode, self.dry_run)

        # 1. Scrape jobs
        logger.info("Step 1: Scraping jobs...")
        try:
            new_jobs = await self.scraper.run(self.profile)
            stats["scraped"] = len(new_jobs)
            scrape_stats = self.scraper.get_stats(new_jobs)
            logger.info("Scraped %d new jobs: %s", len(new_jobs), scrape_stats.get("by_platform", {}))

            if self.telegram_bot:
                await self.telegram_bot.send_message(
                    f"Scraped {len(new_jobs)} new jobs\n"
                    f"Platforms: {scrape_stats.get('by_platform', {})}"
                )
        except Exception as e:
            logger.error("Scraping failed: %s", sanitize_error(e))
            stats["errors"] += 1
            if self.telegram_bot:
                await self.telegram_bot.send_message(
                    f"Scraping FAILED\nError: {sanitize_error(e)}"
                )
            return stats

        if not new_jobs:
            logger.info("No new jobs found. Pipeline complete.")
            return stats

        # 2. Score jobs
        logger.info("Step 2: Scoring %d jobs...", len(new_jobs))
        try:
            scoring_results = await self.scorer.run(new_jobs, self.profile)
            stats["scored"] = len(new_jobs)
            stats["skipped"] = len(scoring_results.get("skipped", [])) + len(scoring_results.get("weak_match", []))

            summary = ScoringPipeline.format_summary(scoring_results)
            logger.info(summary)

            if self.telegram_bot:
                await self.telegram_bot.send_message(summary)
        except Exception as e:
            logger.error("Scoring failed: %s", sanitize_error(e))
            stats["errors"] += 1
            if self.telegram_bot:
                await self.telegram_bot.send_message(
                    f"Scoring FAILED\nError: {sanitize_error(e)}"
                )
            return stats

        # 3. Process qualified jobs
        qualified_jobs = []

        if self.mode == "auto":
            # Auto mode: apply to strong matches automatically
            qualified_jobs = scoring_results.get("strong_match", [])
        elif self.mode == "approve_first":
            # Approve first: send all qualified jobs for review
            qualified_jobs = (
                scoring_results.get("strong_match", []) +
                scoring_results.get("review", [])
            )
        elif self.mode == "hybrid":
            # Hybrid: auto-apply strong, review medium
            for job, scoring in scoring_results.get("strong_match", []):
                qualified_jobs.append((job, scoring))
            # Review jobs sent to Telegram for approval
            for job, scoring in scoring_results.get("review", []):
                if self.telegram_bot:
                    await self.telegram_bot.send_job_card(
                        job_id=job["id"],
                        title=job["title"],
                        company=job["company"],
                        score=scoring.relevance_score,
                        matching_skills=scoring.matching_skills,
                        missing_skills=scoring.missing_skills,
                        recommendation=scoring.recommendation,
                    )

        logger.info("Step 3: Processing %d qualified jobs...", len(qualified_jobs))

        # Start browser for form filling
        if qualified_jobs and not self.dry_run:
            await self.form_engine.start()

        try:
            for job, scoring in qualified_jobs:
                # Check daily limit
                if self.tracker.get_today_count() >= self.max_per_day:
                    logger.warning("Daily application limit reached (%d)", self.max_per_day)
                    break

                # Check platform limit
                platform = job.get("platform", "")
                platform_limit = self.max_per_platform.get(platform, 50)
                if self.tracker.get_today_count(platform) >= platform_limit:
                    logger.warning("Platform limit reached for %s (%d)", platform, platform_limit)
                    continue

                try:
                    result = await self._apply_to_job(job, scoring)
                    if result:
                        stats["applied"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.error("Application error for %s at %s: %s", job["title"], job["company"], sanitize_error(e))
                    stats["errors"] += 1

                # Check if we should take a break
                if self.form_engine.anti_detection.should_take_break():
                    await self.form_engine.anti_detection.take_break()

        finally:
            if not self.dry_run:
                await self.form_engine.shutdown()

        # 4. Send daily summary
        stats["avg_score"] = self.tracker.get_stats(days=1).get("avg_score", 0)
        if self.telegram_bot:
            await self.telegram_bot.send_daily_summary(stats)

        logger.info("Pipeline complete: %s", stats)
        return stats

    async def _apply_to_job(self, job: dict, scoring) -> bool:
        """Apply to a single job: generate docs, fill form, submit."""
        logger.info("Applying: %s at %s (score: %.0f)", job["title"], job["company"], scoring.relevance_score)

        # Generate resume + cover letter
        docs = await self.doc_pipeline.generate_documents(job, self.profile, scoring)

        if self.dry_run:
            logger.info("[DRY RUN] Would apply to %s at %s", job["title"], job["company"])
            logger.info("  Resume: %s", docs.resume_path)
            logger.info("  Cover Letter: %s", docs.cover_letter_path)
            return True

        # Determine if we should auto-submit
        auto_submit = self.mode == "auto" or (
            self.mode == "hybrid" and scoring.relevance_score >= 80
        )

        # Fill the form
        result = await self.form_engine.fill_and_submit(
            job=job,
            profile=self.profile,
            documents=docs,
            auto_submit=auto_submit,
        )

        if result.status == "captcha":
            if self.telegram_bot:
                await self.telegram_bot.send_message(
                    f"CAPTCHA detected for {job['title']} at {job['company']}.\n"
                    f"Please solve manually."
                )
            return False

        if result.status == "rate_limited":
            logger.warning("Rate limited for %s", job.get("platform", ""))
            return False

        # Approve First flow
        if self.mode == "approve_first" and result.success:
            if self.telegram_bot:
                await self.telegram_bot.send_job_card(
                    job_id=job["id"],
                    title=job["title"],
                    company=job["company"],
                    score=scoring.relevance_score,
                    matching_skills=scoring.matching_skills,
                    missing_skills=scoring.missing_skills,
                    recommendation=scoring.recommendation,
                    screenshot_path=result.screenshot_path,
                )

                timeout = self.config.get("form_filling", {}).get("captcha", {}).get("timeout_minutes", 30)
                decision = await self.telegram_bot.wait_for_approval(job["id"], timeout_minutes=timeout)

                if decision == "approve":
                    # Submit the form
                    submit_result = await self.form_engine.fill_and_submit(
                        job=job, profile=self.profile, documents=docs, auto_submit=True,
                    )
                    if not submit_result.success:
                        return False
                elif decision == "reject":
                    logger.info("User rejected %s at %s", job["title"], job["company"])
                    return False
                else:
                    logger.info("Approval timeout for %s at %s", job["title"], job["company"])
                    return False

        # Record the application
        if result.success or result.status == "submitted":
            self.tracker.record_application(
                job=job,
                resume_path=docs.resume_path,
                cover_letter_path=docs.cover_letter_path,
                score=scoring.relevance_score,
                screenshot_path=result.screenshot_path,
            )

            if self.telegram_bot:
                count = self.tracker.get_today_count()
                await self.telegram_bot.send_application_confirmation(
                    title=job["title"],
                    company=job["company"],
                    score=scoring.relevance_score,
                    app_number=count,
                )

            # Delay between applications
            await self.form_engine.anti_detection.delay_between_applications()
            return True

        return False
