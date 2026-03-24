"""Form filling engine - manages browser, detects platform, delegates to handlers."""

import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext

from src.ai.router import AIRouter
from src.applier.profile.loader import UserProfile
from src.applier.resume.pipeline import DocumentSet

from .anti_detection import AntiDetection
from .field_mapper import FieldMapper
from .session_manager import SessionManager
from .handlers import PLATFORM_HANDLERS
from .handlers.base import ApplicationResult
from .handlers.generic import GenericFormHandler

logger = logging.getLogger(__name__)

# URL patterns to detect platform
PLATFORM_PATTERNS = {
    "greenhouse": [r"greenhouse\.io", r"boards\.greenhouse"],
    "lever": [r"lever\.co", r"jobs\.lever"],
    "linkedin": [r"linkedin\.com"],
    "indeed": [r"indeed\.com"],
    "workday": [r"myworkday(jobs)?\.com", r"workday\.com"],
    "wellfound": [r"wellfound\.com", r"angel\.co"],
    "naukri": [r"naukri\.com"],
}


class FormFillingEngine:
    """Manages Playwright browser and orchestrates form filling across platforms."""

    def __init__(self, config: dict, ai_router: AIRouter):
        self.config = config
        form_config = config.get("form_filling", {})
        browser_config = form_config.get("browser", {})

        self.headless = browser_config.get("headless", False)
        self.user_agent = browser_config.get("user_agent", "")
        viewport = browser_config.get("viewport", {})
        self.viewport_width = viewport.get("width", 1440)
        self.viewport_height = viewport.get("height", 900)

        self.anti_detection = AntiDetection(config)
        self.field_mapper = FieldMapper(ai_router=ai_router)
        self.session_manager = SessionManager()

        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        """Launch the browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )
        self._context = await self._browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            user_agent=self.user_agent if self.user_agent else None,
        )
        await self.anti_detection.configure_browser(self._context)
        logger.info("Browser started (headless=%s)", self.headless)

    async def shutdown(self) -> None:
        """Close the browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser shut down")

    async def fill_and_submit(self, job: dict, profile: UserProfile,
                               documents: DocumentSet,
                               auto_submit: bool = False) -> ApplicationResult:
        """Fill a job application form and optionally submit it.

        Args:
            job: Job data dict
            profile: User profile
            documents: Generated resume + cover letter
            auto_submit: If True, click submit after filling

        Returns:
            ApplicationResult with status
        """
        url = job.get("url", "")
        if not url:
            return ApplicationResult(status="error", message="No application URL")

        platform = self._detect_platform(url)
        logger.info("Filling form: %s at %s (platform: %s)", job["title"], job["company"], platform)

        # Check rate limit
        if not self.anti_detection.check_rate_limit(platform):
            return ApplicationResult(status="rate_limited", message=f"Rate limit reached for {platform}")

        # Load cookies for this platform
        if self._context:
            await self.session_manager.load_cookies(self._context, platform)

        # Open page
        page = await self._context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.anti_detection.human_delay(2000, 4000)

            # Check for CAPTCHA
            handler = self._get_handler(platform)
            if await handler.detect_captcha(page):
                screenshot = await handler.take_screenshot(page, "captcha")
                return ApplicationResult(
                    status="captcha",
                    message="CAPTCHA detected - manual intervention needed",
                    screenshot_path=screenshot,
                )

            # Fill the form
            result = await handler.fill(page, job, profile, documents)

            # Take pre-submit screenshot
            screenshots_config = self.config.get("form_filling", {}).get("screenshots", {})
            if screenshots_config.get("take_before_submit", True):
                result.screenshot_path = await handler.take_screenshot(page, "pre_submit")

            # Submit if auto mode
            if auto_submit and result.success:
                submit_result = await self._click_submit(page)
                if submit_result:
                    result.status = "submitted"
                    result.message = "Application submitted"
                    # Take post-submit screenshot
                    if screenshots_config.get("take_after_submit", True):
                        await self.anti_detection.human_delay(2000, 4000)
                        await handler.take_screenshot(page, "post_submit")
                else:
                    result.status = "submit_failed"
                    result.message = "Form filled but submit button not found"

            # Record action for rate limiting
            self.anti_detection.record_action(platform)

            # Save cookies
            if self._context:
                await self.session_manager.save_cookies(self._context, platform)

            return result

        except Exception as e:
            logger.error("Form filling error for %s: %s", url, e)
            return ApplicationResult(status="error", message=str(e), errors=[str(e)])
        finally:
            await page.close()

    async def _click_submit(self, page) -> bool:
        """Try to find and click the submit button."""
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Submit Application')",
            "button[data-automation-id='submitButton']",
            "button[aria-label*='Submit']",
        ]

        for selector in submit_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await self.anti_detection.human_delay(500, 1500)
                    await btn.click()
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    return True
            except Exception:
                continue

        return False

    def _detect_platform(self, url: str) -> str:
        """Detect the ATS platform from the URL."""
        url_lower = url.lower()
        for platform, patterns in PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return platform
        return "generic"

    def _get_handler(self, platform: str):
        """Get the appropriate form handler for a platform."""
        handler_cls = PLATFORM_HANDLERS.get(platform, GenericFormHandler)
        return handler_cls(
            field_mapper=self.field_mapper,
            anti_detection=self.anti_detection,
        )
