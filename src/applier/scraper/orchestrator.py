"""Scraping orchestrator - runs all scrapers, deduplicates, stores in DB."""

import asyncio
import logging
from difflib import SequenceMatcher

from src.applier.profile.loader import UserProfile
from src.database.models import get_session, Job

from .jobspy_engine import JobSpyEngine
from .greenhouse import GreenhouseScraper
from .lever import LeverScraper
from .wellfound import WellfoundScraper
from .naukri import NaukriScraper
from .workday import WorkdayScraper

logger = logging.getLogger(__name__)


class ScrapingOrchestrator:
    """Orchestrates job scraping across all platforms."""

    def __init__(self, config: dict):
        self.config = config
        self.jobspy = JobSpyEngine(config)
        self.greenhouse = GreenhouseScraper(config)
        self.lever = LeverScraper(config)
        self.wellfound = WellfoundScraper(config)
        self.naukri = NaukriScraper(config)
        self.workday = WorkdayScraper(config)
        self.similarity_threshold = (
            config.get("scraping", {}).get("dedup", {}).get("similarity_threshold", 0.85)
        )

    async def run(self, profile: UserProfile) -> list[dict]:
        """Run all scrapers, deduplicate, and store results."""
        all_jobs = []

        # 1. JobSpy (synchronous - runs in executor)
        loop = asyncio.get_event_loop()
        try:
            jobspy_jobs = await loop.run_in_executor(None, self.jobspy.scrape, profile)
            all_jobs.extend(jobspy_jobs)
            logger.info("JobSpy: %d jobs", len(jobspy_jobs))
        except Exception as e:
            logger.error("JobSpy failed: %s", e)

        # 2. Custom scrapers (async - all 5 run concurrently)
        custom_results = await asyncio.gather(
            self._safe_scrape(self.greenhouse, profile),
            self._safe_scrape(self.lever, profile),
            self._safe_scrape(self.wellfound, profile),
            self._safe_scrape(self.naukri, profile),
            self._safe_scrape(self.workday, profile),
            return_exceptions=True,
        )

        for result in custom_results:
            if isinstance(result, list):
                all_jobs.extend(result)
            elif isinstance(result, Exception):
                logger.error("Custom scraper error: %s", result)

        # 3. Deduplicate
        unique_jobs = self._deduplicate(all_jobs)
        logger.info("Deduplication: %d -> %d unique jobs", len(all_jobs), len(unique_jobs))

        # 4. Filter out already-applied jobs
        new_jobs = self._filter_existing(unique_jobs)
        logger.info("After filtering existing: %d new jobs", len(new_jobs))

        # 5. Store in DB
        stored_count = self._store_jobs(new_jobs)
        logger.info("Stored %d new jobs in database", stored_count)

        return new_jobs

    async def _safe_scrape(self, scraper, profile: UserProfile) -> list[dict]:
        """Safely run a scraper, catching NotImplementedError."""
        try:
            return await scraper.scrape(profile)
        except NotImplementedError:
            return []
        except Exception as e:
            logger.error("%s scraper failed: %s", scraper.platform_name, e)
            return []

    def _deduplicate(self, jobs: list[dict]) -> list[dict]:
        """Remove duplicate jobs based on title + company + location similarity."""
        seen_keys = set()
        unique = []

        for job in jobs:
            key = f"{job['title'].lower().strip()}_{job['company'].lower().strip()}"

            # Exact match check
            if key in seen_keys:
                continue

            # Fuzzy match check against existing keys
            is_dup = False
            for existing_key in seen_keys:
                ratio = SequenceMatcher(None, key, existing_key).ratio()
                if ratio >= self.similarity_threshold:
                    is_dup = True
                    break

            if not is_dup:
                seen_keys.add(key)
                unique.append(job)

        return unique

    def _filter_existing(self, jobs: list[dict]) -> list[dict]:
        """Remove jobs that already exist in the database."""
        if not jobs:
            return []

        session = get_session()
        try:
            existing_ids = {
                row[0] for row in session.query(Job.id).all()
            }
            return [j for j in jobs if j["id"] not in existing_ids]
        finally:
            session.close()

    def _store_jobs(self, jobs: list[dict]) -> int:
        """Store new jobs in the database."""
        if not jobs:
            return 0

        session = get_session()
        try:
            for job_data in jobs:
                job = Job(
                    id=job_data["id"],
                    title=job_data["title"],
                    company=job_data["company"],
                    location=job_data.get("location", ""),
                    description=job_data.get("description", ""),
                    url=job_data.get("url", ""),
                    platform=job_data.get("platform", ""),
                    posted_date=job_data.get("posted_date"),
                    salary_min=job_data.get("salary_min"),
                    salary_max=job_data.get("salary_max"),
                    salary_currency=job_data.get("salary_currency", ""),
                    job_type=job_data.get("job_type", ""),
                    work_mode=job_data.get("work_mode", ""),
                    experience_required=job_data.get("experience_required"),
                    application_status="scraped",
                )
                session.merge(job)
            session.commit()
            return len(jobs)
        except Exception as e:
            session.rollback()
            logger.error("Failed to store jobs: %s", e)
            return 0
        finally:
            session.close()

    def get_stats(self, jobs: list[dict]) -> dict:
        """Get scraping stats breakdown by platform."""
        platform_counts = {}
        for job in jobs:
            platform = job.get("platform", "unknown")
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

        return {
            "total": len(jobs),
            "by_platform": platform_counts,
        }
