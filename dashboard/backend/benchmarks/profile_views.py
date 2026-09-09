"""Bounded service profiling against read-only OpenSearch and a SQLite clone.

Run inside the candidate dashboard image with AUDIT_BASELINE_DB pointing to a
read-only, consistent database backup. Outputs metadata only, never report rows
or exception text. Defaults: one repetition of 7/30/90/365-day views, at most
1,000 read-only search calls and five minutes total. Transports are blocked.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


class BudgetReached(Exception):
    pass


def bounded_number(name, default, lower, upper):
    value = int(os.environ.get(name, str(default)))
    if not lower <= value <= upper:
        raise ValueError(name)
    return value


def json_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=lambda item: item.isoformat()).encode())


def phase(body):
    aggregations = body.get("aggs", {})
    if "hosts" in aggregations:
        return "host_inventory"
    if "domains" in aggregations:
        return "domain_inventory" if "messages" in aggregations["domains"].get("aggs", {}) else "report_freshness"
    if "events" in aggregations:
        sources = aggregations["events"].get("composite", {}).get("sources", [])
        return "daily_evidence" if sources and "day" in sources[0] else "host_history"
    return "other_aggregate"


class ProfiledSearch:
    def __init__(self, client, *, max_queries=1000, deadline=None):
        self.client, self.max_queries, self.deadline = client, max_queries, deadline
        self.queries = []

    async def search(self, index, body, *, allow_missing=False):
        if len(self.queries) >= self.max_queries or self.deadline is not None and time.monotonic() >= self.deadline:
            raise BudgetReached()
        record = {"phase": phase(body), "elapsed_ms": 0, "took_ms": 0,
                  "response_json_bytes": 0, "buckets": 0, "empty_pages": 0, "failed": False}
        self.queries.append(record)
        started = time.perf_counter()
        try:
            result = await self.client.search(index, body, allow_missing=allow_missing)
        except Exception:
            record["failed"] = True
            raise
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        record["took_ms"] = result.get("took") if isinstance(result.get("took"), (float, int)) else 0
        record["response_json_bytes"] = json_size(result)
        for aggregation in result.get("aggregations", {}).values():
            if isinstance(aggregation, dict) and isinstance(aggregation.get("buckets"), list):
                record["buckets"] += len(aggregation["buckets"])
                record["empty_pages"] += not aggregation["buckets"]
        return result

    def summarize(self, start):
        phases = defaultdict(lambda: {"queries": 0, "elapsed_ms": 0, "took_ms": 0,
                                      "response_json_bytes": 0, "buckets": 0, "empty_pages": 0, "failed": 0})
        for query in self.queries[start:]:
            item = phases[query["phase"]]
            item["queries"] += 1
            for key in ("elapsed_ms", "took_ms", "response_json_bytes", "buckets", "empty_pages", "failed"):
                item[key] += query[key]
        for item in phases.values():
            item["elapsed_ms"] = round(item["elapsed_ms"], 3)
        return dict(phases)


async def measure(client, label, operation, *, days=None, repetition=1):
    first = len(client.queries)
    stopped = False
    largest_gap = 0.0

    async def heartbeat():
        nonlocal largest_gap
        last = time.perf_counter()
        while not stopped:
            await asyncio.sleep(0.01)
            current = time.perf_counter()
            largest_gap = max(largest_gap, current - last - 0.01)
            last = current

    pulse = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    started, cpu_started = time.perf_counter(), time.process_time()
    result, failure = None, None
    try:
        remaining = max(0.01, client.deadline - time.monotonic()) if client.deadline else 120
        result = await asyncio.wait_for(operation(), timeout=min(120, remaining))
    except Exception as exc:
        failure = type(exc).__name__
    elapsed = (time.perf_counter() - started) * 1000
    cpu = (time.process_time() - cpu_started) * 1000
    stopped = True
    await pulse
    items = result.get("items", []) if isinstance(result, dict) else result if isinstance(result, list) else []
    summary = {
        "measurement": label, "days": days, "repetition": repetition,
        "status": "failed" if failure else "passed", "error_type": failure,
        "elapsed_ms": round(elapsed, 3), "process_cpu_ms": round(cpu, 3),
        "event_loop_max_lag_ms": round(max(largest_gap, 0) * 1000, 3),
        "returned_items": len(items), "total_items": result.get("total", len(items)) if isinstance(result, dict) else len(items),
        "result_json_bytes": json_size(result) if result is not None else 0,
        "search": client.summarize(first),
    }
    return summary, result


async def run():
    baseline = Path(os.environ["AUDIT_BASELINE_DB"]).resolve()
    if not baseline.is_file():
        raise ValueError("baseline_missing")
    windows = [int(value) for value in os.environ.get("AUDIT_WINDOWS", "7,30,90,365").split(",")]
    if not windows or len(windows) > 4 or any(value not in {7, 30, 90, 365} for value in windows):
        raise ValueError("windows_invalid")
    repetitions = bounded_number("AUDIT_REPETITIONS", 1, 1, 3)
    max_queries = bounded_number("AUDIT_MAX_QUERIES", 1000, 10, 5000)
    total_seconds = bounded_number("AUDIT_TOTAL_SECONDS", 300, 30, 900)
    original_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dmarc-phase8-", dir="/tmp") as folder:
        database = Path(folder) / "dashboard-copy.db"
        with sqlite3.connect(f"file:{baseline}?mode=ro", uri=True) as source:
            with sqlite3.connect(database) as target:
                source.backup(target)
        os.environ["DASHBOARD_DATABASE_PATH"] = str(database)
        from app import notifications
        from app.config import Settings
        from app.opensearch import OpenSearchClient
        from app.service import DashboardService
        from app.store import StateStore
        settings = Settings(database_path=database)
        client = ProfiledSearch(OpenSearchClient(settings.opensearch_url, settings.request_timeout_seconds),
                                max_queries=max_queries, deadline=time.monotonic() + total_seconds)
        state = StateStore(database)
        service = DashboardService(client, state, settings)
        measurements = []
        with ExitStack() as stack:
            for method in ("send_message", "send_smtp", "send_msgraph"):
                stack.enter_context(patch.object(notifications, method, side_effect=RuntimeError("transport_disabled")))
            stack.enter_context(patch("smtplib.SMTP", side_effect=RuntimeError("transport_disabled")))
            stack.enter_context(patch("smtplib.SMTP_SSL", side_effect=RuntimeError("transport_disabled")))
            for repetition in range(1, repetitions + 1):
                operations = [("domains", None, lambda: service.domains())]
                for days in windows:
                    operations.extend([
                        ("hosts_page", days, lambda days=days: service.hosts_page("*", days, limit=100)),
                        ("alerts", days, lambda days=days: service.alerts("*", days)),
                    ])
                for label, days, operation in operations:
                    summary, _ = await measure(client, label, operation, days=days, repetition=repetition)
                    measurements.append(summary)
                    print(json.dumps(summary, sort_keys=True), flush=True)
                    if summary["status"] != "passed":
                        break
                if measurements[-1]["status"] != "passed":
                    break
        if hashlib.sha256(baseline.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError("baseline_changed")
        return {"status": "passed" if all(item["status"] == "passed" for item in measurements) else "incomplete",
                "measurements": len(measurements), "search_queries": len(client.queries), "real_sends": 0,
                "baseline_unchanged": True,
                "notes": "JSON byte counts are reserialized sizes, not compressed wire bytes; loop lag includes local decoding and instrumentation."}


if __name__ == "__main__":
    try:
        outcome = asyncio.run(run())
        print(json.dumps(outcome, sort_keys=True), flush=True)
        if outcome["status"] != "passed":
            raise SystemExit(1)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1)
