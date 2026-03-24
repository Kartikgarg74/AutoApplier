"""Indeed application form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class IndeedHandler(BaseFormHandler):
    """Handles Indeed application forms.

    Indeed can either:
    1. Redirect to the company's own application page (handled by generic handler)
    2. Use Indeed's own application form (similar multi-step to LinkedIn)
    """

    platform_name = "indeed"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            await self.anti_detection.human_delay(1000, 2000)

            # Check if it's Indeed's own form or external redirect
            url = page.url
            if "indeed.com" not in url:
                result.status = "redirect"
                result.message = "Indeed redirected to external site"
                return result

            # Fill Indeed's form fields
            fields = {
                "input[id*='name'], input[name*='name']": profile.personal.full_name,
                "input[id*='email'], input[name*='email']": profile.personal.email,
                "input[id*='phone'], input[name*='phone']": profile.personal.phone,
            }

            for selector, value in fields.items():
                if not value:
                    continue
                try:
                    element = await page.query_selector(selector)
                    if element:
                        current = await element.input_value()
                        if not current.strip():
                            await element.fill("")
                            await self.anti_detection.human_type(page, selector, value)
                            await self.anti_detection.human_delay()
                except Exception as e:
                    logger.debug("Indeed field skip %s: %s", selector, e)

            # Resume upload
            if documents.resume_path:
                file_input = await page.query_selector("input[type='file']")
                if file_input:
                    await file_input.set_input_files(documents.resume_path)
                    await self.anti_detection.human_delay(1000, 2000)

            # Handle multi-step (Indeed sometimes has "Continue" buttons)
            for _ in range(5):
                continue_btn = await page.query_selector(
                    "button[id*='continue'], button[class*='continue'], "
                    "button:has-text('Continue')"
                )
                if continue_btn:
                    await continue_btn.click()
                    await self.anti_detection.human_delay(1500, 3000)
                else:
                    break

            result.success = True
            result.status = "filled"
            result.message = "Indeed form filled"

        except Exception as e:
            logger.error("Indeed form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result
