"""Generic form handler - fallback for unknown platforms."""

import logging

from .base import BaseFormHandler, ApplicationResult
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


class GenericFormHandler(BaseFormHandler):
    """Fallback handler for unknown application platforms.

    Uses DOM analysis to identify form fields and fill them
    using the field mapper (with AI fallback for unknown fields).
    """

    platform_name = "generic"

    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        result = ApplicationResult()

        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
            await self.anti_detection.human_delay(1000, 2000)

            # Find all form fields
            filled_count = 0

            # Text inputs and textareas
            inputs = await page.query_selector_all(
                "input[type='text']:visible, input[type='email']:visible, "
                "input[type='tel']:visible, input[type='url']:visible, "
                "textarea:visible"
            )

            for inp in inputs:
                try:
                    label_text = await self._get_field_label(inp)
                    if not label_text:
                        continue

                    current_value = await inp.input_value()
                    if current_value.strip():
                        continue

                    value = self.field_mapper.map_field(
                        label_text, "text", None, profile,
                        job.get("title", ""), job.get("company", ""),
                    )
                    if value:
                        await inp.fill(value)
                        await self.anti_detection.human_delay(300, 800)
                        filled_count += 1
                except Exception as e:
                    logger.debug("Generic field error: %s", e)

            # Select dropdowns
            selects = await page.query_selector_all("select:visible")
            for select in selects:
                try:
                    label_text = await self._get_field_label(select)
                    if not label_text:
                        continue

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
                        filled_count += 1
                except Exception:
                    pass

            # File uploads
            if documents.resume_path:
                file_inputs = await page.query_selector_all("input[type='file']:visible")
                for i, fi in enumerate(file_inputs):
                    file_path = documents.resume_path if i == 0 else documents.cover_letter_path
                    if file_path:
                        try:
                            await fi.set_input_files(file_path)
                            await self.anti_detection.human_delay(1000, 2000)
                            filled_count += 1
                        except Exception:
                            pass

            result.success = filled_count > 0
            result.status = "filled" if filled_count > 0 else "partial"
            result.message = f"Generic handler: filled {filled_count} fields"

        except Exception as e:
            logger.error("Generic form filling failed: %s", e)
            result.status = "error"
            result.message = str(e)
            result.errors.append(str(e))

        return result

    async def _get_field_label(self, element) -> str:
        """Try multiple strategies to find a field's label."""
        try:
            # Strategy 1: aria-label
            label = await element.get_attribute("aria-label")
            if label:
                return label.strip()

            # Strategy 2: placeholder
            label = await element.get_attribute("placeholder")
            if label:
                return label.strip()

            # Strategy 3: associated <label> element
            label = await element.evaluate("""el => {
                const id = el.id;
                if (id) {
                    const label = document.querySelector(`label[for="${id}"]`);
                    if (label) return label.textContent;
                }
                const parent = el.closest('.form-group, .field, .form-field, [class*="field"]');
                if (parent) {
                    const label = parent.querySelector('label');
                    if (label) return label.textContent;
                }
                return '';
            }""")
            if label:
                return label.strip()

        except Exception:
            pass

        return ""
