"""Scoring pipeline - combines keyword filter and AI scoring with bucketing."""

import logging

from src.ai.router import AIRouter
from src.applier.profile.loader import UserProfile
from src.database.models import get_session, Job

from .keyword_filter import KeywordFilter
from .ai_scorer import AIScorer, ScoringResult

logger = logging.getLogger(__name__)


class ScoringPipeline:
    """Two-phase scoring: keyword pre-filter (free) then AI deep analysis."""

    def __init__(self, config: dict, ai_router: AIRouter):
        scoring_config = config.get("scoring", {})
        self.keyword_filter = KeywordFilter()
        self.ai_scorer = AIScorer(ai_router)

        self.keyword_threshold = scoring_config.get("keyword_prefilter_threshold", 30)
        self.apply_threshold = scoring_config.get("apply_threshold", 60)
        self.auto_apply_threshold = scoring_config.get("auto_apply_threshold", 80)
        self.max_batch = scoring_config.get("max_jobs_per_batch", 50)

    async def run(self, jobs: list[dict], profile: UserProfile) -> dict:
        """Run the full scoring pipeline. Returns bucketed results."""
        results = {
            "strong_match": [],   # score >= 80
            "review": [],         # score 60-80
            "weak_match": [],     # score < 60 but passed keyword filter
            "skipped": [],        # failed keyword filter
            "errors": [],
        }

        if not jobs:
            return results

        # Phase 1: Keyword pre-filter (FREE)
        passed_filter = []
        for job in jobs:
            kw_score = self.keyword_filter.score(job, profile)
            if kw_score < self.keyword_threshold:
                results["skipped"].append(job)
                self._update_status(job["id"], "skipped")
                logger.debug("Keyword skip: %s at %s (score: %.1f)", job["title"], job["company"], kw_score)
            else:
                passed_filter.append(job)

        logger.info(
            "Keyword filter: %d passed, %d skipped (threshold: %d)",
            len(passed_filter), len(results["skipped"]), self.keyword_threshold,
        )

        if not passed_filter:
            return results

        # Phase 2: AI deep scoring (Claude Haiku)
        scored = await self.ai_scorer.score_batch(passed_filter, profile, max_batch=self.max_batch)

        for job, scoring in scored:
            if scoring.relevance_score >= self.auto_apply_threshold:
                results["strong_match"].append((job, scoring))
            elif scoring.relevance_score >= self.apply_threshold:
                results["review"].append((job, scoring))
            else:
                results["weak_match"].append((job, scoring))
                self._update_status(job["id"], "skipped")

        logger.info(
            "AI scoring: %d strong, %d review, %d weak",
            len(results["strong_match"]),
            len(results["review"]),
            len(results["weak_match"]),
        )

        return results

    def _update_status(self, job_id: str, status: str) -> None:
        """Update job status in DB."""
        session = get_session()
        try:
            job = session.query(Job).filter_by(id=job_id).first()
            if job:
                job.application_status = status
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def format_summary(results: dict) -> str:
        """Format scoring results as a summary string."""
        total = sum(
            len(v) for v in results.values()
        )
        return (
            f"Scoring Summary\n"
            f"{'=' * 24}\n"
            f"Total scored: {total}\n"
            f"Strong matches (>=80): {len(results['strong_match'])}\n"
            f"For review (60-80): {len(results['review'])}\n"
            f"Weak matches (<60): {len(results['weak_match'])}\n"
            f"Keyword skipped: {len(results['skipped'])}\n"
            f"Errors: {len(results['errors'])}"
        )
