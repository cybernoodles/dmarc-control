from __future__ import annotations

import base64
import binascii
import imaplib
import json
import os
import secrets
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VAULT_AAD = b"dmarc-control-mailbox-v1"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_TOKEN_ROOT = "https://login.microsoftonline.com"


class ConnectionSecretError(RuntimeError):
    pass


class ConnectionTestError(RuntimeError):
    pass


class SecretVault:
    def __init__(self, key_path: Path, aad: bytes = VAULT_AAD) -> None:
        self._key_path = key_path
        self._aad = aad

    def _key(self) -> bytes:
        try:
            key = self._key_path.read_bytes()
        except FileNotFoundError:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_bytes(32)
            try:
                descriptor = os.open(
                    self._key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                key = self._key_path.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(key)
        if len(key) != 32:
            raise ConnectionSecretError(
                "Mailbox encryption key has an invalid length"
            )
        return key

    def encrypt(self, values: dict[str, str]) -> str:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = AESGCM(self._key()).encrypt(
            nonce,
            plaintext,
            self._aad,
        )
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, encoded: str) -> dict[str, str]:
        try:
            payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
            plaintext = AESGCM(self._key()).decrypt(
                payload[:12],
                payload[12:],
                self._aad,
            )
            values = json.loads(plaintext.decode("utf-8"))
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            binascii.Error,
            InvalidTag,
        ) as exc:
            raise ConnectionSecretError(
                "Stored mailbox credentials could not be decrypted"
            ) from exc
        if not isinstance(values, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in values.items()
        ):
            raise ConnectionSecretError(
                "Stored mailbox credentials have an invalid format"
            )
        return values


def _safe_error_message(
    value: str,
    *,
    secret_values: tuple[str, ...],
) -> str:
    message = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    for secret_value in secret_values:
        if secret_value:
            message = message.replace(secret_value, "[redacted]")
    return message[:500]


def _remote_error(
    response: httpx.Response,
    *,
    default: str,
    secret_values: tuple[str, ...],
) -> ConnectionTestError:
    message = default
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(
                    error.get("message")
                    or error.get("description")
                    or message
                )
            else:
                message = str(payload.get("error_description") or error or message)
    except (ValueError, TypeError):
        pass
    return ConnectionTestError(
        _safe_error_message(message, secret_values=secret_values)
    )


def _graph_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _graph_folder(
    client: httpx.Client,
    *,
    mailbox: str,
    folder_path: str,
    access_token: str,
    secret_values: tuple[str, ...],
) -> None:
    segments = [segment.strip() for segment in folder_path.split("/") if segment]
    if not segments:
        raise ConnectionTestError("Mailbox folder must not be empty")

    encoded_mailbox = quote(mailbox, safe="")
    well_known = {
        "inbox": "inbox",
        "archive": "archive",
        "drafts": "drafts",
        "sent items": "sentitems",
        "deleted items": "deleteditems",
        "junk email": "junkemail",
    }
    first = segments.pop(0)
    first_identifier = well_known.get(first.casefold())
    if first_identifier:
        response = client.get(
            f"{GRAPH_ROOT}/users/{encoded_mailbox}/mailFolders/"
            f"{first_identifier}?$select=id,displayName",
            headers=_graph_headers(access_token),
        )
        if response.status_code >= 400:
            raise _remote_error(
                response,
                default=f'Mailbox folder "{first}" is not accessible',
                secret_values=secret_values,
            )
        current = response.json()
    else:
        response = client.get(
            f"{GRAPH_ROOT}/users/{encoded_mailbox}/mailFolders"
            "?$select=id,displayName&$top=999",
            headers=_graph_headers(access_token),
        )
        if response.status_code >= 400:
            raise _remote_error(
                response,
                default="Mailbox folders could not be listed",
                secret_values=secret_values,
            )
        folders = response.json().get("value", [])
        current = next(
            (
                item
                for item in folders
                if str(item.get("displayName", "")).casefold()
                == first.casefold()
            ),
            None,
        )
        if current is None:
            raise ConnectionTestError(
                f'Mailbox folder "{first}" was not found'
            )

    for segment in segments:
        folder_id = quote(str(current.get("id", "")), safe="")
        response = client.get(
            f"{GRAPH_ROOT}/users/{encoded_mailbox}/mailFolders/{folder_id}"
            "/childFolders?$select=id,displayName&$top=999",
            headers=_graph_headers(access_token),
        )
        if response.status_code >= 400:
            raise _remote_error(
                response,
                default=f'Mailbox folder "{segment}" is not accessible',
                secret_values=secret_values,
            )
        folders = response.json().get("value", [])
        current = next(
            (
                item
                for item in folders
                if str(item.get("displayName", "")).casefold()
                == segment.casefold()
            ),
            None,
        )
        if current is None:
            raise ConnectionTestError(
                f'Mailbox folder "{folder_path}" was not found'
            )


