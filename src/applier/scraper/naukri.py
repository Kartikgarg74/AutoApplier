"""Naukri.com scraper - India's largest job portal via their search API."""

import hashlib
import logging
from datetime import datetime

import httpx

from .base_scraper import BaseScraper
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)

# Naukri has a public JSON search API used by their frontend
NAUKRI_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"


class NaukriScraper(BaseScraper):
    """Scrapes jobs from Naukri.com — India's largest job portal.

    Naukri has:
    - Dominant market share in India for job listings
    - Public search API returning JSON (used by their SPA frontend)
    - Filters: keywords, location, experience, salary, freshness
    - Important for Indian market roles
    """

    platform_name = "naukri"

    def __init__(self, config: dict):
        super().__init__(config)
        naukri_config = config.get("scraping", {}).get("custom_scrapers", {}).get("naukri", {})
        self.enabled = naukri_config.get("enabled", False)
        self.max_pages = naukri_config.get("max_pages", 3)

    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from Naukri.com matching user's target roles and location."""
        if not self.enabled:
            return []

        all_jobs = []
        search_terms = profile.job_preferences.target_roles[:5]
        location = profile.personal.location.city or "India"

        # Determine experience range from profile
        exp_years = self._estimate_experience(profile)

        async with httpx.AsyncClient(timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
            "Accept": "application/json",
            "Appid": "109",
            "Systemid": "Naukri",
        }) as client:
            for term in search_terms:
                try:
                    jobs = await self._search_jobs(client, term, location, exp_years)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning("Naukri search failed for '%s': %s", term, e)

        logger.info("Naukri: scraped %d jobs", len(all_jobs))
        return all_jobs

    async def _search_jobs(self, client: httpx.AsyncClient, keyword: str,
                           location: str, experience: int) -> list[dict]:
        """Search Naukri's API for jobs."""
        jobs = []

        for page in range(1, self.max_pages + 1):
            try:
                # Naukri uses URL-based search with SEO-friendly paths
                # Their API endpoint accepts query params
                search_url = (
                    f"https://www.naukri.com/jobapi/v3/search"
                    f"?noOfResults=20&urlType=search_by_keyword"
                    f"&searchType=adv&keyword={keyword}"
                    f"&location={location}"
                    f"&experience={experience}"
                    f"&pageNo={page}"
                )

                response = await client.get(search_url)

                if response.status_code != 200:
                    # Fallback to scraping the HTML search results page
                    return await self._scrape_search_page(client, keyword, location)

                data = response.json()
                job_details = data.get("jobDetails", [])

                if not job_details:
                    break

                for jd in job_details:
                    title = jd.get("title", "")
                    company = jd.get("companyName", "")
                    loc = jd.get("placeholders", [{}])
                    location_str = ""
                    for ph in loc:
                        if ph.get("type") == "location":
                            location_str = ph.get("label", "")
                            break

                    salary_str = ""
                    for ph in loc:
                        if ph.get("type") == "salary":
                            salary_str = ph.get("label", "")
                            break

                    sal_min, sal_max = self._parse_salary(salary_str)

                    job = {
                        "id": hashlib.md5(f"{title}_{company}_{location_str}".lower().encode()).hexdigest()[:16],
                        "title": title,
                        "company": company,
                        "location": location_str,
                        "description": jd.get("jobDescription", ""),
                        "url": jd.get("jdURL", ""),
                        "platform": "naukri",
                        "posted_date": self._parse_date(jd.get("createdDate")),
                        "salary_min": sal_min,
                        "salary_max": sal_max,
                        "salary_currency": "INR",
                        "job_type": jd.get("jobType", ""),
                        "work_mode": "Remote" if "remote" in jd.get("title", "").lower() or "remote" in str(jd.get("tagsAndSkills", "")).lower() else "",
                        "experience_required": jd.get("experience", ""),
                        "application_status": "scraped",
                    }
                    jobs.append(job)

                # Check if there are more pages
                total = data.get("noOfJobs", 0)
                if page * 20 >= total:
                    break

            except Exception as e:
                logger.warning("Naukri page %d error: %s", page, e)
                break

        return jobs

    async def _scrape_search_page(self, client: httpx.AsyncClient,
                                   keyword: str, location: str) -> list[dict]:
        """Fallback: scrape Naukri search results HTML page."""
        jobs = []
        try:
            slug = keyword.lower().replace(" ", "-")
            url = f"https://www.naukri.com/{slug}-jobs-in-{location.lower()}"
            response = await client.get(url)

            if response.status_code != 200:
                return []

            html = response.text
            import json

            # Naukri embeds job data in a script tag with type application/ld+json
            marker = '<script type="application/ld+json">'
            pos = 0
            while marker in html[pos:]:
                start = html.index(marker, pos) + len(marker)
                end = html.index("</script>", start)
                pos = end

                try:
                    ld_data = json.loads(html[start:end])

                    # Look for JobPosting schema
                    if isinstance(ld_data, dict) and ld_data.get("@type") == "JobPosting":
                        listings = [ld_data]
                    elif isinstance(ld_data, list):
                        listings = [item for item in ld_data if isinstance(item, dict) and item.get("@type") == "JobPosting"]
                    elif isinstance(ld_data, dict) and "itemListElement" in ld_data:
                        listings = [item.get("item", {}) for item in ld_data.get("itemListElement", [])]
                    else:
                        continue

                    for listing in listings:
                        title = listing.get("title", "")
                        company = listing.get("hiringOrganization", {}).get("name", "")
                        loc = listing.get("jobLocation", {})
                        if isinstance(loc, dict):
                            loc_name = loc.get("address", {}).get("addressLocality", "")
                        elif isinstance(loc, list) and loc:
                            loc_name = loc[0].get("address", {}).get("addressLocality", "")
                        else:
                            loc_name = ""

                        if title and company:
                            jobs.append({
                                "id": hashlib.md5(f"{title}_{company}_{loc_name}".lower().encode()).hexdigest()[:16],
                                "title": title,
                                "company": company,
                                "location": loc_name,
                                "description": listing.get("description", ""),
                                "url": listing.get("url", ""),
                                "platform": "naukri",
                                "posted_date": self._parse_date(listing.get("datePosted")),
                                "salary_min": None,
                                "salary_max": None,
                                "salary_currency": "INR",
                                "job_type": listing.get("employmentType", ""),
                                "work_mode": "",
                                "experience_required": None,
                                "application_status": "scraped",
                            })

                except (json.JSONDecodeError, ValueError):
                    continue

        except Exception as e:
            logger.warning("Naukri HTML fallback failed: %s", e)

        return jobs

    @staticmethod
    def _estimate_experience(profile: UserProfile) -> int:
        """Estimate years of experience from profile."""
        if not profile.work_experience:
            return 0
        from datetime import date
        earliest = None
        for exp in profile.work_experience:
            try:
                parts = exp.start_date.split("-")
                year = int(parts[0])
                month = int(parts[1]) if len(parts) > 1 else 1
                start = date(year, month, 1)
                if earliest is None or start < earliest:
                    earliest = start
            except (ValueError, IndexError):
                continue
        if earliest:
            return max(0, (date.today() - earliest).days // 365)
        return 0

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[float | None, float | None]:
        """Parse Naukri salary string like '8-15 Lacs PA' into min/max."""
        if not salary_str:
            return None, None
        import re
        # Match patterns like "8-15 Lacs" or "10-20 Lakhs"
        match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:Lacs?|Lakhs?)", salary_str, re.IGNORECASE)
        if match:
            return float(match.group(1)) * 100000, float(match.group(2)) * 100000
        return None, None

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            # Try common Naukri date formats
            for fmt in ("%d %b %Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            return None
