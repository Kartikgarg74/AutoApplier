"""LinkedIn Easy Apply form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class LinkedInEasyApplyHandler(BaseFormHandler):
    """Handles LinkedIn Easy Apply multi-step modal.

    LinkedIn Easy Apply has:
    - Multi-step modal dialog
    - Resume upload + contact info (usually pre-filled)
    - Custom questions per step
    - "Submit Application" at the end
    - Strict rate limits: max 5/hour, 25/day
    - Requires logged-in session (saved cookies)
    """

    platform_name = "linkedin"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            # Click "Easy Apply" button
            easy_apply_btn = await page.query_selector("button.jobs-apply-button, button[aria-label*='Easy Apply']")
            if not easy_apply_btn:
                result.status = "error"
                result.message = "Easy Apply button not found. May require login or is not Easy Apply."
                return result

            await easy_apply_btn.click()
            await self.anti_detection.human_delay(2000, 4000)

            # Process multi-step modal
            max_steps = 10
            for step in range(max_steps):
                await self.anti_detection.human_delay(1000, 2000)

                # Check for submit button (final step)
                submit_btn = await page.query_selector("button[aria-label*='Submit application'], button[aria-label*='Submit']")
                if submit_btn:
                    # We're at the final step - don't click submit (that's done by the engine)
                    result.success = True
                    result.status = "filled"
                    result.message = f"LinkedIn Easy Apply filled ({step + 1} steps)"
                    return result

                # Fill current step's fields
                await self._fill_step(page, profile, job, documents)

                # Click "Next" or "Review"
                next_btn = await page.query_selector(
                    "button[aria-label*='Continue'], button[aria-label*='Next'], "
                    "button[aria-label*='Review']"
                )
                if next_btn:
                    await next_btn.click()
                    await self.anti_detection.human_delay(1500, 3000)
                else:
                    break

            result.success = True
            result.status = "filled"
            result.message = "LinkedIn Easy Apply form filled"

        except Exception as e:
            logger.error("LinkedIn Easy Apply failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _fill_step(self, page, profile: UserProfile, job: dict,
                         documents: DocumentSet) -> None:
        """Fill fields in the current Easy Apply step."""
        # Resume upload
        file_input = await page.query_selector("input[type='file']")
        if file_input and documents.resume_path:
            await file_input.set_input_files(documents.resume_path)
            await self.anti_detection.human_delay()

        # Text inputs
        text_inputs = await page.query_selector_all(
            ".jobs-easy-apply-modal input[type='text'], "
            ".jobs-easy-apply-modal textarea, "
            ".artdeco-text-input input"
        )
        for inp in text_inputs:
            try:
                label_el = await inp.evaluate_handle(
                    "el => el.closest('.fb-dash-form-element')?.querySelector('label') || "
                    "el.closest('.jobs-easy-apply-form-element')?.querySelector('label')"
                )
                if not label_el:
                    continue
                label_text = await label_el.inner_text()
                current_value = await inp.input_value()

                # Skip if already filled
                if current_value.strip():
                    continue

                value = self.field_mapper.map_field(
                    label_text.strip(), "text", None, profile,
                    job.get("title", ""), job.get("company", ""),
                )
                if value:
                    await inp.fill(value)
                    await self.anti_detection.human_delay(300, 800)
            except Exception:
                pass

        # Dropdowns
        selects = await page.query_selector_all(
            ".jobs-easy-apply-modal select, "
            "select[data-test-text-selectable-option]"
        )
        for select in selects:
            try:
                label_el = await select.evaluate_handle(
                    "el => el.closest('.fb-dash-form-element')?.querySelector('label')"
                )
                if not label_el:
                    continue
                label_text = await label_el.inner_text()

                options_els = await select.query_selector_all("option")
                option_texts = []
                for opt in options_els:
                    t = (await opt.inner_text()).strip()
                    if t:
                        option_texts.append(t)

                value = self.field_mapper.map_field(
                    label_text.strip(), "select", option_texts, profile,
                    job.get("title", ""), job.get("company", ""),
                )
                if value:
                    await select.select_option(label=value)
                    await self.anti_detection.human_delay()
            except Exception:
                pass
