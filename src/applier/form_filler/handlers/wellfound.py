"""Wellfound (AngelList) application form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class WellfoundHandler(BaseFormHandler):
    """Handles Wellfound startup application forms.

    Wellfound applications are typically simpler than enterprise ATS:
    - Single-page form with name, email, resume, cover letter
    - Optional custom questions from the startup
    - Sometimes redirects to external application page
    - Lower ATS friction = easier to automate
    """

    platform_name = "wellfound"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            await self.anti_detection.human_delay(1000, 2000)

            # Check if there's an "Apply" button to click first
            apply_btn = await page.query_selector(
                "button[data-test='apply-button'], "
                "a[data-test='apply-button'], "
                "button:has-text('Apply'), "
                "a:has-text('Apply Now')"
            )
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                await self.anti_detection.human_delay(1500, 3000)

            # Check if redirected to external site
            if "wellfound.com" not in page.url:
                result.status = "redirect"
                result.message = "Redirected to external application site"
                return result

            # Fill standard fields
            field_map = {
                "input[name='name'], input[placeholder*='name' i]": profile.personal.full_name,
                "input[name='email'], input[type='email']": profile.personal.email,
                "input[name='phone'], input[type='tel']": profile.personal.phone,
                "input[placeholder*='LinkedIn' i], input[name*='linkedin' i]": profile.personal.linkedin_url,
                "input[placeholder*='GitHub' i], input[name*='github' i]": profile.personal.github_url,
                "input[placeholder*='website' i], input[name*='website' i]": profile.personal.portfolio_url,
                "input[placeholder*='location' i], input[name*='location' i]": profile.personal.location.city,
            }

            for selector, value in field_map.items():
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
                    logger.debug("Wellfound field skip %s: %s", selector, e)

            # Resume upload
            if documents.resume_path:
                file_input = await page.query_selector("input[type='file']")
                if file_input:
                    await file_input.set_input_files(documents.resume_path)
                    await self.anti_detection.human_delay(1000, 2000)

            # Cover letter / "Why are you interested?" textarea
            cover_textarea = await page.query_selector(
                "textarea[name*='cover' i], textarea[placeholder*='why' i], "
                "textarea[name*='note' i], textarea[placeholder*='message' i]"
            )
            if cover_textarea and documents.cover_letter_text:
                # Use first 500 chars of cover letter as the note
                note = documents.cover_letter_text[:500]
                await cover_textarea.fill(note)
                await self.anti_detection.human_delay()

            # Fill any remaining custom fields
            custom_inputs = await page.query_selector_all("input[type='text']:visible, textarea:visible")
            for inp in custom_inputs:
                try:
                    current = await inp.input_value()
                    if current.strip():
                        continue
                    label = await self._get_label(inp)
                    if not label:
                        continue
                    value = self.field_mapper.map_field(
                        label, "text", None, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await inp.fill(value)
                        await self.anti_detection.human_delay(300, 800)
                except Exception:
                    pass

            result.success = True
            result.status = "filled"
            result.message = "Wellfound form filled"

        except Exception as e:
            logger.error("Wellfound form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _get_label(self, element) -> str:
        """Get the label for a form element."""
        try:
            label = await element.evaluate("""el => {
                const id = el.id;
                if (id) {
                    const lbl = document.querySelector('label[for="' + id + '"]');
                    if (lbl) return lbl.textContent;
                }
                return el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
            }""")
            return label.strip() if label else ""
        except Exception:
            return ""
