"""Cover letter generator - creates tailored cover letters using Claude Sonnet."""

import asyncio
import hashlib
import logging
from pathlib import Path

from src.ai.router import AIRouter
from src.ai.prompts.cover_letter import COVER_LETTER_SYSTEM_PROMPT, build_cover_letter_prompt
from src.applier.profile.loader import UserProfile
from src.applier.scoring.ai_scorer import ScoringResult

logger = logging.getLogger(__name__)


class CoverLetterGenerator:
    """Generates tailored cover letters using AI."""

    def __init__(self, ai_router: AIRouter, cache_dir: str = "data/cover_letters"):
        self.ai_router = ai_router
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}

    async def generate(self, job: dict, profile: UserProfile,
                       scoring: ScoringResult) -> str:
        """Generate a tailored cover letter."""
        cache_key = self._cache_key(job.get("company", ""), job.get("title", ""))
        if cache_key in self._cache:
            logger.info("Cover letter cache hit for %s at %s", job["title"], job["company"])
            return self._cache[cache_key]

        prompt = build_cover_letter_prompt(
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", ""),
            professional_summary=profile.professional_summary,
            matching_skills=scoring.matching_skills,
            cover_letter_hook=scoring.cover_letter_hook,
        )

        loop = asyncio.get_event_loop()
        try:
            text = await loop.run_in_executor(
                None,
                lambda: self.ai_router.route(
                    task="cover_letter",
                    prompt=prompt,
                    system_prompt=COVER_LETTER_SYSTEM_PROMPT,
                    max_tokens=1024,
                    temperature=0.7,
                ),
            )

            self._cache[cache_key] = text
            logger.info("Cover letter generated for %s at %s", job["title"], job["company"])
            return text

        except Exception as e:
            logger.error("Cover letter generation failed: %s", e)
            raise

    def _cache_key(self, company: str, title: str) -> str:
        key = f"{company.lower().strip()}_{title.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
