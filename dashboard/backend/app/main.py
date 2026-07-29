from __future__ import annotations

import asyncio
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    SESSION_COOKIE,
    SESSION_HOURS,
    AdminSession,
    create_session,
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
from .service import DashboardService
from .store import StateStore

VERSION = "2.0.0-mvp"

client = OpenSearchClient(
    settings.opensearch_url,
    timeout_seconds=settings.request_timeout_seconds,
)
store = StateStore(settings.database_path)
service = DashboardService(client, store, settings)

app = FastAPI(
    title="DMARC Control API",
    version=VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
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


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
HOST_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def current_session_hash(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    return session_hash(token) if token else None


def is_admin_authenticated(request: Request) -> bool:
    current_hash = current_session_hash(request)
    return bool(current_hash and store.admin_session_valid(current_hash))


def require_admin(request: Request) -> None:
    if not is_admin_authenticated(request):
        raise HTTPException(status_code=401, detail="Admin login required")


def set_admin_cookie(response: Response, session: AdminSession) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.token,
        max_age=SESSION_HOURS * 60 * 60,
        expires=session.expires_at,
        path="/",
        secure=settings.session_secure_cookie,
        httponly=True,
        samesite="strict",
    )


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
    setup_required = not store.admin_configured()
    return {
        "setup_required": setup_required,
        "authenticated": (
            False if setup_required else is_admin_authenticated(request)
        ),
    }


@app.post("/api/auth/setup", status_code=201)
async def setup_admin(update: PasswordRequest, response: Response):
    if not store.set_initial_admin_password(hash_password(update.password)):
        raise HTTPException(
            status_code=409,
            detail="Admin password is already configured",
        )
    set_admin_cookie(response, create_session(store))
    return {"setup_required": False, "authenticated": True}


@app.post("/api/auth/login")
async def login_admin(update: PasswordRequest, response: Response):
    password_hash = store.admin_password_hash()
    if not password_hash:
        raise HTTPException(status_code=409, detail="Admin setup required")
    if not verify_password(update.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin password")
    set_admin_cookie(response, create_session(store))
    return {"setup_required": False, "authenticated": True}


@app.post("/api/auth/logout")
async def logout_admin(request: Request, response: Response):
    current_hash = current_session_hash(request)
    if current_hash:
        store.delete_admin_session(current_hash)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.session_secure_cookie,
        httponly=True,
        samesite="strict",
    )
    return {
        "setup_required": not store.admin_configured(),
        "authenticated": False,
    }


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
    set_admin_cookie(response, create_session(store))
    return {"setup_required": False, "authenticated": True}


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