def test_msgraph_connection(
    settings: dict[str, Any],
    secret: dict[str, str],
) -> str:
    client_secret = secret["client_secret"]
    secret_values = (client_secret,)
    tenant_id = quote(str(settings["tenant_id"]), safe="")
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
        ) as client:
            token_response = client.post(
                f"{GRAPH_TOKEN_ROOT}/{tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": settings["client_id"],
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                    "scope": "https://graph.microsoft.com/.default",
                },
                headers={"Accept": "application/json"},
            )
            if token_response.status_code >= 400:
                raise _remote_error(
                    token_response,
                    default="Microsoft Entra authentication failed",
                    secret_values=secret_values,
                )
            token_payload = token_response.json()
            access_token = (
                str(token_payload.get("access_token", ""))
                if isinstance(token_payload, dict)
                else ""
            )
            if not access_token:
                raise ConnectionTestError(
                    "Microsoft Entra returned no access token"
                )
            for folder in (
                settings["reports_folder"],
                settings["archive_folder"],
            ):
                _graph_folder(
                    client,
                    mailbox=settings["mailbox"],
                    folder_path=folder,
                    access_token=access_token,
                    secret_values=secret_values,
                )
    except httpx.HTTPError as exc:
        raise ConnectionTestError(
            _safe_error_message(
                f"Microsoft Graph connection failed: {exc}",
                secret_values=secret_values,
            )
        ) from exc
    return "Microsoft-365-Postfach und Ordner sind erreichbar."


def _quoted_imap_mailbox(folder: str) -> str:
    escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def test_imap_connection(
    settings: dict[str, Any],
    secret: dict[str, str],
) -> str:
    password = secret["password"]
    connection: imaplib.IMAP4_SSL | None = None
    try:
        connection = imaplib.IMAP4_SSL(
            host=str(settings["host"]),
            port=int(settings["port"]),
            ssl_context=ssl.create_default_context(),
            timeout=20,
        )
        status, _ = connection.login(str(settings["user"]), password)
        if status != "OK":
            raise ConnectionTestError("IMAP authentication failed")
        for folder in (
            settings["reports_folder"],
            settings["archive_folder"],
        ):
            status, _ = connection.select(
                _quoted_imap_mailbox(str(folder)),
                readonly=True,
            )
            if status != "OK":
                raise ConnectionTestError(
                    f'IMAP folder "{folder}" was not found or is not accessible'
                )
        if hasattr(connection, "unselect"):
            connection.unselect()
    except ConnectionTestError:
        raise
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        raise ConnectionTestError(
            _safe_error_message(
                f"IMAP connection failed: {exc}",
                secret_values=(password,),
            )
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
    return "IMAP-Postfach und Ordner sind erreichbar."


def test_mailbox_connection(
    provider: str,
    settings: dict[str, Any],
    secret: dict[str, str],
) -> str:
    if provider == "msgraph":
        return test_msgraph_connection(settings, secret)
    if provider == "imap":
        return test_imap_connection(settings, secret)
    raise ConnectionTestError("Unsupported mailbox provider")
