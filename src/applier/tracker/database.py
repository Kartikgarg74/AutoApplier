"""Application tracker - CRUD operations on applications and daily stats."""

import json
import logging
from datetime import datetime, date

from src.database.models import get_session, Application, DailyStat, Job

logger = logging.getLogger(__name__)


class ApplicationTracker:
    """Tracks job applications in SQLite."""

    def record_application(self, job: dict, resume_path: str = "",
                           cover_letter_path: str = "", score: float = 0,
                           screenshot_path: str = "") -> str:
        """Record a new application. Returns the application ID."""
        session = get_session()
        try:
            app_id = f"app_{job['id']}_{int(datetime.now().timestamp())}"
            app = Application(
                id=app_id,
                job_id=job["id"],
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                platform=job.get("platform", ""),
                job_url=job.get("url", ""),
                applied_date=datetime.utcnow(),
                relevance_score=score,
                status="applied",
                resume_version=resume_path,
                cover_letter_version=cover_letter_path,
                screenshot_path=screenshot_path,
            )
            session.add(app)

            # Update job status
            db_job = session.query(Job).filter_by(id=job["id"]).first()
            if db_job:
                db_job.application_status = "applied"

            # Update daily stats
            self._update_daily_stats(session, job.get("platform", ""))

            session.commit()
            logger.info("Recorded application: %s at %s", job["title"], job["company"])
            return app_id

        except Exception as e:
            session.rollback()
            logger.error("Failed to record application: %s", e)
            return ""
        finally:
            session.close()

    def update_status(self, app_id: str, new_status: str, notes: str = "") -> None:
        """Update an application's status."""
        session = get_session()
        try:
            app = session.query(Application).filter_by(id=app_id).first()
            if app:
                app.status = new_status
                if notes:
                    app.notes = notes
                if new_status in ("interview", "rejected", "offer"):
                    app.response_date = datetime.utcnow()
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to update application status: %s", e)
        finally:
            session.close()

    def get_today_count(self, platform: str | None = None) -> int:
        """Get number of applications today, optionally filtered by platform."""
        session = get_session()
        try:
            today = date.today()
            query = session.query(Application).filter(
                Application.applied_date >= datetime.combine(today, datetime.min.time())
            )
            if platform:
                query = query.filter(Application.platform == platform)
            return query.count()
        finally:
            session.close()

    def get_pending_approvals(self) -> list[dict]:
        """Get jobs that are scored but awaiting approval."""
        session = get_session()
        try:
            jobs = session.query(Job).filter(
                Job.application_status == "scored",
                Job.relevance_score >= 60,
            ).order_by(Job.relevance_score.desc()).all()

            return [
                {
                    "id": j.id,
                    "title": j.title,
                    "company": j.company,
                    "score": j.relevance_score,
                    "recommendation": j.ai_recommendation,
                    "url": j.url,
                }
                for j in jobs
            ]
        finally:
            session.close()

    def get_recent_applications(self, limit: int = 10) -> list[dict]:
        """Get the most recent applications."""
        session = get_session()
        try:
            apps = session.query(Application).order_by(
                Application.applied_date.desc()
            ).limit(limit).all()

            return [
                {
                    "id": a.id,
                    "title": a.job_title,
                    "company": a.company,
                    "platform": a.platform,
                    "score": a.relevance_score,
                    "status": a.status,
                    "date": a.applied_date.strftime("%Y-%m-%d") if a.applied_date else "",
                }
                for a in apps
            ]
        finally:
            session.close()

    def get_stats(self, days: int = 30) -> dict:
        """Get application statistics for the last N days."""
        session = get_session()
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)

            apps = session.query(Application).filter(
                Application.applied_date >= cutoff
            ).all()

            if not apps:
                return {"total": 0, "by_platform": {}, "by_status": {},
                        "avg_score": 0, "response_rate": 0, "interview_rate": 0}

            total = len(apps)
            by_platform = {}
            by_status = {}
            scores = []

            for app in apps:
                by_platform[app.platform] = by_platform.get(app.platform, 0) + 1
                by_status[app.status] = by_status.get(app.status, 0) + 1
                if app.relevance_score:
                    scores.append(app.relevance_score)

            responses = sum(1 for a in apps if a.status in ("interview", "rejected", "offer"))
            interviews = sum(1 for a in apps if a.status == "interview")

            return {
                "total": total,
                "by_platform": by_platform,
                "by_status": by_status,
                "avg_score": sum(scores) / len(scores) if scores else 0,
                "response_rate": (responses / total * 100) if total > 0 else 0,
                "interview_rate": (interviews / total * 100) if total > 0 else 0,
            }
        finally:
            session.close()

    def _update_daily_stats(self, session, platform: str) -> None:
        """Update or create daily stats record."""
        today = date.today()
        stat = session.query(DailyStat).filter_by(date=today).first()

        if not stat:
            stat = DailyStat(date=today, total_applied=1, platforms_used=json.dumps([platform]))
            session.add(stat)
        else:
            stat.total_applied += 1
            platforms = json.loads(stat.platforms_used or "[]")
            if platform and platform not in platforms:
                platforms.append(platform)
                stat.platforms_used = json.dumps(platforms)
