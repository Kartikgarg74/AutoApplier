"""Base form handler - abstract class for platform-specific form filling."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.applier.form_filler.anti_detection import AntiDetection
from src.applier.form_filler.field_mapper import FieldMapper
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

logger = logging.getLogger(__name__)


@dataclass
class ApplicationResult:
    """Result of a form fill + submit attempt."""
    success: bool = False
    status: str = "pending"  # success, failed, captcha, error, timeout
    message: str = ""
    screenshot_path: str = ""
    errors: list[str] = field(default_factory=list)


class BaseFormHandler(ABC):
    """Abstract base class for platform-specific form handlers."""

    platform_name: str = "unknown"

    def __init__(self, field_mapper: FieldMapper, anti_detection: AntiDetection):
        self.field_mapper = field_mapper
        self.anti_detection = anti_detection

    @abstractmethod
    async def fill(self, page, job: dict, profile: UserProfile,
                   documents: DocumentSet) -> ApplicationResult:
        """Fill the application form on the page. Do NOT submit."""
        ...

    async def detect_captcha(self, page) -> bool:
        """Check if a CAPTCHA is present on the page."""
        captcha_indicators = [
            "captcha",
            "recaptcha",
            "hcaptcha",
            "g-recaptcha",
            "cf-turnstile",
        ]
        page_content = await page.content()
        content_lower = page_content.lower()
        return any(indicator in content_lower for indicator in captcha_indicators)

    async def take_screenshot(self, page, label: str, output_dir: str = "data/screenshots") -> str:
        """Take a screenshot of the current page."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"{output_dir}/{self.platform_name}_{label}_{timestamp}.png"
        await page.screenshot(path=path, full_page=True)
        logger.info("Screenshot saved: %s", path)
        return path

    async def _fill_text_field(self, page, selector: str, value: str) -> None:
        """Fill a text field with human-like typing."""
        try:
            await page.wait_for_selector(selector, timeout=5000)
            await self.anti_detection.human_type(page, selector, value)
        except Exception as e:
            logger.warning("Failed to fill field %s: %s", selector, e)

    async def _select_dropdown(self, page, selector: str, value: str) -> None:
        """Select a dropdown option."""
        try:
            await page.wait_for_selector(selector, timeout=5000)
            await page.select_option(selector, label=value)
        except Exception:
            # Try by value
            try:
                await page.select_option(selector, value=value)
            except Exception as e:
                logger.warning("Failed to select dropdown %s: %s", selector, e)

    async def _upload_file(self, page, selector: str, file_path: str) -> None:
        """Upload a file to an input[type=file] element."""
        try:
            if not Path(file_path).exists():
                logger.warning("File not found for upload: %s", file_path)
                return
            await page.wait_for_selector(selector, timeout=5000)
            await page.set_input_files(selector, file_path)
            logger.info("Uploaded file: %s", file_path)
        except Exception as e:
            logger.warning("Failed to upload file %s: %s", selector, e)
