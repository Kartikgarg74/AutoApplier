"""Lever ATS form handler."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class LeverHandler(BaseFormHandler):
    """Handles Lever application forms.

    Lever forms have:
    - Standard layout with name, email, phone, resume
    - Custom questions section
    - Single-page submit
    """

    platform_name = "lever"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            await page.wait_for_selector("form.application-form, .posting-application", timeout=15000)
            await self.anti_detection.human_delay(1000, 2000)

            # Standard fields
            fields = {
                "input[name='name']": profile.personal.full_name,
                "input[name='email']": profile.personal.email,
                "input[name='phone']": profile.personal.phone,
                "input[name='org'], input[name='company']": "",
                "input[name='urls[LinkedIn]'], input[placeholder*='LinkedIn']": profile.personal.linkedin_url,
                "input[name='urls[GitHub]'], input[placeholder*='GitHub']": profile.personal.github_url,
                "input[name='urls[Portfolio]'], input[placeholder*='Portfolio']": profile.personal.portfolio_url,
            }

            for selector, value in fields.items():
                if not value:
                    continue
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await self.anti_detection.human_scroll(page)
                        await element.fill("")
                        await self.anti_detection.human_type(page, selector, value)
                        await self.anti_detection.human_delay()
                except Exception as e:
                    logger.debug("Lever field skip %s: %s", selector, e)

            # Resume upload
            if documents.resume_path:
                await self._upload_file(
                    page,
                    "input[type='file'][name='resume'], input[type='file']",
                    documents.resume_path,
                )
                await self.anti_detection.human_delay()

            # Custom questions (similar approach to Greenhouse)
            custom_fields = await page.query_selector_all(".application-question")
            for field_group in custom_fields:
                try:
                    label_el = await field_group.query_selector("label, .application-label")
                    if not label_el:
                        continue
                    label_text = (await label_el.inner_text()).strip()

                    text_input = await field_group.query_selector("input[type='text'], textarea")
                    select = await field_group.query_selector("select")

                    if text_input:
                        value = self.field_mapper.map_field(
                            label_text, "text", None, profile,
                            job.get("title", ""), job.get("company", ""),
                        )
                        if value:
                            await text_input.fill(value)
                            await self.anti_detection.human_delay()

                    elif select:
                        options_els = await select.query_selector_all("option")
                        option_texts = []
                        for opt in options_els:
                            t = (await opt.inner_text()).strip()
                            if t:
                                option_texts.append(t)
                        value = self.field_mapper.map_field(
                            label_text, "select", option_texts, profile,
                            job.get("title", ""), job.get("company", ""),
                        )
                        if value:
                            await select.select_option(label=value)
                            await self.anti_detection.human_delay()

                except Exception as e:
                    logger.debug("Lever custom question skip: %s", e)

            result.success = True
            result.status = "filled"
            result.message = "Lever form filled"

        except Exception as e:
            logger.error("Lever form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result
