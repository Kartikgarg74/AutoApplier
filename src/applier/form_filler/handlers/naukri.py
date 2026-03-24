"""Naukri.com application form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class NaukriHandler(BaseFormHandler):
    """Handles Naukri.com application forms.

    Naukri has:
    - "Apply" button on job detail page that opens a modal or redirects
    - Sometimes requires Naukri login (use saved cookies)
    - Resume upload from Naukri profile or file upload
    - Additional questions (experience, current CTC, expected CTC, notice period)
    - Can also redirect to company's external career page
    """

    platform_name = "naukri"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            await self.anti_detection.human_delay(1000, 2000)

            # Check if we need to click "Apply" first
            apply_btn = await page.query_selector(
                "button#apply-button, "
                "button.apply-button, "
                "a[id*='apply'], "
                "button:has-text('Apply on company site'), "
                "button:has-text('Apply')"
            )
            if apply_btn:
                btn_text = (await apply_btn.inner_text()).strip().lower()

                # If "Apply on company site" - it will redirect
                if "company site" in btn_text:
                    await apply_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await self.anti_detection.human_delay(2000, 4000)

                    if "naukri.com" not in page.url:
                        result.status = "redirect"
                        result.message = "Redirected to company's external career page"
                        return result
                else:
                    await apply_btn.click()
                    await self.anti_detection.human_delay(2000, 4000)

            # Fill the Naukri application form
            # Naukri often shows a chatbot-like application flow or a modal

            # Standard fields
            field_map = {
                "input[name='name'], input[placeholder*='Name' i]": profile.personal.full_name,
                "input[name='email'], input[type='email']": profile.personal.email,
                "input[name='mobile'], input[type='tel'], input[placeholder*='Mobile' i]": profile.personal.phone,
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
                    logger.debug("Naukri field skip %s: %s", selector, e)

            # Resume upload
            if documents.resume_path:
                file_input = await page.query_selector(
                    "input[type='file'][name*='resume' i], "
                    "input[type='file'][id*='resume' i], "
                    "input[type='file']"
                )
                if file_input:
                    await file_input.set_input_files(documents.resume_path)
                    await self.anti_detection.human_delay(1000, 2000)

            # Naukri-specific fields: CTC, notice period, experience
            await self._fill_naukri_specifics(page, profile)

            # Handle any custom questions
            await self._fill_custom_questions(page, profile, job)

            result.success = True
            result.status = "filled"
            result.message = "Naukri form filled"

        except Exception as e:
            logger.error("Naukri form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _fill_naukri_specifics(self, page, profile: UserProfile) -> None:
        """Fill Naukri-specific fields like CTC and notice period."""
        prefs = profile.job_preferences

        # Current CTC
        ctc_input = await page.query_selector(
            "input[name*='currentCtc' i], input[placeholder*='Current CTC' i], "
            "input[name*='current_salary' i]"
        )
        if ctc_input:
            ctc = str(prefs.salary_expectations.minimum_inr // 100000)  # In lakhs
            await ctc_input.fill(ctc)
            await self.anti_detection.human_delay()

        # Expected CTC
        exp_ctc_input = await page.query_selector(
            "input[name*='expectedCtc' i], input[placeholder*='Expected CTC' i], "
            "input[name*='expected_salary' i]"
        )
        if exp_ctc_input:
            exp_ctc = str(prefs.salary_expectations.preferred_inr // 100000)
            await exp_ctc_input.fill(exp_ctc)
            await self.anti_detection.human_delay()

        # Notice period
        notice_select = await page.query_selector(
            "select[name*='notice' i], select[id*='notice' i]"
        )
        if notice_select:
            notice = prefs.notice_period or "30 days"
            options = await notice_select.query_selector_all("option")
            option_texts = [(await o.inner_text()).strip() for o in options]
            best = self.field_mapper._best_option(notice, option_texts)
            await notice_select.select_option(label=best)
            await self.anti_detection.human_delay()

        # Experience (years)
        exp_input = await page.query_selector(
            "input[name*='experience' i], select[name*='experience' i]"
        )
        if exp_input:
            tag = await exp_input.evaluate("el => el.tagName.toLowerCase()")
            exp_years = str(len(profile.work_experience))  # Rough estimate
            if tag == "select":
                options = await exp_input.query_selector_all("option")
                option_texts = [(await o.inner_text()).strip() for o in options]
                best = self.field_mapper._best_option(exp_years, option_texts)
                await exp_input.select_option(label=best)
            else:
                await exp_input.fill(exp_years)
            await self.anti_detection.human_delay()

    async def _fill_custom_questions(self, page, profile: UserProfile, job: dict) -> None:
        """Fill any remaining custom questions on the Naukri form."""
        # Find all visible unfilled inputs
        inputs = await page.query_selector_all(
            "input[type='text']:visible, textarea:visible, select:visible"
        )

        for inp in inputs:
            try:
                tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                input_type = await inp.evaluate("el => el.type || ''")

                if input_type == "file":
                    continue

                # Get label
                label = await inp.evaluate("""el => {
                    const id = el.id || el.name;
                    if (id) {
                        const lbl = document.querySelector('label[for="' + id + '"]');
                        if (lbl) return lbl.textContent;
                    }
                    const parent = el.closest('.formField, .form-group, [class*="field"]');
                    if (parent) {
                        const lbl = parent.querySelector('label, .label');
                        if (lbl) return lbl.textContent;
                    }
                    return el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
                }""")

                if not label or not label.strip():
                    continue

                if tag == "select":
                    options = await inp.query_selector_all("option")
                    option_texts = [(await o.inner_text()).strip() for o in options]
                    value = self.field_mapper.map_field(
                        label.strip(), "select", option_texts, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await inp.select_option(label=value)
                        await self.anti_detection.human_delay()
                else:
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
