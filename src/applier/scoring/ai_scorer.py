"""AI-powered deep job scoring using the A-G rubric (career-ops port).

Flow per job:
  1. Heuristic legitimacy check (free)     -> maybe early-skip
  2. A-G rubric call (cheap tier LLM)      -> overall score + per-block breakdown
  3. Combine heuristic + LLM legitimacy    -> final tier
  4. Persist to DB + emit markdown report
"""

import asyncio
import json
import logging

from pydantic import BaseModel, Field

from src.ai.router import AIRouter
from src.ai.prompts.rubric import RUBRIC_SYSTEM_PROMPT, build_rubric_prompt
from src.applier.profile.loader import UserProfile
from src.applier.scoring.legitimacy import heuristic_tier, combine_tiers
from src.database.models import get_session, Job
from src.reporting import MarkdownReportWriter
from src.utils.security import sanitize_error
from src.utils.states import AppState

logger = logging.getLogger(__name__)


class ScoringResult(BaseModel):
    """Result from A-G rubric scoring (carries both flat and block data)."""
    relevance_score: float = 0
    matching_skills: list[str] = []
    missing_skills: list[str] = []
    recommendation: str = "Skip"
    reasoning: str = ""
    resume_focus_areas: list[str] = []
    cover_letter_hook: str = ""

    # A-G rubric extensions
    blocks: dict = Field(default_factory=dict)
    legitimacy_tier: str = "proceed_with_caution"
    legitimacy_signals: list[str] = []
    report_path: str = ""

    @property
    def is_suspicious(self) -> bool:
        return self.legitimacy_tier == "suspicious"

    @property
    def should_generate_docs(self) -> bool:
        """Gate for Sonnet-tier CV rewrite — skip if suspicious or too weak."""
        return (
            not self.is_suspicious
            and self.recommendation != "Skip"
            and self.relevance_score >= 50
        )


