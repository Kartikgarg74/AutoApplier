"""Greenhouse ATS scraper - scrapes job boards at boards.greenhouse.io."""

import hashlib
import logging
from datetime import datetime

import httpx

from .base_scraper import BaseScraper
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


class GreenhouseScraper(BaseScraper):
    """Scrapes jobs from Greenhouse board pages using their JSON API."""

    platform_name = "greenhouse"

    def __init__(self, config: dict):
        super().__init__(config)
        gh_config = config.get("scraping", {}).get("custom_scrapers", {}).get("greenhouse", {})
        self.enabled = gh_config.get("enabled", False)
        self.company_pages = gh_config.get("company_pages", [])

    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from configured Greenhouse boards."""
        if not self.enabled or not self.company_pages:
            return []

        all_jobs = []
        async with httpx.AsyncClient(timeout=30) as client:
            for board_url in self.company_pages:
                try:
                    jobs = await self._scrape_board(client, board_url, profile)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.error("Failed to scrape Greenhouse board %s: %s", board_url, e)

        logger.info("Greenhouse: scraped %d jobs from %d boards", len(all_jobs), len(self.company_pages))
        return all_jobs

    async def _scrape_board(self, client: httpx.AsyncClient, board_url: str,
                            profile: UserProfile) -> list[dict]:
        """Scrape a single Greenhouse board using the JSON API."""
        # Extract board token from URL: https://boards.greenhouse.io/stripe -> stripe
        board_token = board_url.rstrip("/").split("/")[-1]
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

        response = await client.get(api_url, params={"content": "true"})
        response.raise_for_status()

        data = response.json()
        jobs_data = data.get("jobs", [])

        jobs = []
        for j in jobs_data:
            title = j.get("title", "")
            company = board_token.replace("-", " ").title()
            location = j.get("location", {}).get("name", "")

            job = {
                "id": hashlib.md5(f"{title}_{company}_{location}".lower().encode()).hexdigest()[:16],
                "title": title,
                "company": company,
                "location": location,
                "description": j.get("content", ""),
                "url": j.get("absolute_url", ""),
                "platform": "greenhouse",
                "posted_date": self._parse_date(j.get("updated_at")),
                "salary_min": None,
                "salary_max": None,
                "salary_currency": "",
                "job_type": "",
                "work_mode": "",
                "experience_required": None,
                "application_status": "scraped",
            }
            jobs.append(job)

        return jobs

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
