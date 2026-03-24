"""Abstract base class for custom platform scrapers."""

import logging
from abc import ABC, abstractmethod

from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base for custom Playwright-based scrapers."""

    platform_name: str = "unknown"

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from this platform. Returns list of job dicts."""
        ...
