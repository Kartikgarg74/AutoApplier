"""Tests for Telegram bot — rate limiting, authorization, and notifications."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from src.notifications.telegram_bot import TelegramBot


class TestRateLimiting:
    """Test command rate limiting."""

    def test_allows_within_limit(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        for _ in range(5):
            assert bot._check_rate_limit("status") is True

    def test_blocks_over_limit(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        for _ in range(5):
            bot._check_rate_limit("status")
        assert bot._check_rate_limit("status") is False

    def test_different_commands_have_separate_limits(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        for _ in range(5):
            bot._check_rate_limit("status")
        # status is exhausted, but scrape should still work
        assert bot._check_rate_limit("scrape") is True

    def test_rate_limit_resets_after_window(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        # Fill up the limit
        for _ in range(5):
            bot._check_rate_limit("status")
        assert bot._check_rate_limit("status") is False

        # Manually age the timestamps past the window
        old_time = datetime.now() - timedelta(minutes=2)
        bot._command_timestamps["status"] = [old_time] * 5

        # Should be allowed again
        assert bot._check_rate_limit("status") is True


class TestAuthorization:
    """Test chat authorization."""

    def test_authorized_chat(self):
        bot = TelegramBot(bot_token="test", chat_id="12345")
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        assert bot._is_authorized(mock_update) is True

    def test_unauthorized_chat(self):
        bot = TelegramBot(bot_token="test", chat_id="12345")
        mock_update = MagicMock()
        mock_update.effective_chat.id = 99999
        assert bot._is_authorized(mock_update) is False


class TestNotifications:
    """Test notification methods."""

    @pytest.mark.asyncio
    async def test_send_message_skips_when_not_initialized(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        # app is None, should not raise
        await bot.send_message("test message")

    @pytest.mark.asyncio
    async def test_send_daily_summary_formats_correctly(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        bot.app = MagicMock()
        bot.app.bot.send_message = AsyncMock()

        stats = {"scraped": 50, "scored": 50, "applied": 10, "skipped": 30, "avg_score": 72}
        await bot.send_daily_summary(stats)

        call_args = bot.app.bot.send_message.call_args
        text = call_args.kwargs["text"]
        assert "50" in text
        assert "10" in text
        assert "72" in text


class TestApprovalFlow:
    """Test the approval/rejection workflow."""

    @pytest.mark.asyncio
    async def test_wait_for_approval_timeout(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        # Very short timeout to test
        result = await bot.wait_for_approval("job-001", timeout_minutes=0.001)
        assert result == "timeout"
        # Callback should be cleaned up
        assert "job-001" not in bot._approval_callbacks

    def test_is_paused_default(self):
        bot = TelegramBot(bot_token="test", chat_id="123")
        assert bot.is_paused is False
