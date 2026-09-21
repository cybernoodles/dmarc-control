from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app import main
from app.version import LOCAL_VERSION, dashboard_version


class DashboardVersionTests(unittest.TestCase):
    def test_release_version_comes_from_build_metadata(self) -> None:
        with patch.dict(
            os.environ,
            {"DMARC_CONTROL_VERSION": "2.3.0"},
            clear=True,
        ):
            self.assertEqual(dashboard_version(), "2.3.0")

    def test_local_source_build_uses_dev_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(dashboard_version(), LOCAL_VERSION)

        with patch.dict(
            os.environ,
            {"DMARC_CONTROL_VERSION": "   "},
            clear=True,
        ):
            self.assertEqual(dashboard_version(), LOCAL_VERSION)

    def test_fastapi_metadata_uses_the_health_version_source(self) -> None:
        self.assertEqual(main.app.version, main.VERSION)
