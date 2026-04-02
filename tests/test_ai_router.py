"""Tests for AI Router — startup validation, routing, and fallback."""

import pytest
from unittest.mock import MagicMock, patch

from src.ai.router import AIRouter, MAX_TOKENS_PER_TASK, MAX_TOKENS_ABSOLUTE


class TestAIRouterStartupValidation:
    """Test that AIRouter validates API keys at startup."""

    def test_raises_when_no_providers_configured(self):
        """AIRouter must fail fast if no API keys are set."""
        config = {
            "ai": {
                "anthropic": {"api_key": ""},
                "groq": {"api_key": ""},
            }
        }
        with pytest.raises(RuntimeError, match="No AI providers configured"):
            AIRouter(config)

    def test_works_with_only_anthropic(self, sample_config):
        """Should work fine with just Anthropic configured."""
        sample_config["ai"]["groq"]["api_key"] = ""
        with patch("src.ai.router.ClaudeClient"):
            router = AIRouter(sample_config)
            assert router.claude is not None
            assert router.groq is None

    def test_works_with_only_groq(self, sample_config):
        """Should work fine with just Groq configured."""
        sample_config["ai"]["anthropic"]["api_key"] = ""
        with patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            assert router.claude is None
            assert router.groq is not None

    def test_works_with_both_providers(self, sample_config):
        """Should initialize both when both keys present."""
        with patch("src.ai.router.ClaudeClient"), patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            assert router.claude is not None
            assert router.groq is not None


class TestTokenCapping:
    """Test token cap enforcement."""

    def test_caps_to_task_limit(self, sample_config):
        with patch("src.ai.router.ClaudeClient"), patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            assert router._cap_tokens("job_scoring", 5000) == 1024

    def test_caps_to_absolute_limit(self, sample_config):
        with patch("src.ai.router.ClaudeClient"), patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            assert router._cap_tokens("unknown_task", 99999) == MAX_TOKENS_ABSOLUTE

    def test_allows_within_limit(self, sample_config):
        with patch("src.ai.router.ClaudeClient"), patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            assert router._cap_tokens("job_scoring", 512) == 512


class TestTaskRouting:
    """Test that tasks route to the correct tier."""

    def test_scoring_routes_to_cheap(self, sample_config):
        with patch("src.ai.router.ClaudeClient") as mock_claude, \
             patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            client, model = router._get_client_and_model("job_scoring")
            assert model == "claude-haiku-4-5-20251001"

    def test_resume_routes_to_quality(self, sample_config):
        with patch("src.ai.router.ClaudeClient") as mock_claude, \
             patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            client, model = router._get_client_and_model("resume_generation")
            assert model == "claude-sonnet-4-6"

    def test_fallback_routes_to_groq(self, sample_config):
        with patch("src.ai.router.ClaudeClient"), \
             patch("src.ai.router.GroqClient"):
            router = AIRouter(sample_config)
            client, model = router._get_client_and_model("job_scoring", use_fallback=True)
            assert model == "llama-3.3-70b-versatile"
