"""Profile validation - ensures the user profile is complete enough for applications."""

import re
from .loader import UserProfile


class ProfileValidator:
    """Validates that a user profile meets minimum requirements for job applications."""

    def validate(self, profile: UserProfile) -> list[str]:
        """Return a list of validation errors. Empty list = valid."""
        errors = []

        # Required personal fields
        if not profile.personal.full_name:
            errors.append("Missing: personal.full_name")
        if not profile.personal.email:
            errors.append("Missing: personal.email")
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", profile.personal.email):
            errors.append("Invalid email format")
        if not profile.personal.phone:
            errors.append("Missing: personal.phone")
        if not profile.personal.location.city:
            errors.append("Missing: personal.location.city")

        # Professional summary
        summary_words = len(profile.professional_summary.split())
        if summary_words < 20:
            errors.append(f"Professional summary too short ({summary_words} words, need at least 20)")

        # Work experience
        if len(profile.work_experience) < 1:
            errors.append("At least 1 work experience entry required")

        # Education
        if len(profile.education) < 1:
            errors.append("At least 1 education entry required")

        # Target roles
        if len(profile.job_preferences.target_roles) < 3:
            errors.append(f"At least 3 target roles required (have {len(profile.job_preferences.target_roles)})")

        # FAQ answers
        if len(profile.faq) < 5:
            errors.append(f"At least 5 FAQ answers required (have {len(profile.faq)})")

        return errors
