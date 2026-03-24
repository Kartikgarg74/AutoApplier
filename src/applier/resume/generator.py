"""Resume generator - creates tailored resumes using Claude Sonnet."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from src.ai.router import AIRouter
from src.ai.prompts.resume_gen import RESUME_SYSTEM_PROMPT, build_resume_prompt
from src.applier.profile.loader import UserProfile
from src.applier.scoring.ai_scorer import ScoringResult

logger = logging.getLogger(__name__)


class ResumeGenerator:
    """Generates tailored resumes using AI."""

    def __init__(self, ai_router: AIRouter, cache_dir: str = "data/resumes"):
        self.ai_router = ai_router
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}

    async def generate(self, job: dict, profile: UserProfile,
                       scoring: ScoringResult) -> dict:
        """Generate a tailored resume as structured JSON."""
        # Check cache
        cache_key = self._cache_key(job.get("company", ""), job.get("title", ""))
        if cache_key in self._cache:
            logger.info("Resume cache hit for %s at %s", job["title"], job["company"])
            return self._cache[cache_key]

        # Build profile data dict for the prompt
        profile_data = {
            "personal": {
                "full_name": profile.personal.full_name,
                "email": profile.personal.email,
                "phone": profile.personal.phone,
                "linkedin_url": profile.personal.linkedin_url,
                "location": {"city": profile.personal.location.city},
            },
            "professional_summary": profile.professional_summary,
            "work_experience": [
                {
                    "title": exp.title,
                    "company": exp.company,
                    "location": exp.location,
                    "start_date": exp.start_date,
                    "end_date": exp.end_date,
                    "description": exp.description,
                    "technologies": exp.technologies,
                    "achievements": exp.achievements,
                }
                for exp in profile.work_experience
            ],
            "education": [
                {
                    "degree": edu.degree,
                    "institution": edu.institution,
                    "graduation_date": edu.graduation_date,
                    "gpa": edu.gpa,
                    "achievements": edu.achievements,
                }
                for edu in profile.education
            ],
            "skills": {
                "programming_languages": {
                    "expert": profile.skills.programming_languages.expert,
                    "proficient": profile.skills.programming_languages.proficient,
                },
                "frameworks": profile.skills.frameworks,
                "tools": profile.skills.tools,
            },
            "projects": [
                {"name": p.name, "description": p.description, "technologies": p.technologies, "impact": p.impact}
                for p in profile.projects
            ],
            "certifications": [
                {"name": c.name, "issuer": c.issuer, "date": c.date}
                for c in profile.certifications
            ],
        }

        scoring_data = {
            "resume_focus_areas": scoring.resume_focus_areas,
            "matching_skills": scoring.matching_skills,
        }

        prompt = build_resume_prompt(
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", ""),
            profile_data=profile_data,
            scoring_result=scoring_data,
        )

        loop = asyncio.get_event_loop()
        try:
            resume_data = await loop.run_in_executor(
                None,
                lambda: self.ai_router.route_json(
                    task="resume_generation",
                    prompt=prompt,
                    system_prompt=RESUME_SYSTEM_PROMPT,
                    max_tokens=4096,
                    temperature=0.5,
                ),
            )

            self._cache[cache_key] = resume_data
            logger.info("Resume generated for %s at %s", job["title"], job["company"])
            return resume_data

        except Exception as e:
            logger.error("Resume generation failed: %s", e)
            raise

    def _cache_key(self, company: str, title: str) -> str:
        """Generate a cache key from company and role."""
        key = f"{company.lower().strip()}_{title.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()[:12]
