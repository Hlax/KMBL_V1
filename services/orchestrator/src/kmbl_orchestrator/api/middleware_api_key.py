"""Optional shared-secret auth for mutating orchestrator routes (production hardening)."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse

from kmbl_orchestrator.config import get_settings


def _extract_api_key(request: Request) -> str:
    x = (request.headers.get("x-api-key") or "").strip()
    if x:
        return x
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


async def optional_api_key_middleware(request: Request, call_next):
    """
    When ``ORCHESTRATOR_API_KEY`` is set, require it for non-safe methods.

    Exempt: GET/HEAD/OPTIONS, ``/health``, OpenAPI docs, and static paths used by Swagger.
    """
    settings = get_settings()
    expected = (settings.orchestrator_api_key or "").strip()
    if not expected:
        return await call_next(request)

    method = request.method.upper()
    if method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    path = request.url.path
    if path == "/health" or path.startswith("/health/"):
        return await call_next(request)
    if path in ("/docs", "/redoc", "/openapi.json"):
        return await call_next(request)
    if path.startswith("/docs/"):
        return await call_next(request)

    got = _extract_api_key(request)
    if got != expected:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "invalid or missing API key",
                "hint": "Set X-API-Key or Authorization: Bearer <ORCHESTRATOR_API_KEY>",
            },
        )
    return await call_next(request)
