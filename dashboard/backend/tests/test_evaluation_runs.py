from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.store import StateStore


SCOPE = {"domain": "*", "days": 30, "cases": ["host-fail", "stale-reports"]}


class EvaluationRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.db"
        self.store = StateStore(self.path)
        self.now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        patched = patch("app.evaluation_runs.datetime", wraps=datetime)
        self.clock = patched.start()
        self.addCleanup(patched.stop)
        self.clock.now.side_effect = lambda *_: self.now

    def test_empty_database_has_no_invented_evaluation(self):
        self.assertEqual(self.store.evaluation_status(), {"latest": None, "last_success": None})

    def test_run_scope_unknown_counts_and_result_survive_restart(self):
        run_id = self.store.start_evaluation(SCOPE)
        running = StateStore(self.path).evaluation_status()["latest"]
        self.assertEqual(running["id"], run_id)
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["scope"], SCOPE)
        self.assertIsNone(running["finished_at"])
        self.assertIsNone(running["duration_ms"])
        self.assertEqual(running["counts"], {"events": None, "domains": None, "hosts": None})
        self.now += timedelta(seconds=2)
        self.assertTrue(self.store.finish_evaluation(run_id, "success", 2000, {"events": 31, "domains": 3}))
        status = StateStore(self.path).evaluation_status()
        self.assertEqual(status["latest"], status["last_success"])
        self.assertEqual(status["latest"]["counts"], {"events": 31, "domains": 3, "hosts": None})
        self.assertEqual(status["latest"]["duration_ms"], 2000)
        self.assertEqual(status["latest"]["started_at"], running["started_at"])

    def test_failure_preserves_last_success_and_distinguishes_new_start(self):
        first = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(first, "success", 20, {"events": 0, "domains": 0, "hosts": 0})
        self.now += timedelta(minutes=5)
        second = self.store.start_evaluation(SCOPE)
        status = self.store.evaluation_status()
        self.assertEqual(status["latest"]["status"], "running")
        self.assertEqual(status["last_success"]["id"], first)
        self.store.finish_evaluation(second, "failure", 300, error="OpenSearch ist nicht erreichbar.")
        status = self.store.evaluation_status()
        self.assertEqual(status["latest"]["id"], second)
        self.assertEqual(status["latest"]["status"], "failure")
        self.assertEqual(status["last_success"]["id"], first)
        self.assertNotEqual(status["latest"]["started_at"], status["last_success"]["started_at"])

    def test_late_finish_cannot_replace_newer_run_or_newer_success(self):
        older = self.store.start_evaluation(SCOPE)
        newer = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(newer, "success", 20, {"events": 7})
        self.now += timedelta(seconds=10)
        self.store.finish_evaluation(older, "success", 10000, {"events": 3})
        status = self.store.evaluation_status()
        self.assertEqual(status["latest"]["id"], newer)
        self.assertEqual(status["last_success"]["id"], newer)
        self.assertEqual(status["last_success"]["counts"]["events"], 7)

    def test_success_is_terminal_and_later_mail_failure_cannot_reclassify_it(self):
        run_id = self.store.start_evaluation(SCOPE)
        self.assertTrue(self.store.finish_evaluation(run_id, "success", 15))
        self.assertFalse(self.store.finish_evaluation(run_id, "failure", 1000, error="SMTP nicht erreichbar."))
        self.assertEqual(self.store.evaluation_status()["latest"]["status"], "success")
        self.assertIsNone(self.store.evaluation_status()["latest"]["error"])

    def test_restart_marks_running_runs_interrupted_without_erasing_success(self):
        success = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(success, "success", 10)
        first = self.store.start_evaluation(SCOPE)
        second = self.store.start_evaluation(SCOPE)
        self.now += timedelta(seconds=3)
        restarted = StateStore(self.path)
        self.assertEqual(restarted.interrupt_running_evaluations(), 2)
        self.assertEqual(restarted.interrupt_running_evaluations(), 0)
        status = restarted.evaluation_status()
        self.assertEqual(status["latest"]["id"], second)
        self.assertEqual(status["latest"]["status"], "interrupted")
        self.assertEqual(status["latest"]["duration_ms"], 3000)
        self.assertIn("Neustart", status["latest"]["error"])
        self.assertEqual(status["last_success"]["id"], success)
        self.assertFalse(restarted.finish_evaluation(first, "success", 4000))
        newest = restarted.start_evaluation(SCOPE)
        self.assertGreater(newest, second)
        self.assertEqual(restarted.evaluation_status()["latest"]["status"], "running")

    def test_parallel_store_instances_get_distinct_monotonic_run_ids(self):
        other = StateStore(self.path)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(store.start_evaluation, SCOPE) for store in (self.store, other)]
            ids = [future.result() for future in futures]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.store.evaluation_status()["latest"]["id"], max(ids))

    def test_history_is_bounded_while_old_success_and_running_run_are_retained(self):
        success = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(success, "success", 1)
        running = self.store.start_evaluation(SCOPE)
        for _ in range(30):
            run_id = self.store.start_evaluation(SCOPE)
            self.store.finish_evaluation(run_id, "failure", 1, error="Abfrage fehlgeschlagen.")
        self.assertEqual(self.store.evaluation_status()["last_success"]["id"], success)
        with self.store._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0]
        self.assertEqual(count, 22)
        self.assertTrue(self.store.finish_evaluation(running, "interrupted", 10))
        with self.store._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0]
        self.assertEqual(count, 21)

    def test_scope_and_counts_store_only_public_fields(self):
        run_id = self.store.start_evaluation({**SCOPE, "smtp_password": "do-not-store", "secret": {"token": "hidden"}})
        self.store.finish_evaluation(run_id, "success", 12, {"events": 4, "credentials": "do-not-store"})
        self.assertNotIn("do-not-store", json.dumps(self.store.evaluation_status()))
        self.assertNotIn("credentials", json.dumps(self.store.evaluation_status()))

    def test_invalid_input_does_not_mutate_existing_status(self):
        with self.assertRaises(ValueError):
            self.store.start_evaluation({**SCOPE, "days": 0})
        self.assertIsNone(self.store.evaluation_status()["latest"])
        run_id = self.store.start_evaluation(SCOPE)
        for arguments in (
            {"status": "sending", "duration_ms": 1},
            {"status": "success", "duration_ms": -1},
            {"status": "failure", "duration_ms": 1, "error": RuntimeError("raw secret")},
            {"status": "success", "duration_ms": 1, "counts": {"events": -1}},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.store.finish_evaluation(run_id, **arguments)
        self.assertEqual(self.store.evaluation_status()["latest"]["status"], "running")
        self.assertFalse(self.store.finish_evaluation(9999, "success", 1))

    def test_public_error_is_bounded_and_success_clears_error(self):
        run_id = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(run_id, "failure", 1, error="OpenSearch\r\n" + "unavailable " * 100)
        message = self.store.evaluation_status()["latest"]["error"]
        self.assertLessEqual(len(message), 500)
        self.assertNotIn("\n", message)
        next_id = self.store.start_evaluation(SCOPE)
        self.store.finish_evaluation(next_id, "success", 1, error="irrelevant stale error")
        self.assertIsNone(self.store.evaluation_status()["latest"]["error"])


if __name__ == "__main__":
    unittest.main()
