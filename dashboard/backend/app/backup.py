from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


BACKUP_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}$")


class BackupError(RuntimeError):
    pass


def create_backup_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")
    return f"{timestamp}-{os.urandom(4).hex()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_backup(source_path: Path, destination_path: Path) -> str:
    if not source_path.is_file():
        raise BackupError("Dashboard database is not available")
    source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True, timeout=30)
    destination = sqlite3.connect(destination_path, timeout=30)
    try:
        source.backup(destination, pages=256, sleep=0.05)
        result = destination.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite online backup failed: {exc}") from exc
    finally:
        destination.close()
        source.close()
    integrity = str(result[0]) if result else "no result"
    if integrity != "ok":
        raise BackupError(f"SQLite integrity check failed: {integrity}")
    destination_path.chmod(0o600)
    return integrity


def _copy_optional(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    shutil.copyfile(source, destination)
    destination.chmod(0o600)
    return True


class OnlineBackupManager:
    def __init__(
        self,
        *,
        opensearch_url: str,
        database_path: Path,
        connection_key_path: Path,
        parser_control_token_path: Path,
        output_path: Path,
        repository_name: str,
        repository_path: str,
        index_pattern: str,
        timeout_seconds: float,
        application_version: str,
    ) -> None:
        self._opensearch_url = opensearch_url.rstrip("/")
        self._database_path = database_path
        self._connection_key_path = connection_key_path
        self._parser_control_token_path = parser_control_token_path
        self._output_path = output_path
        self._repository_name = repository_name
        self._repository_path = repository_path
        self._index_pattern = index_pattern
        self._timeout = timeout_seconds
        self._application_version = application_version

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_missing: bool = False,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{self._opensearch_url}{path}",
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise BackupError(f"OpenSearch backup request failed: {exc}") from exc
        if allow_missing and response.status_code == 404:
            return {}
        if response.is_error:
            raise BackupError(
                "OpenSearch backup request failed "
                f"({response.status_code}): {response.text[:500]}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise BackupError("OpenSearch returned an invalid response") from exc

    async def create(self, backup_id: str) -> dict[str, Any]:
        if not BACKUP_ID_PATTERN.fullmatch(backup_id):
            raise BackupError("Invalid backup identifier")
        repository = quote(self._repository_name, safe="")
        snapshot_name = f"dmarc-control-{backup_id}"
        snapshot = quote(snapshot_name, safe="")
        await self._request(
            "PUT",
            f"/_snapshot/{repository}",
            json_body={
                "type": "fs",
                "settings": {
                    "location": self._repository_path,
                    "compress": True,
                },
            },
        )
        cluster_info = await self._request("GET", "/")
        snapshot_created = False
        try:
            result = await self._request(
                "PUT",
                f"/_snapshot/{repository}/{snapshot}?wait_for_completion=true",
                json_body={
                    "indices": self._index_pattern,
                    "ignore_unavailable": True,
                    "include_global_state": False,
                    "partial": False,
                    "metadata": {
                        "backup_id": backup_id,
                        "application": "DMARC Control",
                        "application_version": self._application_version,
                    },
                },
            )
            snapshot_created = True
            snapshot_result = result.get("snapshot", {})
            if snapshot_result.get("state") != "SUCCESS":
                raise BackupError(
                    "OpenSearch snapshot did not complete successfully: "
                    f"{snapshot_result.get('state', 'unknown')}"
                )
            manifest_path = await asyncio.to_thread(
                self._create_control_backup,
                backup_id,
                snapshot_name,
                snapshot_result,
                cluster_info,
            )
        except BaseException:
            if snapshot_created:
                try:
                    await asyncio.shield(
                        self._request(
                            "DELETE",
                            f"/_snapshot/{repository}/{snapshot}",
                            allow_missing=True,
                        )
                    )
                except Exception:
                    pass
            raise
        return {
            "backup_id": backup_id,
            "snapshot_name": snapshot_name,
            "manifest_path": str(manifest_path),
            "indices": snapshot_result.get("indices", []),
        }

    def _create_control_backup(
        self,
        backup_id: str,
        snapshot_name: str,
        snapshot_result: dict[str, Any],
        cluster_info: dict[str, Any],
    ) -> Path:
        try:
            self._output_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise BackupError(
                "Backup target is not writable. Check the Docker backup mount."
            ) from exc
        temporary = self._output_path / f".{backup_id}.tmp"
        destination = self._output_path / backup_id
        if destination.exists() or temporary.exists():
            raise BackupError("Backup target already exists")
        temporary.mkdir(mode=0o700)
        try:
            database_backup = temporary / "dashboard.db"
            integrity = _sqlite_backup(self._database_path, database_backup)
            key_present = _copy_optional(
                self._connection_key_path,
                temporary / "connection.key",
            )
            token_present = _copy_optional(
                self._parser_control_token_path,
                temporary / "control.token",
            )
            files = {
                path.name: {
                    "sha256": _sha256(path),
                    "size": path.stat().st_size,
                }
                for path in sorted(temporary.iterdir())
                if path.is_file()
            }
            manifest = {
                "schema": "dmarc-control.backup.v1",
                "backup_id": backup_id,
                "created_at": datetime.now(UTC).isoformat(),
                "application_version": self._application_version,
                "opensearch": {
                    "cluster_name": cluster_info.get("cluster_name"),
                    "version": cluster_info.get("version", {}).get("number"),
                    "repository": self._repository_name,
                    "snapshot": snapshot_name,
                    "state": snapshot_result.get("state"),
                    "indices": snapshot_result.get("indices", []),
                    "shards": snapshot_result.get("shards", {}),
                    "start_time": snapshot_result.get("start_time"),
                    "end_time": snapshot_result.get("end_time"),
                },
                "control": {
                    "sqlite_integrity_check": integrity,
                    "connection_key_present": key_present,
                    "parser_control_token_present": token_present,
                    "files": files,
                },
            }
            manifest_path = temporary / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            temporary.rename(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination / "manifest.json"

    async def delete(self, *, backup_id: str, snapshot_name: str) -> None:
        if not BACKUP_ID_PATTERN.fullmatch(backup_id):
            raise BackupError("Invalid backup identifier")
        repository = quote(self._repository_name, safe="")
        snapshot = quote(snapshot_name, safe="")
        await self._request(
            "DELETE",
            f"/_snapshot/{repository}/{snapshot}",
            allow_missing=True,
        )
        destination = (self._output_path / backup_id).resolve()
        output_root = self._output_path.resolve()
        if destination.parent != output_root:
            raise BackupError("Backup path is outside the configured target")
        if destination.exists():
            await asyncio.to_thread(shutil.rmtree, destination)
