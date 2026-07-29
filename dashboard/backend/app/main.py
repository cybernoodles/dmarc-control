from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
