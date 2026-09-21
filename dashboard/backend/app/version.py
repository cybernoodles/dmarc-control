"""Build-time version metadata for the dashboard API."""

from __future__ import annotations

import os


LOCAL_VERSION = "dev"


def dashboard_version() -> str:
    """Return the release version embedded in an image, or the local fallback."""
    return os.getenv("DMARC_CONTROL_VERSION", "").strip() or LOCAL_VERSION


VERSION = dashboard_version()
