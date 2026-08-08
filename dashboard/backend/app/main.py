from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    READ_SESSION_COOKIE,
    SESSION_COOKIE,
    SESSION_HOURS,
    Session,
    create_admin_session,
    create_read_session,
    hash_password,
    session_hash,
    verify_password,
)
from .config import settings
from .connection import (
    ConnectionSecretError,
    ConnectionTestError,
    SecretVault,
    test_mailbox_connection,
)
from .opensearch import OpenSearchClient, OpenSearchError
from .notifications import (
    NOTIFICATION_CASES,
    NotificationDeliveryError,
    build_message,
    destination_hash,
    notification_case,
    send_message,
    test_alert,
)
from .service import DashboardService
from .store import StateStore

VERSION = "2.0.0-rc.1"
NOTIFICATION_VAULT_AAD = b"dmarc-control-notifications-v1"
logger = logging.getLogger(__name__)

client = OpenSearchClient(
    settings.opensearch_url,
    timeout_seconds=settings.request_timeout_seconds,
)
store = StateStore(settings.database_path)
service = DashboardService(client, store, settings)


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.notification_wakeup = asyncio.Event()
    task = asyncio.create_task(notification_delivery_loop(application))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="DMARC Control API",
    version=VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


class AlertStatusUpdate(BaseModel):
    status: Literal["open", "acknowledged", "resolved", "ignored"]


class HostClassificationUpdate(BaseModel):
    service_name: str | None = Field(default=None, max_length=120)
    trust_status: Literal["unconfirmed", "automatic", "confirmed", "ignored"]
    notes: str | None = Field(default=None, max_length=500)


class AppearanceUpdate(BaseModel):
    profile: Literal["standard", "custom"]
    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
    )


class PasswordRequest(BaseModel):
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class InitialSetupRequest(BaseModel):
    admin_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )
    read_username: str = Field(min_length=1, max_length=120)
    read_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class ReadLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class ReadCredentialsUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(
        min_length=1,
        max_length=PASSWORD_MAX_LENGTH,
    )
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class MailboxConnectionUpdate(BaseModel):
    provider: Literal["msgraph", "imap"]
    tenant_id: str | None = Field(default=None, max_length=120)
    client_id: str | None = Field(default=None, max_length=120)
    client_secret: str | None = Field(default=None, max_length=2048)
    mailbox: str | None = Field(default=None, max_length=320)
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    user: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=2048)
    reports_folder: str = Field(default="INBOX", max_length=255)
    archive_folder: str = Field(default="Archive", max_length=255)


class ParserStatusUpdate(BaseModel):
    mode: Literal["legacy", "managed"]
    state: Literal["starting", "running", "restarting", "error", "stopped"]
    revision: int | None = Field(default=None, ge=1)
    version: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=500)
    pid: int | None = Field(default=None, ge=1)


NotificationCase = Literal[
    "new-host-fail",
    "host-degradation",
    "host-fail",
    "dynamic-ip-fail",
    "new-source-ip",
    "compensated-alignment",
    "stale-reports",
]


class SmtpNotificationUpdate(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "tls", "plain"] = "starttls"
    username: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, max_length=2048)


class GraphNotificationUpdate(BaseModel):
    reuse_mailbox_connection: bool = True
    tenant_id: str = Field(default="", max_length=120)
    client_id: str = Field(default="", max_length=120)
    client_secret: str | None = Field(default=None, max_length=2048)


