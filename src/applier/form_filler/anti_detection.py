"""Anti-detection measures for browser automation."""

import asyncio
import logging
import random
from collections import defaultdict
from datetime import datetime, date

logger = logging.getLogger(__name__)


class AntiDetection:
    """Human-like browser interaction patterns and rate limiting."""

    def __init__(self, config: dict):
        ad_config = config.get("anti_detection", {})
        timing = config.get("form_filling", {}).get("timing", {})

        self.typing_speed_min = timing.get("typing_speed_min_ms", 50)
        self.typing_speed_max = timing.get("typing_speed_max_ms", 150)
        self.field_delay_min = timing.get("min_delay_between_fields_ms", 500)
        self.field_delay_max = timing.get("max_delay_between_fields_ms", 3000)
        self.app_delay_min = timing.get("between_applications_min_sec", 120)
        self.app_delay_max = timing.get("between_applications_max_sec", 600)

        # Rate limits per platform
        self.rate_limits = ad_config.get("rate_limits", {})

        # Track actions per platform per day
        self._daily_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._hourly_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._count_date = date.today()
        self._count_hour = datetime.now().hour

        # Break tracking
        self._apps_since_break = 0
        self.break_every_n = 10

    async def human_type(self, page, selector: str, text: str) -> None:
        """Type text with human-like variable speed."""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        for char in text:
            await page.keyboard.type(char)
            delay = random.uniform(self.typing_speed_min, self.typing_speed_max) / 1000
            # Occasional longer pause (thinking)
            if random.random() < 0.05:
                delay += random.uniform(0.3, 0.8)
            await asyncio.sleep(delay)

    async def human_delay(self, min_ms: int | None = None, max_ms: int | None = None) -> None:
        """Random delay between actions."""
        min_val = (min_ms or self.field_delay_min) / 1000
        max_val = (max_ms or self.field_delay_max) / 1000
        await asyncio.sleep(random.uniform(min_val, max_val))

    async def human_scroll(self, page) -> None:
        """Random scroll before interacting with elements."""
        scroll_amount = random.randint(100, 400)
        direction = random.choice([1, -1])
        await page.evaluate(f"window.scrollBy(0, {scroll_amount * direction})")
        await asyncio.sleep(random.uniform(0.3, 0.8))

    async def delay_between_applications(self) -> None:
        """Wait between applications to appear human."""
        delay = random.uniform(self.app_delay_min, self.app_delay_max)
        logger.info("Waiting %.0f seconds before next application...", delay)
        await asyncio.sleep(delay)

    async def configure_browser(self, context) -> None:
        """Apply stealth settings to browser context."""
        # Remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

    def check_rate_limit(self, platform: str) -> bool:
        """Check if we're within rate limits for this platform. Returns True if OK."""
        self._reset_counters_if_needed()

        limits = self.rate_limits.get(platform, {})
        max_per_hour = limits.get("max_per_hour", 10)
        max_per_day = limits.get("max_per_day", 50)

        hour_key = str(datetime.now().hour)
        if self._hourly_counts[platform][hour_key] >= max_per_hour:
            logger.warning("Rate limit: %s hourly limit reached (%d/%d)", platform, self._hourly_counts[platform][hour_key], max_per_hour)
            return False

        day_key = str(date.today())
        if self._daily_counts[platform][day_key] >= max_per_day:
            logger.warning("Rate limit: %s daily limit reached (%d/%d)", platform, self._daily_counts[platform][day_key], max_per_day)
            return False

        return True

    def record_action(self, platform: str) -> None:
        """Record an application action for rate limiting."""
        self._reset_counters_if_needed()
        hour_key = str(datetime.now().hour)
        day_key = str(date.today())
        self._hourly_counts[platform][hour_key] += 1
        self._daily_counts[platform][day_key] += 1
        self._apps_since_break += 1

    def should_take_break(self) -> bool:
        """Check if it's time for a break."""
        if self._apps_since_break >= self.break_every_n:
            self._apps_since_break = 0
            return True
        return False

    async def take_break(self) -> None:
        """Take a break between application sessions."""
        duration = random.uniform(5 * 60, 15 * 60)  # 5-15 minutes
        logger.info("Taking a %.0f minute break...", duration / 60)
        await asyncio.sleep(duration)

    def _reset_counters_if_needed(self) -> None:
        """Reset counters on new day/hour."""
        now = datetime.now()
        if now.date() != self._count_date:
            self._daily_counts.clear()
            self._hourly_counts.clear()
            self._count_date = now.date()
            self._count_hour = now.hour
        elif now.hour != self._count_hour:
            self._hourly_counts.clear()
            self._count_hour = now.hour
