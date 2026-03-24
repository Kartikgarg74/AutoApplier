"""Lever ATS scraper - uses Lever's public JSON API."""

import hashlib
import logging
from datetime import datetime

import httpx

from .base_scraper import BaseScraper
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


class LeverScraper(BaseScraper):
    """Scrapes jobs from Lever career pages using their JSON API."""

    platform_name = "lever"

    def __init__(self, config: dict):
        super().__init__(config)
        lever_config = config.get("scraping", {}).get("custom_scrapers", {}).get("lever", {})
        self.enabled = lever_config.get("enabled", False)
        self.company_pages = lever_config.get("company_pages", [])

    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from configured Lever boards."""
        if not self.enabled or not self.company_pages:
            return []

        all_jobs = []
        async with httpx.AsyncClient(timeout=30) as client:
            for page_url in self.company_pages:
                try:
                    jobs = await self._scrape_company(client, page_url)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.error("Failed to scrape Lever page %s: %s", page_url, e)

        logger.info("Lever: scraped %d jobs from %d companies", len(all_jobs), len(self.company_pages))
        return all_jobs

    async def _scrape_company(self, client: httpx.AsyncClient, page_url: str) -> list[dict]:
        """Scrape jobs from a single Lever company page."""
        # Extract company from URL: https://jobs.lever.co/stripe -> stripe
        company_slug = page_url.rstrip("/").split("/")[-1]
        api_url = f"https://api.lever.co/v0/postings/{company_slug}"

        response = await client.get(api_url)
        response.raise_for_status()

        postings = response.json()
        jobs = []

        for p in postings:
            title = p.get("text", "")
            company = company_slug.replace("-", " ").title()
            location = p.get("categories", {}).get("location", "")

            job = {
                "id": hashlib.md5(f"{title}_{company}_{location}".lower().encode()).hexdigest()[:16],
                "title": title,
                "company": company,
                "location": location,
                "description": p.get("descriptionPlain", ""),
                "url": p.get("hostedUrl", ""),
                "platform": "lever",
                "posted_date": self._parse_timestamp(p.get("createdAt")),
                "salary_min": None,
                "salary_max": None,
                "salary_currency": "",
                "job_type": p.get("categories", {}).get("commitment", ""),
                "work_mode": "",
                "experience_required": None,
                "application_status": "scraped",
            }
            jobs.append(job)

        return jobs

    @staticmethod
    def _parse_timestamp(value) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000)
        except (ValueError, TypeError):
            return None
