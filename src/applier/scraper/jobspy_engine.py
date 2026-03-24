"""JobSpy wrapper - scrapes jobs from LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter."""

import hashlib
import logging
from datetime import datetime

import pandas as pd
from jobspy import scrape_jobs

from src.applier.profile.loader import UserProfile

logger = logging.getLogger(__name__)


def _generate_job_id(title: str, company: str, location: str) -> str:
    """Generate a unique job ID from title + company + location."""
    key = f"{title.lower().strip()}_{company.lower().strip()}_{location.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


class JobSpyEngine:
    """Wraps python-jobspy for multi-platform job scraping."""

    def __init__(self, config: dict):
        scraping = config.get("scraping", {}).get("jobspy", {})
        self.platforms = scraping.get("platforms", ["indeed", "google"])
        self.results_per_platform = scraping.get("results_per_platform", 50)
        self.hours_old = scraping.get("hours_old", 24)
        self.country = scraping.get("country", "India")

    def scrape(self, profile: UserProfile) -> list[dict]:
        """Scrape jobs from all configured platforms using JobSpy."""
        # Build search terms from target roles
        search_terms = profile.job_preferences.target_roles[:5]
        search_query = " OR ".join(f'"{role}"' for role in search_terms)

        location = profile.personal.location.city or "India"
        is_remote = "Remote" in profile.job_preferences.work_mode

        logger.info(
            "Scraping jobs: query='%s', platforms=%s, location='%s'",
            search_query, self.platforms, location,
        )

        try:
            df = scrape_jobs(
                site_name=self.platforms,
                search_term=search_query,
                location=location,
                results_wanted=self.results_per_platform,
                hours_old=self.hours_old,
                country_indeed=self.country,
                is_remote=is_remote if is_remote else None,
            )
        except Exception as e:
            logger.error("JobSpy scraping failed: %s", e)
            return []

        if df is None or df.empty:
            logger.info("No jobs found from JobSpy")
            return []

        jobs = self._dataframe_to_jobs(df)
        logger.info("JobSpy returned %d jobs from %s", len(jobs), self.platforms)
        return jobs

    def _dataframe_to_jobs(self, df: pd.DataFrame) -> list[dict]:
        """Convert JobSpy DataFrame to a list of job dicts."""
        jobs = []
        for _, row in df.iterrows():
            title = str(row.get("title", "")).strip()
            company = str(row.get("company", "")).strip()
            location = str(row.get("location", "")).strip()

            if not title or not company:
                continue

            job = {
                "id": _generate_job_id(title, company, location),
                "title": title,
                "company": company,
                "location": location,
                "description": str(row.get("description", "")),
                "url": str(row.get("job_url", "")),
                "platform": str(row.get("site", "unknown")),
                "posted_date": self._parse_date(row.get("date_posted")),
                "salary_min": self._parse_float(row.get("min_amount")),
                "salary_max": self._parse_float(row.get("max_amount")),
                "salary_currency": str(row.get("currency", "")),
                "job_type": str(row.get("job_type", "")),
                "work_mode": "Remote" if row.get("is_remote") else "",
                "experience_required": None,
                "application_status": "scraped",
            }
            jobs.append(job)

        return jobs

    @staticmethod
    def _parse_date(value) -> datetime | None:
        if pd.isna(value) or value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_float(value) -> float | None:
        if pd.isna(value) or value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
