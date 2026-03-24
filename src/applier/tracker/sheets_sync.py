"""Google Sheets sync - optional sync of applications to a shared spreadsheet."""

import logging

logger = logging.getLogger(__name__)


class GoogleSheetsSync:
    """Syncs application data to Google Sheets (optional feature)."""

    def __init__(self, config: dict):
        sheets_config = config.get("tracking", {}).get("google_sheets", {})
        self.enabled = sheets_config.get("enabled", False)
        self.spreadsheet_id = sheets_config.get("spreadsheet_id", "")
        self.sa_key_path = sheets_config.get("service_account_key", "")
        self.sheet_name = sheets_config.get("sheet_name", "Applications")
        self._client = None

    def _connect(self):
        """Initialize gspread client."""
        if not self.enabled or not self.spreadsheet_id:
            return False

        try:
            import gspread
            self._client = gspread.service_account(filename=self.sa_key_path)
            return True
        except Exception as e:
            logger.warning("Google Sheets connection failed: %s", e)
            return False

    def sync(self, applications: list[dict]) -> None:
        """Sync applications to Google Sheets."""
        if not self.enabled:
            return

        if not self._client and not self._connect():
            return

        try:
            spreadsheet = self._client.open_by_key(self.spreadsheet_id)
            sheet = spreadsheet.worksheet(self.sheet_name)

            # Get existing rows to avoid duplicates
            existing = sheet.get_all_records()
            existing_ids = {row.get("ID", "") for row in existing}

            # Add new applications
            new_rows = []
            for app in applications:
                if app.get("id", "") not in existing_ids:
                    new_rows.append([
                        app.get("date", ""),
                        app.get("company", ""),
                        app.get("title", ""),
                        app.get("platform", ""),
                        str(app.get("score", "")),
                        app.get("status", ""),
                        app.get("url", ""),
                        app.get("id", ""),
                    ])

            if new_rows:
                sheet.append_rows(new_rows)
                logger.info("Synced %d applications to Google Sheets", len(new_rows))

        except Exception as e:
            logger.warning("Google Sheets sync failed: %s", e)
