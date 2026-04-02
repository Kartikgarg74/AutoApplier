"""AI-powered deep job scoring using Claude Haiku."""

import asyncio
import json
import logging

from pydantic import BaseModel

from src.ai.router import AIRouter
from src.ai.prompts.job_scoring import JOB_SCORING_SYSTEM_PROMPT, build_scoring_prompt
from src.applier.profile.loader import UserProfile
from src.database.models import get_session, Job
from src.utils.security import sanitize_error

logger = logging.getLogger(__name__)


class ScoringResult(BaseModel):
    """Result from AI job scoring."""
    relevance_score: float = 0
    matching_skills: list[str] = []
    missing_skills: list[str] = []
    recommendation: str = "Skip"
    reasoning: str = ""
    resume_focus_areas: list[str] = []
    cover_letter_hook: str = ""


class AIScorer:
    """Scores jobs against user profile using Claude Haiku."""

    def __init__(self, ai_router: AIRouter, max_concurrent: int = 5):
        self.ai_router = ai_router
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def score(self, job: dict, profile: UserProfile) -> ScoringResult:
        """Score a single job using AI."""
        async with self.semaphore:
            return await self._score_single(job, profile)

    async def _score_single(self, job: dict, profile: UserProfile) -> ScoringResult:
        """Internal scoring for a single job."""
        prompt = build_scoring_prompt(
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            description=job.get("description", "")[:2000],
            professional_summary=profile.professional_summary,
            skills=", ".join(profile.all_skills_flat),
            experience_summary=profile.work_experience_summary,
            target_roles=profile.job_preferences.target_roles,
        )

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self.ai_router.route_json(
                    task="job_scoring",
                    prompt=prompt,
                    system_prompt=JOB_SCORING_SYSTEM_PROMPT,
                    max_tokens=1024,
                    temperature=0.3,
                ),
            )
            scoring = ScoringResult(**result)

            # Update job in DB
            self._update_job_scoring(job["id"], scoring)

            logger.info(
                "Scored: %s at %s -> %d/100 (%s)",
                job["title"], job["company"], scoring.relevance_score, scoring.recommendation,
            )
            return scoring

        except Exception as e:
            logger.error("AI scoring failed for %s at %s: %s", job["title"], job["company"], sanitize_error(e))
            return ScoringResult(relevance_score=0, recommendation="Skip", reasoning=f"Scoring error: {sanitize_error(e)}")

    async def score_batch(self, jobs: list[dict], profile: UserProfile,
                          max_batch: int = 50) -> list[tuple[dict, ScoringResult]]:
        """Score a batch of jobs concurrently."""
        batch = jobs[:max_batch]
        tasks = [self.score(job, profile) for job in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for job, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error("Batch scoring error: %s", result)
                result = ScoringResult(recommendation="Skip", reasoning="Error")
            scored.append((job, result))

        return scored

    def _update_job_scoring(self, job_id: str, scoring: ScoringResult) -> None:
        """Update job record in DB with scoring results."""
        session = get_session()
        try:
            job = session.query(Job).filter_by(id=job_id).first()
            if job:
                job.relevance_score = scoring.relevance_score
                job.matching_skills = json.dumps(scoring.matching_skills)
                job.missing_skills = json.dumps(scoring.missing_skills)
                job.ai_recommendation = scoring.recommendation
                job.ai_summary = scoring.reasoning
                job.resume_focus_areas = json.dumps(scoring.resume_focus_areas)
                job.cover_letter_hook = scoring.cover_letter_hook
                job.application_status = "scored"
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to update job scoring: %s", e)
        finally:
            session.close()
