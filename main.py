"""AutoApplier — AI-Powered Job Application Bot — Main Entry Point."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import setup_logging, get_logger
from src.utils.config import ConfigLoader
from src.database.models import init_db
from src.ai.router import AIRouter
from src.notifications.telegram_bot import TelegramBot

logger = get_logger("autoapplier")


def parse_args():
    parser = argparse.ArgumentParser(description="AutoApplier — AI-Powered Job Application Bot")
    parser.add_argument("--user", default="kartik",
                        help="User profile to load (default: kartik)")
    parser.add_argument("--mode", default=None,
                        choices=["approve_first", "auto", "hybrid"],
                        help="Application mode override")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run mode — scrape and score but don't submit")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: INFO)")
    parser.add_argument("--scan-once", action="store_true",
                        help="Run a single scan cycle and exit (for testing)")
    return parser.parse_args()


async def run_applier(args, config, ai_router, telegram_bot):
    """Run the auto job applier."""
    from src.applier.profile.loader import ProfileLoader
    from src.applier.profile.validator import ProfileValidator
    from src.applier.orchestrator import ApplicationOrchestrator
    from src.utils.scheduler import JobScheduler

    profile_loader = ProfileLoader(config_dir=PROJECT_ROOT / "config")
    profile = profile_loader.load(user=args.user)
    logger.info("Profile loaded: %s", profile.personal.full_name)

    validator = ProfileValidator()
    errors = validator.validate(profile)
    if errors:
        logger.warning("Profile validation warnings:")
        for err in errors:
            logger.warning("  - %s", err)
    else:
        logger.info("Profile validation: OK")

    applier_mode = args.mode if args.mode in ("approve_first", "auto", "hybrid") else None
    if applier_mode:
        config.setdefault("application_mode", {})["default"] = applier_mode

    orchestrator = ApplicationOrchestrator(
        config=config,
        ai_router=ai_router,
        profile=profile,
        telegram_bot=telegram_bot,
        dry_run=args.dry_run,
    )

    mode = config.get("application_mode", {}).get("default", "approve_first")
    logger.info("Auto Job Applier ready (mode=%s, dry_run=%s)", mode, args.dry_run)
    logger.info("Target roles: %s", ", ".join(profile.job_preferences.target_roles[:3]) + "...")

    if telegram_bot:
        await telegram_bot.send_message(
            f"AutoApplier started!\n"
            f"User: {profile.personal.full_name}\n"
            f"Mode: {mode}\n"
            f"Dry run: {args.dry_run}"
        )

    if args.scan_once:
        try:
            stats = await orchestrator.run_pipeline()
            logger.info("Single run complete: %s", stats)
        except Exception as e:
            logger.error("Single run failed: %s", e)
            if telegram_bot:
                await telegram_bot.send_message(
                    f"Pipeline FAILED (single run)\nError: {str(e)[:200]}"
                )
            raise
        return

    scheduler = JobScheduler()

    scan_schedule = config.get("scraping", {}).get("scan_schedule", {})
    scan_times = scan_schedule.get("times", ["08:00", "18:00"])
    timezone = scan_schedule.get("timezone", "Asia/Kolkata")

    for time_str in scan_times:
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_cron_job(
            func=orchestrator.run_pipeline,
            hour=hour, minute=minute,
            timezone=timezone,
            job_id=f"applier_scan_{time_str}",
        )

    async def send_daily_analytics():
        from src.applier.tracker.analytics import AnalyticsEngine
        report = AnalyticsEngine().generate_report(days=1)
        if telegram_bot:
            await telegram_bot.send_message(report)

    scheduler.add_cron_job(
        func=send_daily_analytics,
        hour=21, minute=0,
        timezone=timezone,
        job_id="applier_daily_summary",
    )

    scheduler.start()
    logger.info("Applier scheduled: scans at %s (%s)", scan_times, timezone)

    stop_event = asyncio.Event()

    def signal_handler():
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown()


async def main():
    args = parse_args()

    setup_logging(log_dir=str(PROJECT_ROOT / "data" / "logs"), level=args.log_level)
    logger.info("AutoApplier starting...")

    config_loader = ConfigLoader(project_root=PROJECT_ROOT)
    config = config_loader.load(user=args.user)
    logger.info("Configuration loaded for user: %s", args.user)

    db_path = config.get("tracking", {}).get("local_db", "data/autoapplier.db")
    init_db(str(PROJECT_ROOT / db_path))
    logger.info("Database initialized: %s", db_path)

    ai_router = AIRouter(config)
    providers = []
    if ai_router.claude:
        providers.append("Claude")
    if ai_router.groq:
        providers.append("Groq")
    logger.info("AI Router ready: [%s]", ", ".join(providers))

    telegram_config = config.get("notifications", {}).get("telegram", {})
    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    telegram_bot = None
    if bot_token and chat_id and telegram_config.get("enabled", False):
        telegram_bot = TelegramBot(bot_token=bot_token, chat_id=chat_id)
        await telegram_bot.start()
        logger.info("Telegram bot started")
    else:
        logger.warning("Telegram bot disabled (missing token/chat_id or disabled in config)")

    try:
        await run_applier(args, config, ai_router, telegram_bot)
    finally:
        if telegram_bot:
            await telegram_bot.send_message("AutoApplier shutting down.")
            await telegram_bot.stop()
        logger.info("Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())