class AIScorer:
    """Scores jobs against user profile using the A-G rubric."""

    def __init__(
        self,
        ai_router: AIRouter,
        max_concurrent: int = 5,
        report_writer: MarkdownReportWriter | None = None,
        legitimacy_gate_enabled: bool = True,
    ):
        self.ai_router = ai_router
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.report_writer = report_writer or MarkdownReportWriter()
        self.legitimacy_gate_enabled = legitimacy_gate_enabled

    async def score(self, job: dict, profile: UserProfile) -> ScoringResult:
        """Score a single job using the A-G rubric."""
        async with self.semaphore:
            return await self._score_single(job, profile)

    async def _score_single(self, job: dict, profile: UserProfile) -> ScoringResult:
        # 1. Cheap heuristic legitimacy check (no LLM call)
        h_verdict = heuristic_tier(job)

        # Hard short-circuit: obvious scams never reach the LLM
        if self.legitimacy_gate_enabled and h_verdict.should_skip and any(
            s.startswith("scam-phrase") for s in h_verdict.signals
        ):
            logger.info(
                "Pre-LLM skip (scam signals) for %s at %s: %s",
                job.get("title"), job.get("company"), h_verdict.signals,
            )
            result = ScoringResult(
                relevance_score=0,
                recommendation="Skip",
                reasoning="Blocked by legitimacy heuristic (scam signals).",
                legitimacy_tier="suspicious",
                legitimacy_signals=h_verdict.signals,
            )
            self._persist(job, result)
            return result

        # 2. A-G rubric LLM call
        prompt = build_rubric_prompt(
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            description=(job.get("description", "") or "")[:2500],
            url=job.get("url", ""),
            professional_summary=profile.professional_summary,
            skills=", ".join(profile.all_skills_flat),
            experience_summary=profile.work_experience_summary,
            target_roles=profile.job_preferences.target_roles,
            posted_age_days=_age_days(job.get("posted_date")),
        )

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: self.ai_router.route_json(
                    task="job_scoring",
                    prompt=prompt,
                    system_prompt=RUBRIC_SYSTEM_PROMPT,
                    max_tokens=1500,
                    temperature=0.3,
                ),
            )
        except Exception as e:
            logger.error(
                "AI rubric failed for %s at %s: %s",
                job.get("title"), job.get("company"), sanitize_error(e),
            )
            result = ScoringResult(
                relevance_score=0,
                recommendation="Skip",
                reasoning=f"Scoring error: {sanitize_error(e)}",
                legitimacy_tier=h_verdict.tier,
                legitimacy_signals=h_verdict.signals,
            )
            self._persist(job, result)
            return result

        # 3. Parse rubric output into ScoringResult
        blocks = raw.get("blocks", {}) or {}
        b_b = blocks.get("B_cv_match", {}) or {}
        b_e = blocks.get("E_personalization", {}) or {}
        b_f = blocks.get("F_interview_plan", {}) or {}
        b_g = blocks.get("G_legitimacy", {}) or {}

        llm_tier = str(b_g.get("tier", "proceed_with_caution"))
        combined_tier = combine_tiers(h_verdict.tier, llm_tier)
        combined_signals = list(h_verdict.signals) + list(b_g.get("concerning_signals", []) or [])

        result = ScoringResult(
            relevance_score=float(raw.get("overall_score", 0) or 0),
            matching_skills=list(b_b.get("matching_skills", []) or []),
            missing_skills=list(b_b.get("missing_skills", []) or []),
            recommendation=str(raw.get("recommendation", "Skip")),
            reasoning=str(raw.get("reasoning", "")),
            resume_focus_areas=list(b_e.get("resume_focus_areas", []) or []),
            cover_letter_hook=str(b_f.get("cover_letter_hook", "")),
            blocks=blocks,
            legitimacy_tier=combined_tier,
            legitimacy_signals=combined_signals,
        )

        # 4. Write markdown audit-trail report + persist
        try:
            meta = self.report_writer.write(job, result, legitimacy_tier=combined_tier)
            result.report_path = str(meta.path)
        except Exception as e:
            logger.warning("Failed to write markdown report: %s", sanitize_error(e))

        self._persist(job, result)

        logger.info(
            "Scored: %s at %s -> %d/100 (%s) [legitimacy=%s]",
            job.get("title"), job.get("company"),
            int(result.relevance_score), result.recommendation, combined_tier,
        )
        return result

    async def score_batch(self, jobs: list[dict], profile: UserProfile,
                          max_batch: int = 50) -> list[tuple[dict, ScoringResult]]:
        """Score a batch of jobs concurrently."""
        batch = jobs[:max_batch]
        tasks = [self.score(job, profile) for job in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scored = []
        for job, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error("Batch scoring error: %s", result)
                result = ScoringResult(recommendation="Skip", reasoning="Error")
            scored.append((job, result))

        return scored

    def _persist(self, job: dict, result: ScoringResult) -> None:
        """Update job record in DB with scoring + rubric + legitimacy.

        Silently no-ops if the DB is not initialized (e.g. unit tests).
        """
        try:
            session = get_session()
        except RuntimeError:
            return
        try:
            row = session.query(Job).filter_by(id=job["id"]).first()
            if not row:
                return
            row.relevance_score = result.relevance_score
            row.matching_skills = json.dumps(result.matching_skills)
            row.missing_skills = json.dumps(result.missing_skills)
            row.ai_recommendation = result.recommendation
            row.ai_summary = result.reasoning
            row.resume_focus_areas = json.dumps(result.resume_focus_areas)
            row.cover_letter_hook = result.cover_letter_hook
            row.block_scores = json.dumps(result.blocks)
            row.legitimacy_tier = result.legitimacy_tier
            row.legitimacy_signals = json.dumps(result.legitimacy_signals)
            row.report_path = result.report_path
            # Canonical state — SKIP suspicious, else Evaluated
            row.application_status = (
                AppState.SKIP.value if result.is_suspicious else AppState.EVALUATED.value
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to persist job scoring: %s", sanitize_error(e))
        finally:
            session.close()


def _age_days(posted_date) -> int | None:
    """Compute posting age in days if we have a datetime."""
    if posted_date is None:
        return None
    try:
        from datetime import datetime, timezone
        dt = posted_date
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(tz=timezone.utc) - dt).days)
    except Exception:
        return None
