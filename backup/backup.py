#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCHEMA = "dmarc-control.backup.v1"
REPOSITORY = "dmarc-control"
ARCHIVE_MAGIC = b"DMARC-CONTROL-BACKUP\x01"
ARCHIVE_AAD = b"dmarc-control-control-state-v1"
VALID_MODES = {"integrated", "external", "none", "unconfigured"}
REQUIRED_CONTROL_FILES = {
    "dashboard/dashboard.db",
    "parser-control/control.token",
}


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    backup_root: Path
    dashboard_data: Path
    parser_control: Path
    stack_config: Path
    dashboard_url: str
    opensearch_url: str
    schedule: str
    retention_days: int
    poll_seconds: int
    parser_pause_timeout: int
    release_version: str
    recovery_key_file: Path

    @classmethod
    def from_environment(cls) -> "Config":
        return cls(
            backup_root=Path(os.getenv("BACKUP_ROOT", "/backups")),
            dashboard_data=Path(
                os.getenv("DASHBOARD_DATA_ROOT", "/dashboard-data")
            ),
            parser_control=Path(
                os.getenv("PARSER_CONTROL_ROOT", "/run/parser-control")
            ),
            stack_config=Path(
                os.getenv("STACK_CONFIG_ROOT", "/stack-config")
            ),
            dashboard_url=os.getenv(
                "DASHBOARD_URL", "http://dashboard:8000"
            ).rstrip("/"),
            opensearch_url=os.getenv(
                "OPENSEARCH_URL", "http://opensearch:9200"
            ).rstrip("/"),
            schedule=os.getenv("BACKUP_SCHEDULE", "0 2 * * *").strip(),
            retention_days=max(
                1, int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
            ),
            poll_seconds=max(5, int(os.getenv("BACKUP_POLL_SECONDS", "30"))),
            parser_pause_timeout=max(
                10, int(os.getenv("BACKUP_PARSER_PAUSE_TIMEOUT", "60"))
            ),
            release_version=os.getenv(
                "DMARC_CONTROL_RELEASE", "unknown"
            ).strip()
            or "unknown",
            recovery_key_file=Path(
                os.getenv(
                    "BACKUP_RECOVERY_KEY_FILE",
                    os.path.join(
                        os.getenv("DASHBOARD_DATA_ROOT", "/dashboard-data"),
                        "backup.key",
                    ),
                )
            ),
        )

    @property
    def manifests(self) -> Path:
        return self.backup_root / "manifests"

    @property
    def control_archives(self) -> Path:
        return self.backup_root / "control"

    @property
    def snapshot_repository(self) -> Path:
        return self.backup_root / "opensearch" / "repository"

    @property
    def operation_lock(self) -> Path:
        return self.backup_root / ".operation.lock"

    @property
    def local_status(self) -> Path:
        return self.backup_root / "status.json"

    @property
    def maintenance_lock(self) -> Path:
        return self.parser_control / "backup.lock"

    @property
    def control_token(self) -> Path:
        return self.parser_control / "control.token"

    @property
    def encryption_key(self) -> Path:
        return self.recovery_key_file


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def backup_id(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("dmarc-%Y%m%dT%H%M%SZ").lower()


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_key(path: Path) -> bytes:
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise BackupError(
            f"Recovery key cannot be read at {path}: {exc}"
        ) from exc
    if len(key) != 32:
        raise BackupError("Recovery key must contain exactly 32 bytes")
    return key


def key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def encrypt_archive(plaintext: Path, destination: Path, key: bytes) -> None:
    nonce = os.urandom(12)
    encrypted = AESGCM(key).encrypt(
        nonce,
        plaintext.read_bytes(),
        ARCHIVE_AAD,
    )
    atomic_write(destination, ARCHIVE_MAGIC + nonce + encrypted)


def decrypt_archive(source: Path, destination: Path, key: bytes) -> None:
    payload = source.read_bytes()
    if not payload.startswith(ARCHIVE_MAGIC):
        raise BackupError("Control archive has an unknown format")
    offset = len(ARCHIVE_MAGIC)
    nonce = payload[offset : offset + 12]
    if len(nonce) != 12:
        raise BackupError("Control archive is truncated")
    try:
        plaintext = AESGCM(key).decrypt(
            nonce,
            payload[offset + 12 :],
            ARCHIVE_AAD,
        )
    except Exception as exc:
        raise BackupError(
            "Control archive authentication failed; recovery key or data is invalid"
        ) from exc
    atomic_write(destination, plaintext)


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 90,
) -> Any:
    body = (
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise BackupError(
            f"{method} {path} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise BackupError(f"{method} {path} is unavailable: {exc}") from exc
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise BackupError(f"{method} {path} returned invalid JSON") from exc


class BackupController:
    def __init__(self, config: Config) -> None:
        self.config = config

    def prepare_directories(self) -> None:
        for path in (
            self.config.backup_root,
            self.config.manifests,
            self.config.control_archives,
            self.config.snapshot_repository,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o770)
            os.chmod(
                path,
                0o2770 if path == self.config.snapshot_repository else 0o770,
            )

    def token(self) -> str:
        try:
            token = self.config.control_token.read_text(
                encoding="utf-8"
            ).strip()
        except OSError as exc:
            raise BackupError(f"Parser control token is unavailable: {exc}") from exc
        if not token:
            raise BackupError("Parser control token is empty")
        return token

    def dashboard_request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Any | None = None,
    ) -> Any:
        return request_json(
            self.config.dashboard_url,
            path,
            method=method,
            payload=payload,
            headers={"X-Parser-Control-Token": self.token()},
        )

    def opensearch_request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Any | None = None,
        timeout: int = 90,
    ) -> Any:
        return request_json(
            self.config.opensearch_url,
            path,
            method=method,
            payload=payload,
            timeout=timeout,
        )

    def configuration(self) -> dict[str, Any]:
        result = self.dashboard_request("/api/internal/backup/config")
        mode = result.get("mode")
        if mode not in VALID_MODES:
            raise BackupError("Dashboard returned an unsupported backup mode")
        return result

    def write_status(self, state: str, **values: Any) -> dict[str, Any]:
        previous: dict[str, Any] = {}
        try:
            previous = json.loads(
                self.config.local_status.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            pass
        status = {
            "state": state,
            "message": values.get("message"),
            "backup_id": values.get("backup_id"),
            "last_success_at": values.get(
                "last_success_at", previous.get("last_success_at")
            ),
            "next_run_at": values.get("next_run_at"),
            "schedule": self.config.schedule,
            "retention_days": self.config.retention_days,
            "updated_at": iso(),
        }
        status = {key: value for key, value in status.items() if value is not None}
        atomic_write(
            self.config.local_status,
            (json.dumps(status, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        try:
            self.dashboard_request(
                "/api/internal/backup/status",
                method="POST",
                payload={
                    key: value
                    for key, value in status.items()
                    if key != "updated_at"
                },
            )
        except BackupError:
            pass
        return status

    @contextmanager
    def operation(self, *, wait: bool = False) -> Iterator[None]:
        self.prepare_directories()
        with self.config.operation_lock.open("a+") as handle:
            flags = fcntl.LOCK_EX
            if not wait:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(handle.fileno(), flags)
            except BlockingIOError as exc:
                raise BackupError("Another backup or restore operation is active") from exc
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create_maintenance_lock(self, current_id: str) -> None:
        self.config.maintenance_lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = self.config.maintenance_lock.read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError:
            existing = ""
        if existing and existing != current_id:
            raise BackupError(
                f"Maintenance lock is already active for {existing}"
            )
        atomic_write(
            self.config.maintenance_lock,
            f"{current_id}\n".encode("utf-8"),
            mode=0o640,
        )

    def release_maintenance_lock(self, expected_id: str | None = None) -> None:
        try:
            current = self.config.maintenance_lock.read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError:
            return
        if expected_id and current != expected_id:
            raise BackupError(
                f"Maintenance lock belongs to {current}, not {expected_id}"
            )
        self.config.maintenance_lock.unlink()

    def wait_for_parser_pause(self) -> None:
        deadline = time.monotonic() + self.config.parser_pause_timeout
        while time.monotonic() < deadline:
            current = self.configuration().get("parser")
            if current and current.get("state") in {"stopped", "error"}:
                return
            time.sleep(2)
        raise BackupError(
            "Parser did not acknowledge the backup maintenance lock in time"
        )

    def register_repository(self) -> None:
        response = self.opensearch_request(
            f"/_snapshot/{REPOSITORY}?verify=true",
            method="PUT",
            payload={
                "type": "fs",
                "settings": {"location": "/mnt/snapshots/repository"},
            },
        )
        if response.get("acknowledged") is not True:
            raise BackupError("OpenSearch did not acknowledge the snapshot repository")

    def opensearch_version(self) -> str:
        result = self.opensearch_request("")
        version = result.get("version", {}).get("number")
        if not isinstance(version, str) or not version:
            raise BackupError("OpenSearch version is unavailable")
        return version

    def indices(self) -> list[dict[str, Any]]:
        result = self.opensearch_request(
            "/_cat/indices?format=json&h=index,docs.count,store.size,status,health"
        )
        indices = []
        for item in result:
            name = str(item.get("index", ""))
            if not name or name.startswith("."):
                continue
            try:
                documents = int(item.get("docs.count") or 0)
            except (TypeError, ValueError):
                documents = 0
            indices.append(
                {
                    "name": name,
                    "documents": documents,
                    "store_size": item.get("store.size"),
                    "status": item.get("status"),
                    "health": item.get("health"),
                }
            )
        return sorted(indices, key=lambda item: item["name"])

    def create_snapshot(
        self,
        snapshot_name: str,
        indices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        names = ",".join(item["name"] for item in indices)
        result = self.opensearch_request(
            f"/_snapshot/{REPOSITORY}/{snapshot_name}?wait_for_completion=true",
            method="PUT",
            payload={
                "indices": names,
                "ignore_unavailable": False,
                "include_global_state": False,
                "partial": False,
            },
            timeout=3600,
        )
        snapshot = result.get("snapshot", {})
        if snapshot.get("state") != "SUCCESS":
            raise BackupError(
                f"OpenSearch snapshot ended in state {snapshot.get('state', 'unknown')}"
            )
        shards = snapshot.get("shards", {})
        if shards.get("failed", 0) != 0:
            raise BackupError("OpenSearch snapshot contains failed shards")
        return snapshot

    def delete_snapshot(self, name: str) -> None:
        self.opensearch_request(
            f"/_snapshot/{REPOSITORY}/{quote(name, safe='-_.')}",
            method="DELETE",
        )

    def sqlite_backup(self, destination: Path) -> str:
        source = self.config.dashboard_data / "dashboard.db"
        if not source.is_file():
            raise BackupError(f"Dashboard database is missing at {source}")
        try:
            with (
                sqlite3.connect(f"file:{source}?mode=ro", uri=True) as input_db,
                sqlite3.connect(destination) as output_db,
            ):
                input_db.backup(output_db)
                result = output_db.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite online backup failed: {exc}") from exc
        integrity = str(result[0]) if result else "missing"
        if integrity != "ok":
            raise BackupError(f"SQLite integrity check failed: {integrity}")
        return integrity

    def create_control_archive(
        self,
        current_id: str,
    ) -> tuple[Path, str, dict[str, bool], str]:
        key = read_key(self.config.encryption_key)
        destination = self.config.control_archives / f"{current_id}.tar.gz.aes"
        included: dict[str, bool] = {}
        with tempfile.TemporaryDirectory(prefix="dmarc-backup-") as directory:
            temporary = Path(directory)
            staging = temporary / "control"
            (staging / "dashboard").mkdir(parents=True)
            (staging / "parser-control").mkdir(parents=True)
            (staging / "stack").mkdir(parents=True)
            integrity = self.sqlite_backup(staging / "dashboard" / "dashboard.db")
            included["dashboard/dashboard.db"] = True

            sources = {
                "dashboard/connection.key": self.config.dashboard_data
                / "connection.key",
                "parser-control/control.token": self.config.control_token,
                "stack/.env": self.config.stack_config / ".env",
                "stack/docker-compose.yml": self.config.stack_config
                / "docker-compose.yml",
                "stack/config/parsedmarc.ini": self.config.stack_config
                / "config"
                / "parsedmarc.ini",
            }
            for archive_name, source in sources.items():
                included[archive_name] = source.is_file()
                if source.is_file():
                    target = staging / archive_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    os.chmod(target, 0o600)

            if not included["parser-control/control.token"]:
                raise BackupError("Parser control token is missing from control backup")

            tar_path = temporary / f"{current_id}.tar.gz"
            with tarfile.open(tar_path, "w:gz") as archive:
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        archive.add(
                            path,
                            arcname=str(path.relative_to(staging)),
                            recursive=False,
                        )
            encrypt_archive(tar_path, destination, key)
        return destination, integrity, included, key_fingerprint(key)

    def manifest_path(self, current_id: str) -> Path:
        return self.config.manifests / f"{current_id}.json"

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        path = self.manifest_path(manifest["backup_id"])
        content = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        atomic_write(path, content)
        atomic_write(
            path.with_suffix(".json.sha256"),
            f"{hashlib.sha256(content).hexdigest()}  {path.name}\n".encode(
                "ascii"
            ),
        )
        return path

    def create_backup(self, *, force: bool = False) -> dict[str, Any]:
        current_id = backup_id()
        with self.operation():
            configuration = self.configuration()
            if configuration["mode"] != "integrated" and not force:
                raise BackupError(
                    "Integrated backups are not selected; use --force for an "
                    "explicit one-off backup"
                )
            self.write_status(
                "running",
                backup_id=current_id,
                message="Preparing consistent backup",
            )
            snapshot_created = False
            self.create_maintenance_lock(current_id)
            try:
                self.wait_for_parser_pause()
                self.register_repository()
                version = self.opensearch_version()
                source_indices = self.indices()
                if source_indices:
                    snapshot = self.create_snapshot(current_id, source_indices)
                    snapshot_created = True
                else:
                    snapshot = {
                        "state": "NOT_REQUIRED",
                        "shards": {"total": 0, "successful": 0, "failed": 0},
                    }
                archive, integrity, included, fingerprint = (
                    self.create_control_archive(current_id)
                )
                parser_status = configuration.get("parser") or {}
                manifest = {
                    "schema": SCHEMA,
                    "backup_id": current_id,
                    "created_at": iso(),
                    "release_version": self.config.release_version,
                    "parsedmarc_version": parser_status.get("version"),
                    "grafana_runtime_included": False,
                    "opensearch": {
                        "version": version,
                        "repository": REPOSITORY,
                        "snapshot": current_id if source_indices else None,
                        "state": snapshot.get("state"),
                        "indices": source_indices,
                        "shards": snapshot.get("shards", {}),
                    },
                    "control": {
                        "archive": archive.name,
                        "sha256": sha256_file(archive),
                        "encryption": "AES-256-GCM",
                        "key_fingerprint": fingerprint,
                        "sqlite_integrity_check": integrity,
                        "included": included,
                    },
                    "consistency": {
                        "parser_paused": True,
                        "notification_delivery_paused": True,
                    },
                }
                path = self.write_manifest(manifest)
            except Exception:
                if snapshot_created and not self.manifest_path(current_id).exists():
                    try:
                        self.delete_snapshot(current_id)
                    except BackupError:
                        pass
                raise
            finally:
                self.release_maintenance_lock(current_id)

            self.write_status(
                "success",
                backup_id=current_id,
                last_success_at=manifest["created_at"],
                next_run_at=iso(next_daily_run(self.config.schedule)),
                message="Backup completed and verified",
            )
            self.prune_locked()
            return {"state": "success", "backup_id": current_id, "manifest": str(path)}

    def manifests(self) -> list[dict[str, Any]]:
        values = []
        if not self.config.manifests.is_dir():
            return values
        for path in sorted(self.config.manifests.glob("dmarc-*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("schema") == SCHEMA:
                values.append(manifest)
        return values

    def select_manifest(self, requested: str | None) -> dict[str, Any]:
        manifests = self.manifests()
        if requested in {None, "latest"}:
            if not manifests:
                raise BackupError("No successful backup manifest exists")
            return manifests[-1]
        path = self.manifest_path(requested)
        if not path.is_file():
            raise BackupError(f"Backup manifest {requested} does not exist")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(f"Backup manifest {requested} is invalid") from exc
        if manifest.get("schema") != SCHEMA:
            raise BackupError("Backup manifest schema is incompatible")
        return manifest

    def verify_manifest(
        self,
        manifest: dict[str, Any],
        *,
        online: bool = True,
        verify_control: bool = True,
    ) -> dict[str, Any]:
        current_id = manifest.get("backup_id")
        if not isinstance(current_id, str) or not current_id.startswith("dmarc-"):
            raise BackupError("Backup manifest has an invalid backup ID")
        path = self.manifest_path(current_id)
        checksum_path = path.with_suffix(".json.sha256")
        try:
            expected_manifest_checksum = checksum_path.read_text(
                encoding="ascii"
            ).split()[0]
        except (OSError, IndexError) as exc:
            raise BackupError("Manifest checksum is missing") from exc
        if sha256_file(path) != expected_manifest_checksum:
            raise BackupError("Manifest checksum does not match")

        if verify_control:
            control = manifest.get("control", {})
            archive = self.config.control_archives / str(control.get("archive", ""))
            if not archive.is_file():
                raise BackupError("Encrypted control archive is missing")
            if sha256_file(archive) != control.get("sha256"):
                raise BackupError("Encrypted control archive checksum does not match")
            key = read_key(self.config.encryption_key)
            if key_fingerprint(key) != control.get("key_fingerprint"):
                raise BackupError("Recovery key fingerprint does not match the backup")
            with tempfile.TemporaryDirectory(prefix="dmarc-verify-") as directory:
                tar_path = Path(directory) / "control.tar.gz"
                decrypt_archive(archive, tar_path, key)
                with tarfile.open(tar_path, "r:gz") as tar:
                    names = set(tar.getnames())
                    if not REQUIRED_CONTROL_FILES.issubset(names):
                        missing = ", ".join(sorted(REQUIRED_CONTROL_FILES - names))
                        raise BackupError(f"Control archive is incomplete: {missing}")
                    database_member = tar.extractfile("dashboard/dashboard.db")
                    if database_member is None:
                        raise BackupError("Dashboard database cannot be extracted")
                    database_path = Path(directory) / "dashboard.db"
                    atomic_write(database_path, database_member.read())
                with sqlite3.connect(database_path) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupError("Restored SQLite integrity check failed")

        expected = {
            item["name"]
            for item in manifest.get("opensearch", {}).get("indices", [])
        }
        if online and expected:
            snapshot = self.opensearch_request(
                f"/_snapshot/{REPOSITORY}/{current_id}"
            )
            entries = snapshot.get("snapshots", [])
            if len(entries) != 1 or entries[0].get("state") != "SUCCESS":
                raise BackupError("OpenSearch snapshot is missing or incomplete")
            actual = set(entries[0].get("indices", []))
            if actual != expected:
                raise BackupError("Snapshot index inventory does not match manifest")
        return {
            "backup_id": current_id,
            "valid": True,
            "online_snapshot_check": online and bool(expected),
            "control_archive_check": verify_control,
        }

    def prune_locked(self) -> list[str]:
        manifests = self.manifests()
        if len(manifests) <= 1:
            return []
        cutoff = utc_now() - timedelta(days=self.config.retention_days)
        removed: list[str] = []
        for manifest in manifests[:-1]:
            try:
                created = datetime.fromisoformat(
                    str(manifest["created_at"]).replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                continue
            if created >= cutoff:
                continue
            current_id = manifest["backup_id"]
            if manifest.get("opensearch", {}).get("snapshot"):
                self.delete_snapshot(current_id)
            archive = self.config.control_archives / manifest["control"]["archive"]
            archive.unlink(missing_ok=True)
            path = self.manifest_path(current_id)
            path.unlink(missing_ok=True)
            path.with_suffix(".json.sha256").unlink(missing_ok=True)
            removed.append(current_id)
        return removed

    def prune(self) -> list[str]:
        with self.operation():
            self.register_repository()
            return self.prune_locked()

    def _dashboard_is_running(self) -> bool:
        try:
            request_json(self.config.dashboard_url, "/api/health", timeout=3)
        except BackupError:
            return False
        return True

    def _version_tuple(self, value: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in value.split(".")[:3])
        except ValueError as exc:
            raise BackupError(f"Unsupported OpenSearch version {value}") from exc

    def _restore_control(self, manifest: dict[str, Any]) -> None:
        key = read_key(self.config.encryption_key)
        archive = self.config.control_archives / manifest["control"]["archive"]
        safety = self.config.backup_root / "restore-safety" / backup_id()
        safety.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="dmarc-restore-") as directory:
            temporary = Path(directory)
            tar_path = temporary / "control.tar.gz"
            decrypt_archive(archive, tar_path, key)
            with tarfile.open(tar_path, "r:gz") as tar:
                names = set(tar.getnames())
                if not REQUIRED_CONTROL_FILES.issubset(names):
                    raise BackupError("Control archive is incomplete")
                for name in REQUIRED_CONTROL_FILES | {"dashboard/connection.key"}:
                    if name not in names:
                        continue
                    member = tar.getmember(name)
                    if not member.isfile() or Path(name).is_absolute() or ".." in Path(name).parts:
                        raise BackupError("Control archive contains an unsafe path")
                    source = tar.extractfile(member)
                    if source is None:
                        raise BackupError(f"Cannot extract {name}")
                    if name.startswith("dashboard/"):
                        target = self.config.dashboard_data / Path(name).name
                    else:
                        target = self.config.parser_control / Path(name).name
                    if target.exists():
                        shutil.copyfile(target, safety / target.name)
                    atomic_write(target, source.read(), mode=0o600)
        atomic_write(self.config.dashboard_data / "backup.key", key, mode=0o600)

    def extract_stack_config(
        self,
        manifest: dict[str, Any],
        destination: Path | None = None,
    ) -> list[str]:
        current_id = manifest["backup_id"]
        target_root = destination or (
            self.config.backup_root / "extracted" / current_id
        )
        target_root.mkdir(parents=True, exist_ok=True)
        key = read_key(self.config.encryption_key)
        archive = self.config.control_archives / manifest["control"]["archive"]
        extracted: list[str] = []
        with tempfile.TemporaryDirectory(prefix="dmarc-extract-") as directory:
            tar_path = Path(directory) / "control.tar.gz"
            decrypt_archive(archive, tar_path, key)
            with tarfile.open(tar_path, "r:gz") as tar:
                for member in tar.getmembers():
                    path = Path(member.name)
                    if (
                        not member.isfile()
                        or not path.parts
                        or path.parts[0] != "stack"
                        or path.is_absolute()
                        or ".." in path.parts
                    ):
                        continue
                    source = tar.extractfile(member)
                    if source is None:
                        raise BackupError(f"Cannot extract {member.name}")
                    target = target_root.joinpath(*path.parts[1:])
                    atomic_write(target, source.read(), mode=0o600)
                    extracted.append(str(target))
        if not extracted:
            raise BackupError("Backup does not contain stack configuration files")
        return sorted(extracted)

    def restore(
        self,
        requested: str | None,
        *,
        replace_existing: bool,
        history_only: bool,
    ) -> dict[str, Any]:
        manifest = self.select_manifest(requested)
        current_id = manifest["backup_id"]
        with self.operation():
            dashboard_running = self._dashboard_is_running()
            if not history_only and dashboard_running:
                raise BackupError(
                    "Dashboard is running; stop dashboard, parsedmarc and "
                    "backup before a full restore"
                )
            self.create_maintenance_lock(f"restore-{current_id}")
            if dashboard_running:
                self.wait_for_parser_pause()
            self.register_repository()
            self.verify_manifest(
                manifest,
                online=True,
                verify_control=not history_only,
            )
            source_version = manifest["opensearch"]["version"]
            target_version = self.opensearch_version()
            source_parts = self._version_tuple(source_version)
            target_parts = self._version_tuple(target_version)
            if source_parts[0] != target_parts[0] or target_parts < source_parts:
                raise BackupError(
                    f"OpenSearch {source_version} backup is incompatible "
                    f"with target {target_version}"
                )

            expected_indices = manifest["opensearch"]["indices"]
            expected_names = {item["name"] for item in expected_indices}
            existing = {item["name"] for item in self.indices()}
            conflicts = sorted(expected_names & existing)
            if conflicts and not replace_existing:
                raise BackupError(
                    "Target indices already exist: "
                    + ", ".join(conflicts)
                    + "; use --replace-existing only after reviewing the target"
                )
            if conflicts:
                safety_name = f"pre-restore-{backup_id()}"
                safety_indices = [
                    item for item in self.indices() if item["name"] in conflicts
                ]
                self.create_snapshot(safety_name, safety_indices)
                for name in conflicts:
                    self.opensearch_request(
                        f"/{quote(name, safe='-_.')}",
                        method="DELETE",
                    )

            if expected_names:
                names = ",".join(sorted(expected_names))
                result = self.opensearch_request(
                    f"/_snapshot/{REPOSITORY}/{current_id}/_restore?wait_for_completion=true",
                    method="POST",
                    payload={
                        "indices": names,
                        "include_global_state": False,
                        "include_aliases": True,
                        "partial": False,
                    },
                    timeout=3600,
                )
                restored = result.get("snapshot", {})
                if restored.get("shards", {}).get("failed", 0) != 0:
                    raise BackupError("OpenSearch restore contains failed shards")
            actual = {item["name"]: item for item in self.indices()}
            for expected in expected_indices:
                current = actual.get(expected["name"])
                if current is None or current["documents"] != expected["documents"]:
                    raise BackupError(
                        f"Document count mismatch after restore for {expected['name']}"
                    )
            if not history_only:
                self._restore_control(manifest)
            self.write_status(
                "restoring",
                backup_id=current_id,
                message="Restore completed; maintenance lock remains until explicit release",
            )
        return {
            "backup_id": current_id,
            "restored": True,
            "history_only": history_only,
            "maintenance_lock": str(self.config.maintenance_lock),
        }


def parse_daily_schedule(value: str) -> tuple[int, int]:
    parts = value.split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
        raise BackupError(
            "BACKUP_SCHEDULE must be a daily UTC cron expression such as '0 2 * * *'"
        )
    try:
        minute = int(parts[0])
        hour = int(parts[1])
    except ValueError as exc:
        raise BackupError("Backup schedule minute and hour must be numbers") from exc
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        raise BackupError("Backup schedule contains an invalid UTC time")
    return hour, minute


def next_daily_run(value: str, now: datetime | None = None) -> datetime:
    hour, minute = parse_daily_schedule(value)
    current = now or utc_now()
    candidate = current.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def latest_success(controller: BackupController) -> dict[str, Any] | None:
    manifests = controller.manifests()
    return manifests[-1] if manifests else None


def next_run_from_latest(
    schedule: str,
    latest: dict[str, Any] | None,
    now: datetime,
) -> datetime:
    if not latest:
        return now
    try:
        created_at = datetime.fromisoformat(
            str(latest["created_at"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise BackupError("Latest backup has an invalid creation time") from exc
    return next_daily_run(schedule, created_at)


def run_daemon(controller: BackupController) -> int:
    controller.prepare_directories()
    last_mode: str | None = None
    known_backup_id: str | None = None
    next_attempt: datetime | None = None
    while True:
        mode: str | None = None
        try:
            configuration = controller.configuration()
            mode = configuration["mode"]
            latest = latest_success(controller)
            if mode != "integrated":
                controller.write_status(
                    "disabled",
                    message=(
                        "External backup strategy selected"
                        if mode == "external"
                        else "No backup strategy selected"
                        if mode == "none"
                        else "Backup strategy is not configured"
                    ),
                    last_success_at=(latest or {}).get("created_at"),
                )
                next_attempt = None
            else:
                now = utc_now()
                latest_id = (latest or {}).get("backup_id")
                if last_mode is None:
                    next_attempt = next_run_from_latest(
                        controller.config.schedule,
                        latest,
                        now,
                    )
                elif last_mode != "integrated":
                    next_attempt = now
                elif latest_id != known_backup_id and latest_id is not None:
                    next_attempt = next_run_from_latest(
                        controller.config.schedule,
                        latest,
                        now,
                    )
                if next_attempt is None:
                    next_attempt = now
                if now >= next_attempt:
                    controller.create_backup()
                    latest = latest_success(controller)
                    latest_id = (latest or {}).get("backup_id")
                    next_attempt = next_run_from_latest(
                        controller.config.schedule,
                        latest,
                        now,
                    )
                controller.write_status(
                    "success" if latest else "waiting",
                    message=(
                        "Automatic backup schedule is active"
                        if latest
                        else "Waiting for historical OpenSearch data"
                    ),
                    backup_id=(latest or {}).get("backup_id"),
                    last_success_at=(latest or {}).get("created_at"),
                    next_run_at=iso(next_attempt),
                )
                known_backup_id = latest_id
            last_mode = mode
        except BackupError as exc:
            if mode == "integrated":
                next_attempt = utc_now() + timedelta(
                    seconds=max(300, controller.config.poll_seconds)
                )
            controller.write_status(
                "error",
                message=str(exc),
                next_run_at=iso(next_attempt) if next_attempt else None,
            )
            print(f"backup error: {exc}", file=sys.stderr, flush=True)
        time.sleep(controller.config.poll_seconds)


def output_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dmarc-backup",
        description="DMARC Control backup and restore utility",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("daemon", help="run the automatic backup scheduler")
    now = commands.add_parser("now", help="create a backup immediately")
    now.add_argument("--force", action="store_true")
    commands.add_parser("status", help="show scheduler and strategy status")
    commands.add_parser("list", help="list successful backups")
    verify = commands.add_parser("verify", help="verify a backup")
    verify.add_argument("backup_id", nargs="?", default="latest")
    verify.add_argument("--offline", action="store_true")
    verify.add_argument("--history-only", action="store_true")
    commands.add_parser("prune", help="apply configured retention")
    extract = commands.add_parser(
        "extract-config",
        help="decrypt stack configuration for manual review",
    )
    extract.add_argument("backup_id", nargs="?", default="latest")
    extract.add_argument("--destination", type=Path)
    export = commands.add_parser(
        "export-key", help="print the recovery key for secure offline storage"
    )
    export.add_argument("--raw", action="store_true")
    restore = commands.add_parser("restore", help="restore a verified backup")
    restore.add_argument("backup_id", nargs="?", default="latest")
    restore.add_argument("--replace-existing", action="store_true")
    restore.add_argument("--history-only", action="store_true")
    commands.add_parser(
        "release", help="release the maintenance lock after restore validation"
    )
    commands.add_parser("health", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    controller = BackupController(Config.from_environment())
    try:
        if args.command == "daemon":
            return run_daemon(controller)
        if args.command == "now":
            output_json(controller.create_backup(force=args.force))
        elif args.command == "status":
            status: dict[str, Any] = {}
            try:
                status = json.loads(
                    controller.config.local_status.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                status = {"state": "starting"}
            try:
                status["strategy"] = controller.configuration()["mode"]
            except BackupError as exc:
                status["dashboard_error"] = str(exc)
            output_json(status)
        elif args.command == "list":
            output_json(
                [
                    {
                        "backup_id": item["backup_id"],
                        "created_at": item["created_at"],
                        "opensearch_version": item["opensearch"]["version"],
                        "indices": len(item["opensearch"]["indices"]),
                    }
                    for item in controller.manifests()
                ]
            )
        elif args.command == "verify":
            manifest = controller.select_manifest(args.backup_id)
            output_json(
                controller.verify_manifest(
                    manifest,
                    online=not args.offline,
                    verify_control=not args.history_only,
                )
            )
        elif args.command == "prune":
            output_json({"removed": controller.prune()})
        elif args.command == "extract-config":
            manifest = controller.select_manifest(args.backup_id)
            controller.verify_manifest(manifest, online=False)
            output_json(
                {
                    "backup_id": manifest["backup_id"],
                    "extracted": controller.extract_stack_config(
                        manifest,
                        args.destination,
                    ),
                }
            )
        elif args.command == "export-key":
            key = read_key(controller.config.encryption_key)
            encoded = base64.urlsafe_b64encode(key).decode("ascii")
            if args.raw:
                print(encoded)
            else:
                output_json(
                    {
                        "recovery_key": encoded,
                        "fingerprint": key_fingerprint(key),
                        "warning": "Store this key separately from the backup directory.",
                    }
                )
        elif args.command == "restore":
            output_json(
                controller.restore(
                    args.backup_id,
                    replace_existing=args.replace_existing,
                    history_only=args.history_only,
                )
            )
        elif args.command == "release":
            with controller.operation():
                controller.release_maintenance_lock()
                controller.write_status(
                    "success",
                    message="Restore maintenance lock released",
                    next_run_at=iso(next_daily_run(controller.config.schedule)),
                )
            output_json({"released": True})
        elif args.command == "health":
            try:
                status = json.loads(
                    controller.config.local_status.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                return 0
            return 1 if status.get("state") == "error" else 0
        return 0
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
