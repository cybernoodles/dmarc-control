from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    opensearch_url: str = os.getenv("OPENSEARCH_URL", "http://opensearch:9200").rstrip("/")
    aggregate_index: str = os.getenv("DMARC_AGGREGATE_INDEX", "dmarc_aggregate-*")
    forensic_index: str = os.getenv("DMARC_FORENSIC_INDEX", "dmarc_failure-*")
    database_path: Path = Path(os.getenv("DASHBOARD_DATABASE_PATH", "/app/data/dashboard.db"))
    settings_token_file: Path = Path(
        os.getenv("DASHBOARD_SETTINGS_TOKEN_FILE", "/app/data/settings.token")
    )
    settings_token: str = os.getenv("DASHBOARD_SETTINGS_TOKEN", "")
    request_timeout_seconds: float = float(os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "20"))
    new_host_window_days: int = int(os.getenv("NEW_HOST_WINDOW_DAYS", "7"))
    stale_report_days: int = int(os.getenv("STALE_REPORT_DAYS", "3"))


settings = Settings()
