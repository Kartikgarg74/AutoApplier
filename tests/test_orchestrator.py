"""Tests for ApplicationOrchestrator — pipeline flow and error handling."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestOrchestratorPipeline:
    """Test the orchestrator pipeline behavior."""

    @pytest.mark.asyncio
    async def test_scraping_failure_sends_telegram_alert(self, sample_config, mock_telegram_bot):
        """When scraping fails, orchestrator must notify via Telegram."""
        with patch("src.applier.orchestrator.ScrapingOrchestrator") as MockScraper, \
             patch("src.applier.orchestrator.ScoringPipeline"), \
             patch("src.applier.orchestrator.DocumentPipeline"), \
             patch("src.applier.orchestrator.FormFillingEngine"), \
             patch("src.applier.orchestrator.ApplicationTracker"), \
             patch("src.applier.orchestrator.AnalyticsEngine"):

            from src.applier.orchestrator import ApplicationOrchestrator

            mock_scraper_instance = MockScraper.return_value
            mock_scraper_instance.run = AsyncMock(side_effect=Exception("Network timeout"))

            mock_profile = MagicMock()
            orchestrator = ApplicationOrchestrator(
                config=sample_config,
                ai_router=MagicMock(),
                profile=mock_profile,
                telegram_bot=mock_telegram_bot,
            )

            stats = await orchestrator.run_pipeline()

            assert stats["errors"] == 1
            mock_telegram_bot.send_message.assert_called()
            call_text = mock_telegram_bot.send_message.call_args[0][0]
            assert "Scraping FAILED" in call_text

    @pytest.mark.asyncio
    async def test_empty_scrape_returns_early(self, sample_config):
        """Pipeline should exit cleanly when no jobs are found."""
        with patch("src.applier.orchestrator.ScrapingOrchestrator") as MockScraper, \
             patch("src.applier.orchestrator.ScoringPipeline"), \
             patch("src.applier.orchestrator.DocumentPipeline"), \
             patch("src.applier.orchestrator.FormFillingEngine"), \
             patch("src.applier.orchestrator.ApplicationTracker"), \
             patch("src.applier.orchestrator.AnalyticsEngine"):

            from src.applier.orchestrator import ApplicationOrchestrator

            mock_scraper_instance = MockScraper.return_value
            mock_scraper_instance.run = AsyncMock(return_value=[])
            mock_scraper_instance.get_stats = MagicMock(return_value={"by_platform": {}})

            mock_profile = MagicMock()
            orchestrator = ApplicationOrchestrator(
                config=sample_config,
                ai_router=MagicMock(),
                profile=mock_profile,
                telegram_bot=None,
            )

            stats = await orchestrator.run_pipeline()

            assert stats["scraped"] == 0
            assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_scoring_failure_sends_telegram_alert(self, sample_config, mock_telegram_bot):
        """When scoring fails, orchestrator must notify via Telegram."""
        with patch("src.applier.orchestrator.ScrapingOrchestrator") as MockScraper, \
             patch("src.applier.orchestrator.ScoringPipeline") as MockScorer, \
             patch("src.applier.orchestrator.DocumentPipeline"), \
             patch("src.applier.orchestrator.FormFillingEngine"), \
             patch("src.applier.orchestrator.ApplicationTracker"), \
             patch("src.applier.orchestrator.AnalyticsEngine"):

            from src.applier.orchestrator import ApplicationOrchestrator

            mock_scraper_instance = MockScraper.return_value
            mock_scraper_instance.run = AsyncMock(return_value=[{"id": "1", "title": "Dev", "company": "Co"}])
            mock_scraper_instance.get_stats = MagicMock(return_value={"by_platform": {"linkedin": 1}})

            mock_scorer_instance = MockScorer.return_value
            mock_scorer_instance.run = AsyncMock(side_effect=Exception("AI provider down"))

            mock_profile = MagicMock()
            orchestrator = ApplicationOrchestrator(
                config=sample_config,
                ai_router=MagicMock(),
                profile=mock_profile,
                telegram_bot=mock_telegram_bot,
            )

            stats = await orchestrator.run_pipeline()

            assert stats["errors"] == 1
            # Should have sent scrape success + scoring failure
            calls = mock_telegram_bot.send_message.call_args_list
            texts = [call[0][0] for call in calls]
            assert any("Scoring FAILED" in t for t in texts)
