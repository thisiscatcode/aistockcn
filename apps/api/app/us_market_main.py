from __future__ import annotations

import ipaddress
import socket

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers.us_market import router as us_market_router

app = FastAPI(
    title="AiStockCN US Market API",
    version="0.1.0",
    description="Read-only US equity product API, isolated from the existing A-share control API.",
)


def _allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(cidr, strict=False) for cidr in get_settings().panel_api_allowed_cidrs)


def _allowed_service_ips() -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    allowed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for service_name in get_settings().panel_api_allowed_service_names:
        try:
            infos = socket.getaddrinfo(service_name, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for info in infos:
            raw_ip = info[4][0]
            if raw_ip in seen:
                continue
            seen.add(raw_ip)
            try:
                allowed.append(ipaddress.ip_address(raw_ip))
            except ValueError:
                continue
    return tuple(allowed)


ALLOWED_NETWORKS = _allowed_networks()


@app.middleware("http")
async def restrict_api_clients(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    client = request.client
    try:
        client_ip = ipaddress.ip_address(client.host) if client else None
    except ValueError:
        client_ip = None
    if client_ip and (any(client_ip in network for network in ALLOWED_NETWORKS) or client_ip in _allowed_service_ips()):
        return await call_next(request)
    return JSONResponse(status_code=403, content={"detail": "API access is restricted to trusted local services."})


app.include_router(us_market_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "us-market-api"}


@app.get("/")
def root() -> dict[str, object]:
    return {"name": "AiStockCN US Market API", "market": "US", "docs": "/docs"}
