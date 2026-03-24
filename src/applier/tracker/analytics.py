"""Analytics engine - generates application statistics and reports."""

import logging

from .database import ApplicationTracker

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Generates analytics reports for Telegram and logging."""

    def __init__(self):
        self.tracker = ApplicationTracker()

    def generate_report(self, days: int = 30) -> str:
        """Generate a formatted analytics report."""
        stats = self.tracker.get_stats(days=days)

        if stats["total"] == 0:
            return f"No applications in the last {days} days."

        # Platform breakdown
        platform_lines = []
        for platform, count in sorted(stats["by_platform"].items(), key=lambda x: -x[1]):
            pct = count / stats["total"] * 100
            platform_lines.append(f"  {platform.title()}: {count} ({pct:.0f}%)")

        # Status breakdown
        status_lines = []
        for status, count in sorted(stats["by_status"].items(), key=lambda x: -x[1]):
            status_lines.append(f"  {status.title()}: {count}")

        report = (
            f"Application Analytics (Last {days} Days)\n"
            f"{'=' * 32}\n"
            f"Total Applied: {stats['total']}\n"
            f"\n"
            f"By Platform:\n"
            f"{chr(10).join(platform_lines)}\n"
            f"\n"
            f"By Status:\n"
            f"{chr(10).join(status_lines)}\n"
            f"\n"
            f"Response Rate: {stats['response_rate']:.1f}%\n"
            f"Interview Rate: {stats['interview_rate']:.1f}%\n"
            f"Avg Score: {stats['avg_score']:.0f}/100"
        )

        return report

    def generate_daily_summary(self) -> dict:
        """Generate today's summary stats for Telegram."""
        stats = self.tracker.get_stats(days=1)
        return {
            "scraped": 0,  # Filled by orchestrator
            "scored": 0,
            "applied": stats.get("total", 0),
            "skipped": 0,
            "avg_score": stats.get("avg_score", 0),
        }
