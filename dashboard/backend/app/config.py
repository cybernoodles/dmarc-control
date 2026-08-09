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
    connection_key_path: Path = Path(
        os.getenv(
            "DASHBOARD_CONNECTION_KEY_PATH",
            "/app/data/connection.key",
        )
    )
    parser_control_token_file: Path = Path(
        os.getenv(
            "PARSER_CONTROL_TOKEN_FILE",
            "/app/parser-control/control.token",
        )
    )
    session_secure_cookie: bool = os.getenv(
        "DASHBOARD_SESSION_SECURE_COOKIE",
        "false",
    ).lower() in {"1", "true", "yes"}
    request_timeout_seconds: float = float(os.getenv("OPENSEARCH_TIMEOUT_SECONDS", "20"))
    new_host_window_days: int = int(os.getenv("NEW_HOST_WINDOW_DAYS", "7"))
    stale_report_days: int = int(os.getenv("STALE_REPORT_DAYS", "3"))
    notification_poll_seconds: int = max(
        30,
        int(os.getenv("NOTIFICATION_POLL_SECONDS", "300")),
    )
    backup_output_path: Path = Path(
        os.getenv("DASHBOARD_BACKUP_PATH", "/app/backups/control")
    )
    backup_repository_name: str = os.getenv(
        "OPENSEARCH_SNAPSHOT_REPOSITORY",
        "dmarc-control",
    )
    backup_repository_path: str = os.getenv(
        "OPENSEARCH_SNAPSHOT_PATH",
        "/mnt/snapshots",
    )
    backup_index_pattern: str = os.getenv(
        "OPENSEARCH_SNAPSHOT_INDICES",
        "dmarc_*",
    )
    backup_target_label: str = os.getenv(
        "DMARC_BACKUP_TARGET_LABEL",
        "./backups",
    )
    backup_timeout_seconds: float = float(
        os.getenv("BACKUP_TIMEOUT_SECONDS", "1800")
    )
    backup_poll_seconds: int = max(
        60,
        int(os.getenv("BACKUP_POLL_SECONDS", "300")),
    )


settings = Settings()
