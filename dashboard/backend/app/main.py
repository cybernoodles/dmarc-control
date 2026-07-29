from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
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
    cluster = await client.health()
    return {
        "status": "ok",
        "version": VERSION,
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
