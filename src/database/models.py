"""SQLAlchemy 2.0 database models for AutoApplier."""

import json
from datetime import datetime, date
from pathlib import Path

from sqlalchemy import create_engine, String, Float, Integer, Text, DateTime, Date
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Job(Base):
    """Scraped job listing."""
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String, default="")
    platform: Mapped[str] = mapped_column(String, default="")
    posted_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String, default="")
    job_type: Mapped[str] = mapped_column(String, default="")
    work_mode: Mapped[str] = mapped_column(String, default="")
    experience_required: Mapped[str | None] = mapped_column(String, nullable=True)

    # AI-enriched fields
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matching_skills: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    missing_skills: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_recommendation: Mapped[str] = mapped_column(String, default="")
    resume_focus_areas: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    cover_letter_hook: Mapped[str] = mapped_column(Text, default="")

    application_status: Mapped[str] = mapped_column(String, default="scraped")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def get_matching_skills(self) -> list[str]:
        return _safe_json_list(self.matching_skills)

    def get_missing_skills(self) -> list[str]:
        return _safe_json_list(self.missing_skills)

    def get_resume_focus_areas(self) -> list[str]:
        return _safe_json_list(self.resume_focus_areas)


def _safe_json_list(value: str) -> list:
    """Safely parse a JSON list from DB. Returns [] on failure."""
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


class Application(Base):
    """Submitted job application record."""
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    job_title: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    job_url: Mapped[str] = mapped_column(String, default="")
    applied_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="applied")
    resume_version: Mapped[str] = mapped_column(String, default="")
    cover_letter_version: Mapped[str] = mapped_column(String, default="")
    response_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    screenshot_path: Mapped[str] = mapped_column(String, default="")


class DailyStat(Base):
    """Daily application statistics."""
    __tablename__ = "daily_stats"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_scraped: Mapped[int] = mapped_column(Integer, default=0)
    total_scored: Mapped[int] = mapped_column(Integer, default=0)
    total_applied: Mapped[int] = mapped_column(Integer, default=0)
    total_skipped: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float] = mapped_column(Float, default=0.0)
    platforms_used: Mapped[str] = mapped_column(Text, default="[]")  # JSON array


_engine = None
_SessionLocal = None


def init_db(db_path: str = "data/autoapplier.db") -> None:
    """Initialize the database engine and create tables."""
    global _engine, _SessionLocal
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    _SessionLocal = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    """Get a new database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()
