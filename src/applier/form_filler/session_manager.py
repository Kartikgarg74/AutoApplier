"""Browser session manager - handles cookies, sessions, and browser lifecycle."""

import json
import logging
import re
from pathlib import Path

from src.utils.security import encrypt_data, decrypt_data, secure_directory, secure_file, sanitize_error

logger = logging.getLogger(__name__)

# Allowed platform names (prevents path traversal via platform param)
ALLOWED_PLATFORMS = {"greenhouse", "lever", "linkedin", "indeed", "workday", "wellfound", "naukri", "generic"}


class SessionManager:
    """Manages browser cookies and sessions per platform."""

    def __init__(self, cookies_dir: str = "data/cookies"):
        self.cookies_dir = Path(cookies_dir)
        secure_directory(self.cookies_dir)

    def _validate_platform(self, platform: str) -> str:
        """Validate platform name to prevent path traversal."""
        safe = re.sub(r"[^\w-]", "", platform.lower())
        if safe not in ALLOWED_PLATFORMS:
            logger.warning("Unknown platform '%s', using 'generic'", platform)
            return "generic"
        return safe

    async def save_cookies(self, context, platform: str) -> None:
        """Save browser cookies for a platform (encrypted)."""
        platform = self._validate_platform(platform)
        cookies = await context.cookies()
        cookie_path = self.cookies_dir / f"{platform}.enc"

        data = json.dumps(cookies).encode()
        encrypted = encrypt_data(data)

        with open(cookie_path, "wb") as f:
            f.write(encrypted)
        secure_file(cookie_path)

        logger.info("Saved %d cookies for %s (encrypted)", len(cookies), platform)

    async def load_cookies(self, context, platform: str) -> bool:
        """Load saved cookies for a platform (decrypted). Returns True if loaded."""
        platform = self._validate_platform(platform)
        cookie_path = self.cookies_dir / f"{platform}.enc"

        # Also check legacy plaintext files and migrate them
        legacy_path = self.cookies_dir / f"{platform}.json"
        if legacy_path.exists() and not cookie_path.exists():
            await self._migrate_legacy_cookies(legacy_path, cookie_path)

        if not cookie_path.exists():
            return False

        try:
            with open(cookie_path, "rb") as f:
                encrypted = f.read()
            decrypted = decrypt_data(encrypted)
            cookies = json.loads(decrypted)
            await context.add_cookies(cookies)
            logger.info("Loaded %d cookies for %s", len(cookies), platform)
            return True
        except Exception as e:
            logger.warning("Failed to load cookies for %s: %s", platform, sanitize_error(e))
            return False

    async def _migrate_legacy_cookies(self, legacy_path: Path, new_path: Path) -> None:
        """Migrate plaintext cookie files to encrypted format."""
        try:
            with open(legacy_path) as f:
                data = f.read().encode()
            encrypted = encrypt_data(data)
            with open(new_path, "wb") as f:
                f.write(encrypted)
            secure_file(new_path)
            legacy_path.unlink()  # Delete plaintext file
            logger.info("Migrated cookies from plaintext to encrypted: %s", new_path.name)
        except Exception as e:
            logger.warning("Cookie migration failed: %s", sanitize_error(e))

    def has_cookies(self, platform: str) -> bool:
        """Check if saved cookies exist for a platform."""
        platform = self._validate_platform(platform)
        return (self.cookies_dir / f"{platform}.enc").exists()
