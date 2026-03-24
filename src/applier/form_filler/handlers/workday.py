"""Workday ATS form handler - most complex ATS platform."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class WorkdayHandler(BaseFormHandler):
    """Handles Workday application forms.

    Workday is the most challenging ATS:
    - Dynamic field ordering
    - Mandatory/optional fields change between forms
    - Must use .docx resume for better parsing in some cases
    - Navigation requires extra clicks sometimes
    - Frequent UI updates break selectors - use fuzzy matching
    """

    platform_name = "workday"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            # Wait for Workday's dynamic page to load
            await page.wait_for_load_state("networkidle", timeout=20000)
            await self.anti_detection.human_delay(2000, 4000)

            # Workday forms often start with "Apply" button
            apply_btn = await page.query_selector(
                "a[data-automation-id='jobPostingApplyButton'], "
                "button[data-automation-id='applyButton']"
            )
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await self.anti_detection.human_delay(2000, 3000)

            # Fill standard fields using Workday's data-automation-id attributes
            field_map = {
                "[data-automation-id='legalNameSection_firstName'] input": profile.personal.full_name.split()[0],
                "[data-automation-id='legalNameSection_lastName'] input": profile.personal.full_name.split()[-1] if len(profile.personal.full_name.split()) > 1 else "",
                "[data-automation-id='email'] input, input[data-automation-id='email']": profile.personal.email,
                "[data-automation-id='phone'] input, input[data-automation-id='phone-number']": profile.personal.phone,
                "[data-automation-id='addressSection_city'] input": profile.personal.location.city,
            }

            for selector, value in field_map.items():
                if not value:
                    continue
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.fill("")
                        await self.anti_detection.human_type(page, selector, value)
                        await self.anti_detection.human_delay()
                except Exception as e:
                    logger.debug("Workday field skip %s: %s", selector, e)

            # Resume upload
            if documents.resume_path:
                file_input = await page.query_selector(
                    "input[type='file'][data-automation-id*='resume'], "
                    "input[type='file']"
                )
                if file_input:
                    await file_input.set_input_files(documents.resume_path)
                    await self.anti_detection.human_delay(2000, 4000)

            # Handle multi-page navigation
            for _ in range(8):
                next_btn = await page.query_selector(
                    "button[data-automation-id='bottom-navigation-next-button'], "
                    "button[data-automation-id='nextButton']"
                )
                if next_btn:
                    # Fill any visible fields on this page first
                    await self._fill_visible_fields(page, profile, job)
                    await next_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    await self.anti_detection.human_delay(1500, 3000)
                else:
                    break

            result.success = True
            result.status = "filled"
            result.message = "Workday form filled"

        except Exception as e:
            logger.error("Workday form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _fill_visible_fields(self, page, profile: UserProfile, job: dict) -> None:
        """Fill any unfilled visible form fields on the current Workday page."""
        # Find all input fields with labels
        inputs = await page.query_selector_all("input:visible, textarea:visible, select:visible")

        for inp in inputs:
            try:
                # Get label text
                label = await inp.evaluate(
                    "el => el.closest('[data-automation-id]')?.querySelector('label')?.textContent || "
                    "el.getAttribute('aria-label') || el.getAttribute('placeholder') || ''"
                )
                if not label or not label.strip():
                    continue

                tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                input_type = await inp.evaluate("el => el.type || ''")

                if tag == "select":
                    options_els = await inp.query_selector_all("option")
                    option_texts = [
                        (await o.inner_text()).strip()
                        for o in options_els
                    ]
                    value = self.field_mapper.map_field(
                        label.strip(), "select", option_texts, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await inp.select_option(label=value)
                elif input_type != "file":
                    current = await inp.input_value()
                    if current.strip():
                        continue
                    value = self.field_mapper.map_field(
                        label.strip(), "text", None, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await inp.fill(value)
                        await self.anti_detection.human_delay(300, 800)
            except Exception:
                pass
