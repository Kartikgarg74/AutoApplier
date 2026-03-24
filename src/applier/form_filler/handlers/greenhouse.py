"""Greenhouse ATS form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class GreenhouseHandler(BaseFormHandler):
    """Handles Greenhouse application forms.

    Greenhouse forms are relatively standard:
    - Single-page or multi-page forms
    - Standard fields: name, email, phone, resume upload
    - Custom questions at the end
    - File upload via standard input[type=file]
    """

    platform_name = "greenhouse"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        """Fill a Greenhouse application form."""
        result = ApplicationResult()

        try:
            # Wait for form to load
            await page.wait_for_selector("#application_form, form[action*='applications']", timeout=15000)
            await self.anti_detection.human_delay(1000, 2000)

            # Fill standard fields
            await self._fill_standard_fields(page, profile)

            # Upload resume
            if documents.resume_path:
                await self._upload_file(page, "input[type='file'][name*='resume'], input[type='file']#resume", documents.resume_path)
                await self.anti_detection.human_delay()

            # Upload cover letter if there's a second file input
            if documents.cover_letter_path:
                cl_inputs = await page.query_selector_all("input[type='file'][name*='cover'], input[type='file'][name*='letter']")
                if cl_inputs:
                    await cl_inputs[0].set_input_files(documents.cover_letter_path)
                    await self.anti_detection.human_delay()

            # Fill custom questions
            await self._fill_custom_questions(page, profile, job)

            result.success = True
            result.status = "filled"
            result.message = "Form filled successfully"

        except Exception as e:
            logger.error("Greenhouse form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _fill_standard_fields(self, page, profile: UserProfile) -> None:
        """Fill the standard Greenhouse form fields."""
        field_map = {
            "#first_name, input[name*='first_name']": profile.personal.full_name.split()[0],
            "#last_name, input[name*='last_name']": profile.personal.full_name.split()[-1] if len(profile.personal.full_name.split()) > 1 else "",
            "#email, input[name*='email']": profile.personal.email,
            "#phone, input[name*='phone']": profile.personal.phone,
            "input[name*='linkedin'], input[placeholder*='LinkedIn']": profile.personal.linkedin_url,
            "input[name*='location'], input[name*='city']": profile.personal.location.city,
        }

        for selector, value in field_map.items():
            if not value:
                continue
            try:
                element = await page.query_selector(selector)
                if element:
                    await self.anti_detection.human_scroll(page)
                    await element.click()
                    await element.fill("")  # Clear first
                    await self.anti_detection.human_type(page, selector, value)
                    await self.anti_detection.human_delay()
            except Exception as e:
                logger.debug("Skipping field %s: %s", selector, e)

    async def _fill_custom_questions(self, page, profile: UserProfile, job: dict) -> None:
        """Fill custom questions at the end of the Greenhouse form."""
        # Find all question blocks (divs with labels and inputs)
        question_groups = await page.query_selector_all(".field, .custom-question, [class*='question']")

        for group in question_groups:
            try:
                label_el = await group.query_selector("label")
                if not label_el:
                    continue

                label_text = (await label_el.inner_text()).strip()
                if not label_text:
                    continue

                # Determine field type
                text_input = await group.query_selector("input[type='text'], input[type='email'], input[type='tel'], input[type='url']")
                textarea = await group.query_selector("textarea")
                select = await group.query_selector("select")

                if text_input:
                    value = self.field_mapper.map_field(
                        label_text, "text", None, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await text_input.fill(value)
                        await self.anti_detection.human_delay(300, 800)

                elif textarea:
                    value = self.field_mapper.map_field(
                        label_text, "textarea", None, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await textarea.fill(value)
                        await self.anti_detection.human_delay(500, 1500)

                elif select:
                    options = await select.query_selector_all("option")
                    option_texts = []
                    for opt in options:
                        text = (await opt.inner_text()).strip()
                        if text:
                            option_texts.append(text)

                    value = self.field_mapper.map_field(
                        label_text, "select", option_texts, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await select.select_option(label=value)
                        await self.anti_detection.human_delay()

            except Exception as e:
                logger.debug("Skipping custom question: %s", e)
