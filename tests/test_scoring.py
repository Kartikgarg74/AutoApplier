"""Tests for AI Scorer — scoring, error handling, and batch processing."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.applier.scoring.ai_scorer import AIScorer, ScoringResult


class TestScoringResult:
    """Test the ScoringResult model."""

    def test_default_values(self):
        result = ScoringResult()
        assert result.relevance_score == 0
        assert result.recommendation == "Skip"
        assert result.matching_skills == []
        assert result.missing_skills == []

    def test_from_dict(self):
        data = {
            "relevance_score": 85,
            "matching_skills": ["Python", "FastAPI"],
            "missing_skills": ["Go"],
            "recommendation": "Strong Match",
            "reasoning": "Good fit",
            "resume_focus_areas": ["backend"],
            "cover_letter_hook": "Your FastAPI experience...",
        }
        result = ScoringResult(**data)
        assert result.relevance_score == 85
        assert result.recommendation == "Strong Match"
        assert len(result.matching_skills) == 2


class TestAIScorer:
    """Test the AIScorer class."""

    def test_error_returns_skip_with_sanitized_message(self, sample_job):
        """On AI failure, scorer should return Skip with sanitized error."""
        mock_router = MagicMock()
        mock_router.route_json.side_effect = Exception("API key sk-abc123 is invalid")

        scorer = AIScorer(ai_router=mock_router)

        # Create a minimal mock profile
        mock_profile = MagicMock()
        mock_profile.professional_summary = "Python developer"
        mock_profile.all_skills_flat = ["Python", "FastAPI"]
        mock_profile.work_experience_summary = "5 years"
        mock_profile.job_preferences.target_roles = ["Backend Developer"]

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            scorer._score_single(sample_job, mock_profile)
        )

        assert result.relevance_score == 0
        assert result.recommendation == "Skip"
        # Verify the raw API key is NOT in the reasoning
        assert "sk-abc123" not in result.reasoning

    def test_batch_handles_exceptions(self, sample_job):
        """Batch scoring should handle individual failures gracefully."""
        mock_router = MagicMock()
        scorer = AIScorer(ai_router=mock_router)

        jobs = [sample_job, {**sample_job, "id": "test-002"}]
        mock_profile = MagicMock()
        mock_profile.professional_summary = "Developer"
        mock_profile.all_skills_flat = ["Python"]
        mock_profile.work_experience_summary = "3 years"
        mock_profile.job_preferences.target_roles = ["Developer"]

        # Make route_json raise for all calls
        mock_router.route_json.side_effect = Exception("timeout")

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(
            scorer.score_batch(jobs, mock_profile)
        )

        assert len(results) == 2
        for job, result in results:
            assert result.recommendation == "Skip"