class NotificationSettingsUpdate(BaseModel):
    enabled: bool = False
    transport: Literal["smtp", "msgraph"] = "smtp"
    recipients: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    sender: str = Field(min_length=3, max_length=320)
    language: Literal["de", "en"] = "de"
    dashboard_url: str = Field(default="", max_length=500)
    cases: list[NotificationCase] = Field(
        default_factory=lambda: [
            "new-host-fail",
            "host-degradation",
            "host-fail",
            "dynamic-ip-fail",
            "stale-reports",
        ],
        min_length=1,
    )
    smtp: SmtpNotificationUpdate = Field(
        default_factory=SmtpNotificationUpdate
    )
    graph: GraphNotificationUpdate = Field(
        default_factory=GraphNotificationUpdate
    )


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
HOST_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def current_session_hash(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    return session_hash(token) if token else None


def current_read_session_hash(request: Request) -> str | None:
    token = request.cookies.get(READ_SESSION_COOKIE)
    return session_hash(token) if token else None


def is_admin_authenticated(request: Request) -> bool:
    current_hash = current_session_hash(request)
    return bool(current_hash and store.admin_session_valid(current_hash))


def is_read_authenticated(request: Request) -> bool:
    current_hash = current_read_session_hash(request)
    return bool(current_hash and store.read_session_valid(current_hash))


def require_admin(request: Request) -> None:
    if not is_admin_authenticated(request):
        raise HTTPException(status_code=401, detail="Admin login required")


def _set_session_cookie(response: Response, key: str, session: Session) -> None:
    response.set_cookie(
        key=key,
        value=session.token,
        max_age=SESSION_HOURS * 60 * 60,
        expires=session.expires_at,
        path="/",
        secure=settings.session_secure_cookie,
        httponly=True,
        samesite="strict",
    )


def set_admin_cookie(response: Response, session: Session) -> None:
    _set_session_cookie(response, SESSION_COOKIE, session)


def set_read_cookie(response: Response, session: Session) -> None:
    _set_session_cookie(response, READ_SESSION_COOKIE, session)


def delete_session_cookie(response: Response, key: str) -> None:
    response.delete_cookie(
        key,
        path="/",
        secure=settings.session_secure_cookie,
        httponly=True,
        samesite="strict",
    )


def normalized_read_username(username: str) -> tuple[str, str]:
    cleaned = username.strip()
    if not cleaned or any(character.isspace() for character in cleaned):
        raise HTTPException(
            status_code=422,
            detail="Read username must not contain whitespace",
        )
    return cleaned, cleaned.casefold()


def auth_status_payload(request: Request) -> dict:
    setup_required = not store.setup_complete()
    read_authenticated = (
        False if setup_required else is_read_authenticated(request)
    )
    return {
        "setup_required": setup_required,
        "admin_configured": store.admin_configured(),
        "read_authenticated": read_authenticated,
        "read_username": store.read_username() if read_authenticated else None,
        "authenticated": (
            False
            if setup_required or not read_authenticated
            else is_admin_authenticated(request)
        ),
    }


def mailbox_vault() -> SecretVault:
    return SecretVault(settings.connection_key_path)


def _clean_required(value: str | None, label: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{label} is required")
    return cleaned


def _clean_folder(value: str, label: str) -> str:
    cleaned = value.strip().strip("/")
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{label} is required")
    if any(character in cleaned for character in ("\x00", "\r", "\n")):
        raise HTTPException(
            status_code=422,
            detail=f"{label} contains invalid characters",
        )
    return cleaned


def _existing_mailbox_secret(
    state: dict,
    provider: str,
) -> dict[str, str] | None:
    for candidate in (state.get("draft"), state.get("active")):
        if candidate and candidate["provider"] == provider:
            try:
                return mailbox_vault().decrypt(candidate["secret_ciphertext"])
            except ConnectionSecretError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
    return None


def normalize_mailbox_update(
    update: MailboxConnectionUpdate,
    state: dict,
) -> tuple[dict, dict[str, str]]:
    reports_folder = _clean_folder(update.reports_folder, "Reports folder")
    archive_folder = _clean_folder(update.archive_folder, "Archive folder")
    if reports_folder.casefold() == archive_folder.casefold():
        raise HTTPException(
            status_code=422,
            detail="Reports and archive folders must be different",
        )

    existing_secret = _existing_mailbox_secret(state, update.provider) or {}
    if update.provider == "msgraph":
        tenant_id = _clean_required(update.tenant_id, "Tenant ID")
        client_id = _clean_required(update.client_id, "Client ID")
        mailbox = _clean_required(update.mailbox, "Mailbox")
        if not UUID_PATTERN.fullmatch(tenant_id):
            raise HTTPException(
                status_code=422,
                detail="Tenant ID must be a UUID",
            )
        if not UUID_PATTERN.fullmatch(client_id):
            raise HTTPException(
                status_code=422,
                detail="Client ID must be a UUID",
            )
        if "@" not in mailbox or any(
            character.isspace() for character in mailbox
        ):
            raise HTTPException(
                status_code=422,
                detail="Mailbox must be an email address",
            )
        client_secret = (
            update.client_secret
            if update.client_secret
            else existing_secret.get("client_secret")
        )
        if not client_secret:
            raise HTTPException(
                status_code=422,
                detail="Client secret is required",
            )
        return (
            {
                "auth_method": "ClientSecret",
                "tenant_id": tenant_id,
                "client_id": client_id,
                "mailbox": mailbox,
                "reports_folder": reports_folder,
                "archive_folder": archive_folder,
            },
            {"client_secret": client_secret},
        )

    host = _clean_required(update.host, "IMAP host")
    user = _clean_required(update.user, "IMAP user")
    if not HOST_PATTERN.fullmatch(host) or "://" in host:
        raise HTTPException(
            status_code=422,
            detail="IMAP host is invalid",
        )
    password = (
        update.password if update.password else existing_secret.get("password")
    )
    if not password:
        raise HTTPException(
            status_code=422,
            detail="IMAP password is required",
        )
    return (
        {
            "host": host,
            "port": update.port,
            "ssl": True,
            "skip_certificate_verification": False,
            "user": user,
            "reports_folder": reports_folder,
            "archive_folder": archive_folder,
        },
        {"password": password},
    )


def public_mailbox_state(state: dict | None = None) -> dict:
    current = state or store.mailbox_connection_state()

    def public_version(version: dict | None) -> dict | None:
        if not version:
            return None
        return {
            "revision": version["revision"],
            "provider": version["provider"],
            "settings": version["settings"],
            "secret_configured": bool(version["secret_ciphertext"]),
            "created_at": version["created_at"],
        }

    return {
        "configured": current["draft"] is not None,
        "draft": public_version(current["draft"]),
        "active": public_version(current["active"]),
        "draft_revision": current["draft_revision"],
        "tested_revision": current["tested_revision"],
        "active_revision": current["active_revision"],
        "test_status": current["test_status"],
        "test_message": current["test_message"],
        "tested_at": current["tested_at"],
        "updated_at": current["updated_at"],
        "parser": current["runtime"],
    }


def notification_vault() -> SecretVault:
    return SecretVault(
        settings.connection_key_path,
        aad=NOTIFICATION_VAULT_AAD,
    )


def _clean_email(value: str, label: str) -> str:
    cleaned = value.strip()
    if (
        len(cleaned) > 320
        or cleaned.count("@") != 1
        or any(character.isspace() for character in cleaned)
        or any(character in cleaned for character in ("\r", "\n", "\x00"))
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be an email address",
        )
    local, domain = cleaned.rsplit("@", 1)
    if not local or "." not in domain or domain.startswith("."):
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be an email address",
        )
    return cleaned


def _existing_notification_secret() -> dict[str, str]:
    current = store.notification_settings()
    if not current:
        return {}
    try:
        return notification_vault().decrypt(current["secret_ciphertext"])
    except ConnectionSecretError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def normalize_notification_update(
    update: NotificationSettingsUpdate,
) -> tuple[dict, dict[str, str]]:
    recipients: list[str] = []
    for index, recipient in enumerate(update.recipients, start=1):
        cleaned = _clean_email(recipient, f"Recipient {index}")
        if cleaned.casefold() not in {
            existing.casefold() for existing in recipients
        }:
            recipients.append(cleaned)
    sender = _clean_email(update.sender, "Sender")
    selected_cases = list(dict.fromkeys(update.cases))
    if not selected_cases or any(
        item not in NOTIFICATION_CASES for item in selected_cases
    ):
        raise HTTPException(
            status_code=422,
            detail="At least one supported notification case is required",
        )
    dashboard_url = update.dashboard_url.strip().rstrip("/")
    if dashboard_url:
        parsed_url = urlparse(dashboard_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise HTTPException(
                status_code=422,
                detail="Dashboard URL must be an HTTP or HTTPS URL",
            )

    existing_secret = _existing_notification_secret()
    smtp_host = update.smtp.host.strip()
    smtp_username = update.smtp.username.strip()
    if update.transport == "smtp":
        if (
            not smtp_host
            or not HOST_PATTERN.fullmatch(smtp_host)
            or "://" in smtp_host
        ):
            raise HTTPException(
                status_code=422,
                detail="SMTP host is invalid",
            )
        if smtp_username and not update.smtp.password:
            if not existing_secret.get("smtp_password"):
                raise HTTPException(
                    status_code=422,
                    detail="SMTP password is required when a username is set",
                )

    graph_tenant_id = update.graph.tenant_id.strip()
    graph_client_id = update.graph.client_id.strip()
    if update.transport == "msgraph" and not update.graph.reuse_mailbox_connection:
        if not UUID_PATTERN.fullmatch(graph_tenant_id):
            raise HTTPException(
                status_code=422,
                detail="Graph tenant ID must be a UUID",
            )
        if not UUID_PATTERN.fullmatch(graph_client_id):
            raise HTTPException(
                status_code=422,
                detail="Graph client ID must be a UUID",
            )
        if (
            not update.graph.client_secret
            and not existing_secret.get("graph_client_secret")
        ):
            raise HTTPException(
                status_code=422,
                detail="Graph client secret is required",
            )

    normalized = {
        "enabled": update.enabled,
        "transport": update.transport,
        "recipients": recipients,
        "sender": sender,
        "language": update.language,
        "dashboard_url": dashboard_url,
        "cases": selected_cases,
        "lookback_days": 30,
        "smtp": {
            "host": smtp_host,
            "port": update.smtp.port,
            "security": update.smtp.security,
            "username": smtp_username,
        },
        "graph": {
            "reuse_mailbox_connection": (
                update.graph.reuse_mailbox_connection
            ),
            "tenant_id": graph_tenant_id,
            "client_id": graph_client_id,
        },
    }
    secret = {
        "smtp_password": (
            update.smtp.password
            if update.smtp.password is not None
            else existing_secret.get("smtp_password", "")
        ),
        "graph_client_secret": (
            update.graph.client_secret
            if update.graph.client_secret is not None
            else existing_secret.get("graph_client_secret", "")
        ),
    }
    return normalized, secret


def _resolved_notification_configuration(
    current: dict | None = None,
) -> tuple[dict, dict[str, str]]:
    stored = current or store.notification_settings()
    if not stored:
        raise NotificationDeliveryError(
            "Notification settings are not configured"
        )
    try:
        secret = notification_vault().decrypt(stored["secret_ciphertext"])
    except ConnectionSecretError as exc:
        raise NotificationDeliveryError(str(exc)) from exc
    configuration = {
        **stored["settings"],
        "smtp": dict(stored["settings"]["smtp"]),
        "graph": dict(stored["settings"]["graph"]),
    }
    graph = configuration["graph"]
    if (
        configuration["transport"] == "msgraph"
        and graph["reuse_mailbox_connection"]
    ):
        mailbox_state = store.mailbox_connection_state()
        version = next(
            (
                candidate
                for candidate in (
                    mailbox_state.get("active"),
                    mailbox_state.get("draft"),
                )
                if candidate and candidate["provider"] == "msgraph"
            ),
            None,
        )
        if not version:
            raise NotificationDeliveryError(
                "No Microsoft Graph mailbox connection is available for reuse"
            )
        try:
            mailbox_secret = mailbox_vault().decrypt(
                version["secret_ciphertext"]
            )
        except ConnectionSecretError as exc:
            raise NotificationDeliveryError(str(exc)) from exc
        graph["tenant_id"] = version["settings"]["tenant_id"]
        graph["client_id"] = version["settings"]["client_id"]
        secret["graph_client_secret"] = mailbox_secret["client_secret"]
    return configuration, secret


def public_notification_state(current: dict | None = None) -> dict:
    stored = current if current is not None else store.notification_settings()
    if not stored:
        return {
            "configured": False,
            "enabled": False,
            "transport": "smtp",
            "recipients": [],
            "sender": "",
            "language": "de",
            "dashboard_url": "",
            "cases": [
                "new-host-fail",
                "host-degradation",
                "host-fail",
                "dynamic-ip-fail",
                "stale-reports",
            ],
            "smtp": {
                "host": "",
                "port": 587,
                "security": "starttls",
                "username": "",
                "password_configured": False,
            },
            "graph": {
                "reuse_mailbox_connection": True,
                "tenant_id": "",
                "client_id": "",
                "client_secret_configured": False,
            },
            "test_status": "untested",
            "test_message": None,
            "tested_at": None,
            "updated_at": None,
            "delivery": store.notification_delivery_summary(),
        }
    try:
        secret = notification_vault().decrypt(stored["secret_ciphertext"])
    except ConnectionSecretError:
        secret = {}
    public_settings = stored["settings"]
    return {
        "configured": True,
        "enabled": public_settings["enabled"],
        "transport": public_settings["transport"],
        "recipients": public_settings["recipients"],
        "sender": public_settings["sender"],
        "language": public_settings["language"],
        "dashboard_url": public_settings["dashboard_url"],
        "cases": public_settings["cases"],
        "smtp": {
            **public_settings["smtp"],
            "password_configured": bool(secret.get("smtp_password")),
        },
        "graph": {
            **public_settings["graph"],
            "client_secret_configured": bool(
                secret.get("graph_client_secret")
            ),
        },
        "test_status": stored["test_status"],
        "test_message": stored["test_message"],
        "tested_at": stored["tested_at"],
        "updated_at": stored["updated_at"],
        "delivery": store.notification_delivery_summary(),
    }


async def dispatch_notification_cycle() -> None:
    current = store.notification_settings()
    if not current or not current["settings"].get("enabled"):
        return
    configuration, secret = _resolved_notification_configuration(current)
    alerts_to_send = await service.alerts(
        "*",
        int(configuration.get("lookback_days", 30)),
    )
    selected_cases = set(configuration["cases"])
    delivery_target = destination_hash(configuration)
    for alert in alerts_to_send:
        event_type = notification_case(alert)
        if alert.get("status") != "open" or event_type not in selected_cases:
            continue
        if not store.claim_notification_delivery(
            alert_id=alert["id"],
            destination_hash=delivery_target,
        ):
            continue
        try:
            message = build_message(alert, configuration)
            await asyncio.to_thread(
                send_message,
                message,
                configuration,
                secret,
            )
        except Exception as exc:
            store.finish_notification_delivery(
                alert_id=alert["id"],
                destination_hash=delivery_target,
                success=False,
                error=(
                    str(exc)
                    if isinstance(exc, NotificationDeliveryError)
                    else "Notification message could not be generated"
                ),
            )
        else:
            store.finish_notification_delivery(
                alert_id=alert["id"],
                destination_hash=delivery_target,
                success=True,
            )


async def notification_delivery_loop(application: FastAPI) -> None:
    wakeup: asyncio.Event = application.state.notification_wakeup
    while True:
        try:
            await asyncio.wait_for(
                wakeup.wait(),
                timeout=settings.notification_poll_seconds,
            )
        except TimeoutError:
            pass
        wakeup.clear()
        try:
            await dispatch_notification_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification delivery cycle failed")


def configured_parser_control_token() -> str:
    token_file = settings.parser_control_token_file
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        try:
            descriptor = os.open(
                token_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o640,
            )
        except FileExistsError:
            return token_file.read_text(encoding="utf-8").strip()
        with os.fdopen(descriptor, "w", encoding="utf-8") as token_handle:
            token_handle.write(f"{token}\n")
        return token
    except OSError:
        return ""


def require_parser_control_token(provided_token: str | None) -> None:
    expected_token = configured_parser_control_token()
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Parser control token is not available",
        )
    if not provided_token or not hmac.compare_digest(
        provided_token.strip(),
        expected_token,
    ):
        raise HTTPException(status_code=403, detail="Invalid parser control token")


@app.middleware("http")
async def security_headers(request, call_next):
    public_api_paths = {
        "/api/auth/read-login",
        "/api/auth/read-logout",
        "/api/auth/setup",
        "/api/auth/status",
        "/api/health",
    }
    read_login_required = (
        request.url.path.startswith("/api/")
        and request.url.path not in public_api_paths
        and not request.url.path.startswith("/api/internal/")
        and not is_read_authenticated(request)
    )
    if read_login_required:
        response = JSONResponse(
            status_code=401,
            content={"detail": "Read login required"},
        )
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.exception_handler(OpenSearchError)
async def opensearch_error_handler(_request, exc: OpenSearchError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/api/health")
async def health():
    parser_control_ready = bool(configured_parser_control_token())
    cluster = await client.health()
    return {
        "status": "ok",
        "version": VERSION,
        "parser_control": {
            "ready": parser_control_ready,
        },
        "opensearch": {
            "status": cluster.get("status"),
            "cluster_name": cluster.get("cluster_name"),
        },
    }


@app.get("/api/domains")
async def domains():
    return {"items": await service.domains()}


@app.get("/api/auth/status")
async def auth_status(request: Request):
    return auth_status_payload(request)


@app.post("/api/auth/setup", status_code=201)
async def setup_access(
    update: InitialSetupRequest,
    response: Response,
):
    if store.read_configured():
        raise HTTPException(
            status_code=409,
            detail="Initial setup is already complete",
        )

    read_username, read_username_normalized = normalized_read_username(
        update.read_username
    )
    admin_password_hash = store.admin_password_hash()
    if admin_password_hash:
        if not verify_password(update.admin_password, admin_password_hash):
            raise HTTPException(
                status_code=401,
                detail="Invalid admin password",
            )
        saved = store.set_initial_read_credentials(
            expected_admin_hash=admin_password_hash,
            read_username=read_username,
            read_username_normalized=read_username_normalized,
            read_password_hash=hash_password(update.read_password),
        )
    else:
        saved = store.set_initial_credentials(
            admin_password_hash=hash_password(update.admin_password),
            read_username=read_username,
            read_username_normalized=read_username_normalized,
            read_password_hash=hash_password(update.read_password),
        )
    if not saved:
        raise HTTPException(
            status_code=409,
            detail="Initial setup was completed concurrently",
        )

    set_read_cookie(response, create_read_session(store))
    set_admin_cookie(response, create_admin_session(store))
    return {
        "setup_required": False,
        "admin_configured": True,
        "read_authenticated": True,
        "read_username": read_username,
        "authenticated": True,
    }


@app.post("/api/auth/read-login")
async def login_read_user(
    update: ReadLoginRequest,
    request: Request,
    response: Response,
):
    if not store.setup_complete():
        raise HTTPException(status_code=409, detail="Initial setup required")
    _read_username, read_username_normalized = normalized_read_username(
        update.username
    )
    password_hash = store.read_password_hash(read_username_normalized)
    if not password_hash or not verify_password(update.password, password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid read credentials",
        )
    set_read_cookie(response, create_read_session(store))
    return {
        "setup_required": False,
        "admin_configured": True,
        "read_authenticated": True,
        "read_username": store.read_username(),
        "authenticated": is_admin_authenticated(request),
    }


@app.post("/api/auth/read-logout")
async def logout_read_user(request: Request, response: Response):
    read_hash = current_read_session_hash(request)
    admin_hash = current_session_hash(request)
    if read_hash:
        store.delete_read_session(read_hash)
    if admin_hash:
        store.delete_admin_session(admin_hash)
    delete_session_cookie(response, READ_SESSION_COOKIE)
    delete_session_cookie(response, SESSION_COOKIE)
    return {
        "setup_required": not store.setup_complete(),
        "admin_configured": store.admin_configured(),
        "read_authenticated": False,
        "read_username": None,
        "authenticated": False,
    }


@app.post("/api/auth/login")
async def login_admin(update: PasswordRequest, response: Response):
    password_hash = store.admin_password_hash()
    if not password_hash:
        raise HTTPException(status_code=409, detail="Admin setup required")
    if not verify_password(update.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin password")
    set_admin_cookie(response, create_admin_session(store))
    return {
        "setup_required": False,
        "admin_configured": True,
        "read_authenticated": True,
        "read_username": store.read_username(),
        "authenticated": True,
    }


@app.post("/api/auth/logout")
async def logout_admin(request: Request, response: Response):
    current_hash = current_session_hash(request)
    if current_hash:
        store.delete_admin_session(current_hash)
    delete_session_cookie(response, SESSION_COOKIE)
    return auth_status_payload(request)


@app.post("/api/auth/change-password")
async def change_admin_password(
    update: PasswordChangeRequest,
    request: Request,
    response: Response,
):
    require_admin(request)
    password_hash = store.admin_password_hash()
    if not password_hash or not verify_password(
        update.current_password,
        password_hash,
    ):
        raise HTTPException(
            status_code=403,
            detail="Current admin password is invalid",
        )
    if verify_password(update.new_password, password_hash):
        raise HTTPException(
            status_code=422,
            detail="New password must be different",
        )
    if not store.replace_admin_password(
        expected_hash=password_hash,
        password_hash=hash_password(update.new_password),
    ):
        raise HTTPException(
            status_code=409,
            detail="Admin password changed concurrently",
        )
    set_admin_cookie(response, create_admin_session(store))
    return {
        "setup_required": False,
        "admin_configured": True,
        "read_authenticated": True,
        "read_username": store.read_username(),
        "authenticated": True,
    }


@app.put("/api/auth/read-credentials")
async def update_read_credentials(
    update: ReadCredentialsUpdate,
    request: Request,
    response: Response,
):
    require_admin(request)
    read_username, read_username_normalized = normalized_read_username(
        update.username
    )
    if not store.replace_read_credentials(
        read_username=read_username,
        read_username_normalized=read_username_normalized,
        password_hash=hash_password(update.password),
    ):
        raise HTTPException(
            status_code=409,
            detail="Read user is not configured",
        )
    set_read_cookie(response, create_read_session(store))
    return {
        "setup_required": False,
        "admin_configured": True,
        "read_authenticated": True,
        "read_username": read_username,
        "authenticated": True,
    }


@app.get("/api/settings/appearance")
async def appearance_settings():
    return {
        **store.appearance_settings(),
        "write_protected": True,
        "admin_configured": store.admin_configured(),
    }


@app.put("/api/settings/appearance")
async def update_appearance_settings(
    update: AppearanceUpdate,
    request: Request,
):
    require_admin(request)
    if update.profile == "custom" and not update.color:
        raise HTTPException(
            status_code=422,
            detail="A custom color is required for the custom profile",
        )
    result = store.set_global_appearance(
        profile=update.profile,
        color=(update.color or "#173f43").lower(),
    )
    return {
        **result,
        "write_protected": True,
        "admin_configured": True,
    }


@app.get("/api/settings/mailbox")
async def mailbox_settings(request: Request):
    require_admin(request)
    return public_mailbox_state()


@app.put("/api/settings/mailbox")
async def update_mailbox_settings(
    update: MailboxConnectionUpdate,
    request: Request,
):
    require_admin(request)
    current = store.mailbox_connection_state()
    normalized, secret = normalize_mailbox_update(update, current)
    try:
        encrypted_secret = mailbox_vault().encrypt(secret)
    except ConnectionSecretError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    saved = store.save_mailbox_connection(
        provider=update.provider,
        settings=normalized,
        secret_ciphertext=encrypted_secret,
    )
    return public_mailbox_state(saved)


@app.post("/api/settings/mailbox/test")
async def test_mailbox_settings(request: Request):
    require_admin(request)
    current = store.mailbox_connection_state()
    draft = current["draft"]
    if not draft:
        raise HTTPException(
            status_code=409,
            detail="Save a mailbox connection before testing it",
        )
    try:
        secret = mailbox_vault().decrypt(draft["secret_ciphertext"])
        message = await asyncio.to_thread(
            test_mailbox_connection,
            draft["provider"],
            draft["settings"],
            secret,
        )
        test_status = "success"
    except (ConnectionSecretError, ConnectionTestError) as exc:
        message = str(exc)
        test_status = "failure"
    if not store.record_mailbox_test(
        revision=draft["revision"],
        status=test_status,
        message=message,
    ):
        raise HTTPException(
            status_code=409,
            detail="Mailbox settings changed while the test was running",
        )
    return public_mailbox_state()


@app.post("/api/settings/mailbox/activate")
async def activate_mailbox_settings(request: Request):
    require_admin(request)
    current = store.mailbox_connection_state()
    revision = current["draft_revision"]
    if revision is None:
        raise HTTPException(
            status_code=409,
            detail="Save and test a mailbox connection before activating it",
        )
    if not store.activate_mailbox_connection(revision):
        raise HTTPException(
            status_code=409,
            detail="The current mailbox settings require a successful test",
        )
    return public_mailbox_state()


@app.get("/api/settings/notifications")
async def notification_settings(request: Request):
    require_admin(request)
    return public_notification_state()


@app.put("/api/settings/notifications")
async def update_notification_settings(
    update: NotificationSettingsUpdate,
    request: Request,
):
    require_admin(request)
    normalized, secret = normalize_notification_update(update)
    try:
        encrypted_secret = notification_vault().encrypt(secret)
    except ConnectionSecretError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    saved = store.save_notification_settings(
        settings=normalized,
        secret_ciphertext=encrypted_secret,
    )
    if normalized["enabled"] and hasattr(app.state, "notification_wakeup"):
        app.state.notification_wakeup.set()
    return public_notification_state(saved)


@app.post("/api/settings/notifications/test")
async def test_notification_settings(request: Request):
    require_admin(request)
    current = store.notification_settings()
    if not current:
        raise HTTPException(
            status_code=409,
            detail="Save notification settings before sending a test email",
        )
    try:
        configuration, secret = _resolved_notification_configuration(current)
        message = build_message(
            test_alert(),
            configuration,
            test=True,
        )
        await asyncio.to_thread(
            send_message,
            message,
            configuration,
            secret,
        )
        status = "success"
        result_message = "Test email was delivered to the configured transport"
    except NotificationDeliveryError as exc:
        status = "failure"
        result_message = str(exc)
    tested = store.record_notification_test(
        status=status,
        message=result_message,
    )
    return public_notification_state(tested)


@app.get("/api/internal/parser/config")
async def parser_configuration(
    response: Response,
    parser_token: str | None = Header(
        default=None,
        alias="X-Parser-Control-Token",
    ),
):
    require_parser_control_token(parser_token)
    response.headers["Cache-Control"] = "no-store"
    current = store.mailbox_connection_state()
    active = current["active"]
    if not active:
        return {"mode": "legacy", "revision": None, "connection": None}
    try:
        secret = mailbox_vault().decrypt(active["secret_ciphertext"])
    except ConnectionSecretError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "mode": "managed",
        "revision": active["revision"],
        "connection": {
            "provider": active["provider"],
            **active["settings"],
            **secret,
        },
    }


@app.post("/api/internal/parser/status")
async def update_parser_status(
    update: ParserStatusUpdate,
    parser_token: str | None = Header(
        default=None,
        alias="X-Parser-Control-Token",
    ),
):
    require_parser_control_token(parser_token)
    return store.set_parser_runtime_status(update.model_dump())


@app.get("/api/overview")
async def overview(
    domain: str = Query(default="*", max_length=255),
    days: int = Query(default=30, ge=1, le=730),
):
    return await service.overview(domain, days)


@app.get("/api/hosts")
async def hosts(
    domain: str = Query(default="*", max_length=255),
    days: int = Query(default=90, ge=1, le=730),
    risk: Literal[
        "all",
        "critical",
        "warning",
        "healthy",
        "spf-not-aligned",
        "dkim-not-aligned",
    ] = "all",
    limit: int = Query(default=100, ge=1, le=500),
):
    return {
        "scope": {"domain": domain, "days": days, "risk": risk},
        "items": await service.hosts(domain, days, risk=risk, limit=limit),
    }


@app.get("/api/hosts/{source_ip}")
async def host_detail(
    source_ip: str,
    domain: str = Query(default="*", max_length=255),
    days: int = Query(default=90, ge=1, le=730),
):
    items = await service.hosts(
        domain,
        days,
        limit=1,
        source_ip=source_ip,
    )
    if not items:
        raise HTTPException(status_code=404, detail="Sending Host nicht gefunden")
    return items[0]


@app.put("/api/hosts/{source_ip}/classification")
async def update_host_classification(
    source_ip: str,
    update: HostClassificationUpdate,
):
    return store.set_host_override(
        source_ip,
        service_name=update.service_name,
        trust_status=update.trust_status,
        notes=update.notes,
    )


@app.delete("/api/hosts/{source_ip}/classification")
async def clear_host_classification(source_ip: str):
    return {
        "source_ip": source_ip,
        "automatic": True,
        "override_removed": store.clear_host_override(source_ip),
    }


@app.get("/api/alerts")
async def alerts(
    domain: str = Query(default="*", max_length=255),
    days: int = Query(default=30, ge=1, le=730),
    status: Literal[
        "all", "open", "acknowledged", "resolved", "ignored"
    ] = "all",
):
    items = await service.alerts(domain, days)
    if status != "all":
        items = [item for item in items if item["status"] == status]
    return {"scope": {"domain": domain, "days": days}, "items": items}


@app.patch("/api/alerts/{alert_id}")
async def update_alert(alert_id: str, update: AlertStatusUpdate):
    return store.set_alert_status(alert_id, update.status)


@app.get("/api/forensics")
async def forensics(
    domain: str = Query(default="*", max_length=255),
    days: int = Query(default=30, ge=1, le=730),
    failure_type: str = Query(default="*", max_length=120),
):
    return await service.forensics(domain, days, failure_type)


static_directory = Path(__file__).resolve().parent.parent / "static"
if static_directory.exists():
    app.mount("/", StaticFiles(directory=static_directory, html=True), name="frontend")
