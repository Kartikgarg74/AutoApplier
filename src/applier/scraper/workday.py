"""Workday ATS scraper - scrapes enterprise career pages powered by Workday."""

import hashlib
import logging
from datetime import datetime

import httpx

from .base_scraper import BaseScraper
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


class WorkdayScraper(BaseScraper):
    """Scrapes job listings from Workday-powered career sites.

    Workday is the most challenging ATS:
    - Each company has a unique Workday subdomain (e.g., amazon.wd5.myworkdayjobs.com)
    - The job search API is at: {base_url}/wday/cxs/{tenant}/External/jobs
    - POST request with JSON payload for search
    - Pagination via offset
    - Dynamic UI that changes frequently
    """

    platform_name = "workday"

    def __init__(self, config: dict):
        super().__init__(config)
        wd_config = config.get("scraping", {}).get("custom_scrapers", {}).get("workday", {})
        self.enabled = wd_config.get("enabled", False)
        self.company_pages = wd_config.get("company_pages", [])
        self.max_results = wd_config.get("max_results_per_company", 50)

    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from configured Workday career pages."""
        if not self.enabled or not self.company_pages:
            return []

        all_jobs = []
        search_terms = profile.job_preferences.target_roles[:3]
        search_query = " ".join(search_terms[:2])  # Workday search works best with fewer terms

        async with httpx.AsyncClient(timeout=30, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
        }) as client:
            for page_url in self.company_pages:
                try:
                    jobs = await self._scrape_company(client, page_url, search_query)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning("Workday scrape failed for %s: %s", page_url, e)

        logger.info("Workday: scraped %d jobs from %d companies", len(all_jobs), len(self.company_pages))
        return all_jobs

    async def _scrape_company(self, client: httpx.AsyncClient, page_url: str,
                               search_query: str) -> list[dict]:
        """Scrape a single Workday company career site.

        Workday URLs look like:
        - https://amazon.wd5.myworkdayjobs.com/en-US/Amazon
        - https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
        """
        # Parse the Workday URL to extract API endpoint
        api_base = self._parse_workday_url(page_url)
        if not api_base:
            logger.warning("Could not parse Workday URL: %s", page_url)
            return []

        jobs = []
        offset = 0
        page_size = 20

        while offset < self.max_results:
            try:
                payload = {
                    "appliedFacets": {},
                    "limit": page_size,
                    "offset": offset,
                    "searchText": search_query,
                }

                response = await client.post(f"{api_base}/jobs", json=payload)

                if response.status_code != 200:
                    logger.debug("Workday API returned %d for %s", response.status_code, page_url)
                    break

                data = response.json()
                job_postings = data.get("jobPostings", [])

                if not job_postings:
                    break

                company_name = self._extract_company_name(page_url)

                for posting in job_postings:
                    title = posting.get("title", "")
                    location = posting.get("locationsText", "")
                    posted = posting.get("postedOn", "")
                    external_path = posting.get("externalPath", "")

                    # Build full job URL
                    job_url = page_url.rstrip("/")
                    if external_path:
                        job_url = f"{job_url}/{external_path.lstrip('/')}"

                    job = {
                        "id": hashlib.md5(f"{title}_{company_name}_{location}".lower().encode()).hexdigest()[:16],
                        "title": title,
                        "company": company_name,
                        "location": location,
                        "description": posting.get("bulletFields", [""])[0] if posting.get("bulletFields") else "",
                        "url": job_url,
                        "platform": "workday",
                        "posted_date": self._parse_date(posted),
                        "salary_min": None,
                        "salary_max": None,
                        "salary_currency": "",
                        "job_type": "",
                        "work_mode": "Remote" if "remote" in location.lower() else "",
                        "experience_required": None,
                        "application_status": "scraped",
                    }
                    jobs.append(job)

                # Check if more results exist
                total = data.get("total", 0)
                offset += page_size
                if offset >= total:
                    break

            except Exception as e:
                logger.warning("Workday pagination error at offset %d: %s", offset, e)
                break

        return jobs

    @staticmethod
    def _parse_workday_url(url: str) -> str | None:
        """Extract the Workday API base URL from a career page URL.

        Input:  https://amazon.wd5.myworkdayjobs.com/en-US/Amazon
        Output: https://amazon.wd5.myworkdayjobs.com/wday/cxs/amazon/Amazon
        """
        import re
        # Pattern: https://{tenant}.{wd_instance}.myworkdayjobs.com/{locale}/{site}
        match = re.match(
            r"https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com(?:/([^/]+))?(?:/([^/]+))?",
            url,
        )
        if not match:
            # Try alternate pattern: https://company.wd5.myworkdayjobs.com/SiteName
            match = re.match(
                r"https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/([^/?]+)",
                url,
            )
            if match:
                tenant = match.group(1)
                wd_instance = match.group(2)
                site = match.group(3)
                return f"https://{tenant}.{wd_instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
            return None

        tenant = match.group(1)
        wd_instance = match.group(2)
        locale_or_site = match.group(3) or ""
        site = match.group(4) or locale_or_site

        # If locale is present (e.g., "en-US"), the next segment is the site
        if "-" in locale_or_site and match.group(4):
            site = match.group(4)
        elif not "-" in locale_or_site:
            site = locale_or_site

        if not site:
            return None

        return f"https://{tenant}.{wd_instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

    @staticmethod
    def _extract_company_name(url: str) -> str:
        """Extract a readable company name from the Workday URL."""
        import re
        match = re.match(r"https?://([^.]+)\.", url)
        if match:
            name = match.group(1)
            return name.replace("-", " ").title()
        return "Unknown"

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            # Workday sometimes uses "Posted 3 Days Ago" format
            import re
            match = re.search(r"(\d+)\s*days?\s*ago", value, re.IGNORECASE)
            if match:
                from datetime import timedelta
                days = int(match.group(1))
                return datetime.utcnow() - timedelta(days=days)
            return None
