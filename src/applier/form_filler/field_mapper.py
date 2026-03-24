"""Field mapper - maps form fields to user profile data."""

import asyncio
import logging
import re
from difflib import SequenceMatcher

from src.ai.router import AIRouter
from src.ai.prompts.form_answer import FORM_ANSWER_SYSTEM_PROMPT, build_form_answer_prompt
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)

# Common field label patterns -> profile field mapping
FIELD_MAPPINGS = {
    r"first\s*name": lambda p: p.personal.full_name.split()[0] if p.personal.full_name else "",
    r"last\s*name": lambda p: p.personal.full_name.split()[-1] if p.personal.full_name else "",
    r"full\s*name|^name$": lambda p: p.personal.full_name,
    r"email": lambda p: p.personal.email,
    r"phone|mobile|telephone": lambda p: p.personal.phone,
    r"linkedin": lambda p: p.personal.linkedin_url,
    r"github": lambda p: p.personal.github_url,
    r"portfolio|website": lambda p: p.personal.portfolio_url,
    r"city|location": lambda p: p.personal.location.city,
    r"country": lambda p: p.personal.location.country,
    r"state": lambda p: p.personal.location.state,
}


class FieldMapper:
    """Maps form fields to user profile data, with AI fallback for unknown fields."""

    def __init__(self, ai_router: AIRouter | None = None):
        self.ai_router = ai_router

    def map_field(self, label: str, field_type: str, options: list[str] | None,
                  profile: UserProfile, job_title: str = "", company: str = "") -> str | None:
        """Map a form field to the appropriate value from the profile.

        Returns:
            The value to fill, or None if unknown.
        """
        label_lower = label.lower().strip()

        # 1. Try rules-based mapping
        for pattern, extractor in FIELD_MAPPINGS.items():
            if re.search(pattern, label_lower):
                value = extractor(profile)
                if value:
                    # For dropdowns, find best matching option
                    if options and field_type in ("select", "dropdown", "radio"):
                        return self._best_option(value, options)
                    return value

        # 2. Try FAQ matching
        for faq in profile.faq:
            if self._labels_match(label_lower, faq.question.lower()):
                if faq.answer:
                    return faq.answer
                if faq.answer_template:
                    return faq.answer_template
                if faq.answers:
                    return faq.answers.get("default", list(faq.answers.values())[0])

        # 3. AI fallback for unknown fields
        if self.ai_router:
            return self._ai_answer(label, field_type, options, profile, job_title, company)

        return None

    def _best_option(self, value: str, options: list[str]) -> str:
        """Find the best matching option from a list using fuzzy matching."""
        value_lower = value.lower()
        best_match = None
        best_ratio = 0

        for option in options:
            # Exact match
            if option.lower() == value_lower:
                return option

            # Contains match
            if value_lower in option.lower() or option.lower() in value_lower:
                return option

            # Fuzzy match
            ratio = SequenceMatcher(None, value_lower, option.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = option

        if best_ratio > 0.5:
            return best_match

        # Default to first option if nothing matches well
        return options[0] if options else value

    def _labels_match(self, label: str, question: str) -> bool:
        """Check if a form label matches a FAQ question."""
        # Direct substring match
        if label in question or question in label:
            return True
        # Fuzzy match
        ratio = SequenceMatcher(None, label, question).ratio()
        return ratio > 0.6

    def _ai_answer(self, label: str, field_type: str, options: list[str] | None,
                   profile: UserProfile, job_title: str, company: str) -> str | None:
        """Use AI to generate an answer for an unknown form field."""
        faq_text = "\n".join(
            f"Q: {f.question}\nA: {f.answer_template or f.answer or ''}"
            for f in profile.faq
        )

        profile_summary = (
            f"Name: {profile.personal.full_name}\n"
            f"Summary: {profile.professional_summary[:500]}\n"
            f"Skills: {', '.join(profile.all_skills_flat[:10])}\n"
            f"Experience: {profile.work_experience_summary}"
        )

        prompt = build_form_answer_prompt(
            field_label=label,
            field_type=field_type,
            options=options,
            profile_summary=profile_summary,
            faq_answers=faq_text,
            job_title=job_title,
            company=company,
        )

        try:
            answer = self.ai_router.route(
                task="form_field_answer",
                prompt=prompt,
                system_prompt=FORM_ANSWER_SYSTEM_PROMPT,
                max_tokens=256,
                temperature=0.3,
            )
            answer = answer.strip()
            if answer == "UNKNOWN":
                return None

            # If dropdown, find best matching option
            if options:
                return self._best_option(answer, options)

            return answer
        except Exception as e:
            logger.error("AI field answer failed for '%s': %s", label, e)
            return None
