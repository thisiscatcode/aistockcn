from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from uuid import uuid4

from app.config import get_settings
from app.routers.research import router as research_router
from app.services.research_documents import init_research_document_schema
from app.services.research_financials import init_research_financial_schema


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_research_document_schema()
    init_research_financial_schema()
    yield


app = FastAPI(
    title="AiStockCN Research API",
    version="0.1.0",
    description="Isolated API for the AiStockCN Research Copilot.",
    lifespan=lifespan,
)


def _allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(
        ipaddress.ip_network(cidr, strict=False)
        for cidr in get_settings().panel_api_allowed_cidrs
    )


def _allowed_service_ips() -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    allowed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for service_name in get_settings().panel_api_allowed_service_names:
        try:
            infos = socket.getaddrinfo(
                service_name,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            continue
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if address not in allowed:
                allowed.append(address)
    return tuple(allowed)


ALLOWED_NETWORKS = _allowed_networks()
REQUEST_LOG = logging.getLogger("aistockcn.research")
RATE_WINDOW_SECONDS = 60.0
RATE_LIMIT = 60
RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def restrict_research_api_clients(request: Request, call_next):
    if request.url.path in {"/", "/health"}:
        return await call_next(request)
    client = request.client
    try:
        client_ip = ipaddress.ip_address(client.host if client else "")
    except ValueError:
        return JSONResponse(status_code=403, content={"detail": "API client is not trusted."})
    if any(client_ip in network for network in ALLOWED_NETWORKS) or client_ip in _allowed_service_ips():
        return await call_next(request)
    return JSONResponse(status_code=403, content={"detail": "API access is restricted."})


@app.middleware("http")
async def research_observability_and_rate_limit(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    started_at = time.perf_counter()
    actor = request.headers.get("x-research-actor") or (request.client.host if request.client else "unknown")
    if request.method == "POST" and request.url.path.startswith("/api/research"):
        now = time.monotonic()
        bucket = RATE_BUCKETS[actor]
        while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Research request rate limit exceeded."},
                headers={"Retry-After": "60", "X-Request-ID": request_id},
            )
        bucket.append(now)
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    REQUEST_LOG.info(json.dumps({
        "event": "research_http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }))
    return response


app.include_router(research_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "aistockcn-research-api"}


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": "AiStockCN Research API",
        "routes": [
            "/api/research/companies",
            "/api/research/companies/{symbol}",
            "POST /api/research/ask",
            "GET /api/research/documents",
            "POST /api/research/documents/upload",
            "POST /api/research/documents/sec/discover",
            "POST /api/research/documents/sec/sync",
            "GET /api/research/financials/{symbol}",
            "POST /api/research/financials/sec/sync",
            "POST /api/research/retrieve",
        ],
    }
