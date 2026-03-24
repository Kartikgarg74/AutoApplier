"""Keyword-based pre-filter for jobs - free, no API calls."""

import logging
from difflib import SequenceMatcher

from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


class KeywordFilter:
    """Fast keyword-based scoring to pre-filter jobs before AI analysis."""

    def score(self, job: dict, profile: UserProfile) -> float:
        """Score a job based on keyword matching (0-100). No API calls."""
        prefs = profile.job_preferences
        raw_score = 0.0

        title = job.get("title", "").lower()
        description = job.get("description", "").lower()
        location = job.get("location", "").lower()
        job_type = job.get("job_type", "").lower()
        work_mode = job.get("work_mode", "").lower()
        text = f"{title} {description}"

        # Must-have keywords: +5 each
        for kw in prefs.must_have_keywords:
            if kw.lower() in text:
                raw_score += 5

        # Nice-to-have keywords: +2 each
        for kw in prefs.nice_to_have_keywords:
            if kw.lower() in text:
                raw_score += 2

        # Exclude keywords: -20 each (hard penalty)
        for kw in prefs.exclude_keywords:
            if kw.lower() in text:
                raw_score -= 20

        # Title matches a target role: +10
        for role in prefs.target_roles:
            ratio = SequenceMatcher(None, title, role.lower()).ratio()
            if ratio > 0.6:
                raw_score += 10
                break

        # Location match: +5
        preferred_locs = [loc.lower() for loc in profile.personal.location.preferred_locations]
        if any(loc in location for loc in preferred_locs):
            raw_score += 5
        if "remote" in location or "remote" in work_mode:
            raw_score += 5

        # Job type match: +5
        pref_types = [t.lower() for t in prefs.job_type]
        if any(pt in job_type for pt in pref_types):
            raw_score += 3

        # Skills match in description: +2 per skill
        all_skills = [s.lower() for s in profile.all_skills_flat]
        for skill in all_skills:
            if skill.lower() in description:
                raw_score += 2

        # Normalize to 0-100
        # Max realistic raw score: ~80 (all keywords + role match + location + skills)
        normalized = max(0, min(100, (raw_score / 60) * 100))

        return round(normalized, 1)
