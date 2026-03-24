"""Wellfound (formerly AngelList) scraper - startup job listings via GraphQL API."""

import hashlib
import logging
from datetime import datetime

import httpx

from .base_scraper import BaseScraper
from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)

# Wellfound uses a GraphQL API internally
WELLFOUND_GRAPHQL_URL = "https://wellfound.com/graphql"

JOBS_QUERY = """
query JobSearchQuery($query: String!, $page: Int!, $perPage: Int!) {
  talent {
    jobListings(filters: {query: $query, page: $page, perPage: $perPage}) {
      edges {
        node {
          id
          title
          slug
          description
          jobType
          remote
          liveStartAt
          primaryRoleTitle
          locationNames
          compensation
          startup {
            name
            companyUrl
            highConcept
            logoUrl
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


class WellfoundScraper(BaseScraper):
    """Scrapes startup jobs from Wellfound (AngelList Talent).

    Wellfound has:
    - High interview rate (5-6%) due to startup culture
    - Lower ATS friction than enterprise platforms
    - GraphQL API accessible without authentication for job listings
    - Fallback to httpx-based HTML scraping if GraphQL changes
    """

    platform_name = "wellfound"

    def __init__(self, config: dict):
        super().__init__(config)
        wf_config = config.get("scraping", {}).get("custom_scrapers", {}).get("wellfound", {})
        self.enabled = wf_config.get("enabled", False)
        self.max_pages = wf_config.get("max_pages", 3)

    async def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from Wellfound matching the user's target roles."""
        if not self.enabled:
            return []

        all_jobs = []
        search_terms = profile.job_preferences.target_roles[:3]

        async with httpx.AsyncClient(timeout=30, headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
        }) as client:
            for term in search_terms:
                try:
                    jobs = await self._search_jobs(client, term)
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning("Wellfound search failed for '%s': %s", term, e)

        logger.info("Wellfound: scraped %d jobs", len(all_jobs))
        return all_jobs

    async def _search_jobs(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        """Search for jobs using Wellfound's GraphQL API."""
        jobs = []

        for page in range(1, self.max_pages + 1):
            try:
                response = await client.post(WELLFOUND_GRAPHQL_URL, json={
                    "query": JOBS_QUERY,
                    "variables": {"query": query, "page": page, "perPage": 20},
                })

                if response.status_code != 200:
                    # GraphQL might be gated — fall back to HTML scraping
                    return await self._scrape_html(client, query)

                data = response.json()
                edges = (data.get("data", {}).get("talent", {})
                         .get("jobListings", {}).get("edges", []))

                if not edges:
                    break

                for edge in edges:
                    node = edge.get("node", {})
                    startup = node.get("startup", {})

                    title = node.get("title", "")
                    company = startup.get("name", "")
                    location = ", ".join(node.get("locationNames", []))

                    job = {
                        "id": hashlib.md5(f"{title}_{company}_{location}".lower().encode()).hexdigest()[:16],
                        "title": title,
                        "company": company,
                        "location": location,
                        "description": node.get("description", ""),
                        "url": f"https://wellfound.com/jobs/{node.get('slug', '')}",
                        "platform": "wellfound",
                        "posted_date": self._parse_date(node.get("liveStartAt")),
                        "salary_min": None,
                        "salary_max": None,
                        "salary_currency": "",
                        "job_type": node.get("jobType", ""),
                        "work_mode": "Remote" if node.get("remote") else "",
                        "experience_required": None,
                        "application_status": "scraped",
                    }
                    jobs.append(job)

                # Check if more pages
                page_info = (data.get("data", {}).get("talent", {})
                             .get("jobListings", {}).get("pageInfo", {}))
                if not page_info.get("hasNextPage", False):
                    break

            except Exception as e:
                logger.warning("Wellfound page %d error: %s", page, e)
                break

        return jobs

    async def _scrape_html(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        """Fallback: scrape Wellfound job listings via HTML page."""
        jobs = []
        try:
            url = f"https://wellfound.com/role/{query.lower().replace(' ', '-')}"
            response = await client.get(url)

            if response.status_code != 200:
                logger.debug("Wellfound HTML fallback failed for '%s': %d", query, response.status_code)
                return []

            # Parse basic job cards from the HTML using simple string matching
            # Wellfound renders job data in JSON-LD or __NEXT_DATA__ script tags
            html = response.text

            # Look for __NEXT_DATA__ JSON embedded in the page
            import json
            marker = '__NEXT_DATA__" type="application/json">'
            if marker in html:
                start = html.index(marker) + len(marker)
                end = html.index("</script>", start)
                try:
                    next_data = json.loads(html[start:end])
                    # Navigate the Next.js data structure to find job listings
                    props = next_data.get("props", {}).get("pageProps", {})
                    listings = props.get("listings", props.get("jobListings", []))

                    for listing in listings:
                        if isinstance(listing, dict):
                            title = listing.get("title", listing.get("name", ""))
                            company = listing.get("companyName", listing.get("startup", {}).get("name", ""))
                            location = listing.get("location", "")

                            if title and company:
                                jobs.append({
                                    "id": hashlib.md5(f"{title}_{company}_{location}".lower().encode()).hexdigest()[:16],
                                    "title": title,
                                    "company": company,
                                    "location": location,
                                    "description": listing.get("description", ""),
                                    "url": listing.get("url", f"https://wellfound.com/jobs"),
                                    "platform": "wellfound",
                                    "posted_date": None,
                                    "salary_min": None,
                                    "salary_max": None,
                                    "salary_currency": "",
                                    "job_type": "",
                                    "work_mode": "",
                                    "experience_required": None,
                                    "application_status": "scraped",
                                })
                except (json.JSONDecodeError, ValueError):
                    pass

        except Exception as e:
            logger.warning("Wellfound HTML scraping failed: %s", e)

        return jobs

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
