"""Synthetic SQLite measurements. No production reads, secrets, or transport."""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import domain_monitoring
from app.domain_monitoring import domain_freshness_event
from app.store import StateStore


def timed(function, repeat=3):
    walls, cpus = [], []
    for _ in range(repeat):
        wall, cpu = time.perf_counter(), time.process_time()
        function()
        walls.append(time.perf_counter() - wall)
        cpus.append(time.process_time() - cpu)
    return {"wall_seconds": round(statistics.median(walls), 6),
            "cpu_seconds": round(statistics.median(cpus), 6), "repeats": repeat}


def benchmark(size, include_guards=True):
    with tempfile.TemporaryDirectory(prefix=f"dmarc-phase8-{size}-") as directory:
        store = StateStore(Path(directory) / "synthetic.db")
        now = datetime(2026, 9, 9, 12, tzinfo=UTC)
        ended = (now - timedelta(days=10)).isoformat()
        reports = [{"domain": f"d-{i:05d}.example", "last_report": ended} for i in range(size)]
        result = {"size": size}
        result["initial_report_persistence"] = timed(lambda: store.remember_domain_reports(reports), repeat=1)
        result["unchanged_report_persistence"] = timed(lambda: store.remember_domain_reports(reports))
        with store._connect() as connection:
            connection.executemany("""
                INSERT INTO host_overrides
                    (source_ip,service_name,trust_status,notes,updated_at,classification_mode)
                VALUES (?, NULL, 'automatic', NULL, ?, 'automatic')
            """, [(f"198.18.{i // 256}.{i % 256}", now.isoformat()) for i in range(size)])
        result["host_override_read"] = timed(store.host_overrides)
        events = [{
            "id": f"synthetic-event-{i}", "kind": "host-fail", "priority": "critical",
            "title": "Synthetic failure", "domain": reports[i]["domain"],
            "source_ip": f"198.18.{i // 256}.{i % 256}", "report_time": ended,
            "messages": 10, "total_messages": 100, "dmarc_pass": 90, "dmarc_fail": 10,
            "service": "Synthetic provider", "service_confidence": 0.8,
            "service_evidence": ["Synthetic network identity", "Synthetic signing identity"],
            "header_froms": [reports[i]["domain"]], "envelope_froms": [reports[i]["domain"]],
            "status": "open", "classification_mode": "automatic",
        } for i in range(size)]
        result["initial_event_persistence"] = timed(lambda: store.save_alert_events(events, bootstrap=True), repeat=1)
        result["unchanged_event_persistence"] = timed(lambda: store.save_alert_events(events))
        result["delivery_summaries_empty"] = timed(lambda: store.alert_delivery_summaries([event["id"] for event in events]))
        result["registry_full_read"] = timed(store.list_domain_monitoring)
        freshness = [domain_freshness_event(row, now) for row in store.list_domain_monitoring()]
        assert len(freshness) == size and all(freshness)
        if include_guards:
            def guards():
                assert sum(store.domain_freshness_allows(event, 3, now=now) for event in freshness) == size
            result["freshness_guard_all_domains"] = timed(guards, repeat=3 if size <= 100 else 1)
        if size == 100:
            counters = {"canonicalizations": 0, "history_reads": 0, "registry_reads": 0,
                        "connections": 0, "writes": 0}
            original_canonical, original_connect = domain_monitoring.canonical_domain, store._connect
            def canonical(value):
                counters["canonicalizations"] += 1
                return original_canonical(value)
            def trace(sql):
                lowered = sql.lower()
                if "select" in lowered and "from domain_report_history" in lowered:
                    counters["history_reads"] += 1
                if "select" in lowered and "from domain_monitoring" in lowered:
                    counters["registry_reads"] += 1
                if lowered.startswith(("update", "insert", "delete", "begin")):
                    counters["writes"] += 1
            def connect():
                counters["connections"] += 1
                connection = original_connect()
                connection.set_trace_callback(trace)
                return connection
            with patch.object(domain_monitoring, "canonical_domain", side_effect=canonical), patch.object(store, "_connect", side_effect=connect):
                for event in freshness:
                    assert store.domain_freshness_allows(event, 3, now=now)
            result["guard_operation_counts"] = counters
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[3, 100, 1000])
    parser.add_argument("--no-guards", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    results = []
    for size in args.sizes:
        result = benchmark(size, include_guards=not args.no_guards)
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        if args.output:
            Path(args.output).write_text(json.dumps(results, indent=2) + "\n")
