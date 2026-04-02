"""Shared test fixtures for AutoApplier tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sample_config():
    """Minimal config for testing."""
    return {
        "ai": {
            "primary_provider": "anthropic",
            "fallback_provider": "groq",
            "anthropic": {
                "api_key": "test-key-anthropic",
                "models": {
                    "cheap": "claude-haiku-4-5-20251001",
                    "quality": "claude-sonnet-4-6",
                },
            },
            "groq": {
                "api_key": "test-key-groq",
                "model": "llama-3.3-70b-versatile",
                "rate_limit": 14400,
            },
        },
        "application_mode": {
            "default": "approve_first",
            "max_applications_per_day": 30,
            "max_applications_per_platform": {},
        },
        "scraping": {
            "scan_schedule": {
                "times": ["08:00", "18:00"],
                "timezone": "Asia/Kolkata",
            }
        },
        "notifications": {
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "chat_id": "",
            }
        },
        "tracking": {
            "local_db": "data/test.db",
        },
    }


@pytest.fixture
def sample_job():
    """A sample job dict for testing."""
    return {
        "id": "test-job-001",
        "title": "Senior Python Developer",
        "company": "TestCorp",
        "description": "We need a Python developer with 5 years experience in FastAPI, Django, and AWS.",
        "platform": "linkedin",
        "url": "https://example.com/job/001",
        "location": "Remote",
    }


@pytest.fixture
def mock_telegram_bot():
    """A mocked TelegramBot."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_job_card = AsyncMock()
    bot.send_daily_summary = AsyncMock()
    bot.send_application_confirmation = AsyncMock()
    bot.is_paused = False
    return bot
