from __future__ import annotations

import configparser
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONTROL_API = os.getenv(
    "PARSER_CONTROL_API",
    "http://dashboard:8000/api/internal/parser",
).rstrip("/")
CONTROL_TOKEN_FILE = Path(
    os.getenv("PARSER_CONTROL_TOKEN_FILE", "/run/parser-control/control.token")
)
LEGACY_CONFIG = Path(
    os.getenv("PARSER_LEGACY_CONFIG", "/etc/parsedmarc/legacy.ini")
)
BASE_CONFIG = Path(
    os.getenv("PARSER_BASE_CONFIG", "/etc/parsedmarc/base.ini")
)
RUNTIME_CONFIG = Path(
    os.getenv("PARSER_RUNTIME_CONFIG", "/tmp/parsedmarc-managed.ini")
)
PID_FILE = Path("/tmp/parsedmarc.pid")
POLL_SECONDS = max(2, int(os.getenv("PARSER_CONTROL_POLL_SECONDS", "5")))
PARSEDMARC_COMMAND = os.getenv("PARSEDMARC_COMMAND", "parsedmarc")

stop_requested = False


def _boolean_environment(name: str, default: bool) -> str:
    value = os.getenv(name)
    if value is None:
        return "True" if default else "False"
    return "True" if value.lower() in {"1", "true", "yes", "on"} else "False"


def _token() -> str:
    return CONTROL_TOKEN_FILE.read_text(encoding="utf-8").strip()


def _request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = (
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        f"{CONTROL_API}/{path.lstrip('/')}",
        method=method,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Parser-Control-Token": _token(),
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_configuration() -> dict[str, Any]:
    return _request("config")


def post_status(
    *,
    mode: str,
    state: str,
    revision: int | None,
    version: str,
    message: str | None = None,
    pid: int | None = None,
) -> None:
    try:
        _request(
            "status",
            method="POST",
            payload={
                "mode": mode,
                "state": state,
                "revision": revision,
                "version": version,
                "message": message,
                "pid": pid,
            },
        )
    except (OSError, HTTPError, URLError, ValueError):
        pass


def render_managed_configuration(connection: dict[str, Any]) -> Path:
    configuration = configparser.RawConfigParser()
    configuration.read(BASE_CONFIG, encoding="utf-8")
    for section in ("msgraph", "imap", "mailbox"):
        configuration.remove_section(section)

    if not configuration.has_section("general"):
        configuration.add_section("general")
    configuration.set(
        "general",
        "save_aggregate",
        _boolean_environment("PARSER_SAVE_AGGREGATE", True),
    )
    configuration.set(
        "general",
        "save_failure",
        _boolean_environment("PARSER_SAVE_FAILURE", False),
    )
    configuration.set(
        "general",
        "save_smtp_tls",
        _boolean_environment("PARSER_SAVE_SMTP_TLS", False),
    )

    if not configuration.has_section("opensearch"):
        configuration.add_section("opensearch")
    configuration.set(
        "opensearch",
        "hosts",
        os.getenv("PARSER_OPENSEARCH_HOSTS", "opensearch:9200"),
    )
    configuration.set(
        "opensearch",
        "ssl",
        _boolean_environment("PARSER_OPENSEARCH_SSL", False),
    )

    provider = connection["provider"]
    if provider == "msgraph":
        configuration.add_section("msgraph")
        for key in (
            "auth_method",
            "tenant_id",
            "client_id",
            "client_secret",
            "mailbox",
        ):
            configuration.set("msgraph", key, str(connection[key]))
    elif provider == "imap":
        configuration.add_section("imap")
        for key in (
            "host",
            "port",
            "ssl",
            "skip_certificate_verification",
            "user",
            "password",
        ):
            configuration.set("imap", key, str(connection[key]))
    else:
        raise ValueError("Unsupported mailbox provider")

    configuration.add_section("mailbox")
    configuration.set("mailbox", "watch", "True")
    configuration.set("mailbox", "test", "False")
    configuration.set("mailbox", "delete", "False")
    configuration.set(
        "mailbox",
        "reports_folder",
        str(connection["reports_folder"]),
    )
    configuration.set(
        "mailbox",
        "archive_folder",
        str(connection["archive_folder"]),
    )

    temporary_path = RUNTIME_CONFIG.with_suffix(".new")
    with temporary_path.open("w", encoding="utf-8") as runtime_file:
        configuration.write(runtime_file)
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(RUNTIME_CONFIG)
    return RUNTIME_CONFIG


def _version() -> str:
    try:
        return importlib.metadata.version("parsedmarc")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def start_child(config_path: Path) -> subprocess.Popen:
    child = subprocess.Popen(
        [PARSEDMARC_COMMAND, "-c", str(config_path)],
        stdin=subprocess.DEVNULL,
    )
    PID_FILE.write_text(f"{child.pid}\n", encoding="utf-8")
    return child


def stop_child(child: subprocess.Popen | None) -> None:
    if child is None or child.poll() is not None:
        PID_FILE.unlink(missing_ok=True)
        return
    child.terminate()
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=10)
    PID_FILE.unlink(missing_ok=True)


def _signal_handler(_signum, _frame) -> None:
    global stop_requested
    stop_requested = True


def run() -> int:
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    version = _version()
    child: subprocess.Popen | None = None
    current_signature: tuple[str, int | None] | None = None
    current_path: Path | None = None
    last_configuration: dict[str, Any] | None = None

    while not stop_requested:
        try:
            desired = fetch_configuration()
            last_configuration = desired
        except (OSError, HTTPError, URLError, ValueError, json.JSONDecodeError):
            desired = last_configuration
            if desired is None:
                desired = {
                    "mode": "legacy",
                    "revision": None,
                    "connection": None,
                }

        mode = str(desired["mode"])
        revision = desired.get("revision")
        signature = (mode, revision)

        if signature != current_signature:
            if child is not None:
                post_status(
                    mode=current_signature[0] if current_signature else mode,
                    state="restarting",
                    revision=(
                        current_signature[1] if current_signature else revision
                    ),
                    version=version,
                    pid=child.pid,
                )
                stop_child(child)
                child = None

            try:
                if mode == "managed":
                    connection = desired.get("connection")
                    if not isinstance(connection, dict):
                        raise ValueError("Managed connection is missing")
                    current_path = render_managed_configuration(connection)
                else:
                    if not LEGACY_CONFIG.is_file():
                        raise ValueError(
                            "Legacy configuration is not available"
                        )
                    current_path = LEGACY_CONFIG
                post_status(
                    mode=mode,
                    state="starting",
                    revision=revision,
                    version=version,
                )
                child = start_child(current_path)
                current_signature = signature
                post_status(
                    mode=mode,
                    state="running",
                    revision=revision,
                    version=version,
                    pid=child.pid,
                )
            except (OSError, ValueError) as exc:
                post_status(
                    mode=mode,
                    state="error",
                    revision=revision,
                    version=version,
                    message=str(exc)[:500],
                )
                time.sleep(POLL_SECONDS)
                continue

        if child is not None and child.poll() is not None:
            exit_code = child.returncode
            PID_FILE.unlink(missing_ok=True)
            post_status(
                mode=mode,
                state="error",
                revision=revision,
                version=version,
                message=f"parsedmarc exited with code {exit_code}",
            )
            child = None
            current_signature = None

        time.sleep(POLL_SECONDS)

    stop_child(child)
    final_mode = current_signature[0] if current_signature else "legacy"
    final_revision = current_signature[1] if current_signature else None
    post_status(
        mode=final_mode,
        state="stopped",
        revision=final_revision,
        version=version,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
