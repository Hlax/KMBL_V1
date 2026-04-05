"""HTTP client for the local KMBL Playwright wrapper (compact JSON)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from kmbl_orchestrator.config import Settings, get_settings

_log = logging.getLogger(__name__)


def visit_page_via_wrapper(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """POST /visit to the wrapper; returns JSON dict (always includes ``requested_url`` on parse success)."""
    settings = settings or get_settings()
    base = (settings.kmbl_playwright_wrapper_url or "").strip().rstrip("/")
    if not base:
        return {
            "requested_url": str(payload.get("url", "")),
            "status": "error",
            "error": "kmbl_playwright_wrapper_url not configured",
            "timing_ms": 0,
        }

    url = f"{base}/visit"
    timeout = float(settings.kmbl_playwright_http_timeout_sec)
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                return {
                    "requested_url": str(payload.get("url", "")),
                    "status": "error",
                    "error": "wrapper returned non-object JSON",
                    "timing_ms": 0,
                }
            return data
    except httpx.HTTPStatusError as exc:
        _log.debug("playwright wrapper HTTP error: %s", exc)
        return {
            "requested_url": str(payload.get("url", "")),
            "status": "error",
            "error": f"http_{exc.response.status_code}",
            "timing_ms": 0,
        }
    except Exception as exc:
        _log.debug("playwright wrapper request failed: %s", exc)
        return {
            "requested_url": str(payload.get("url", "")),
            "status": "error",
            "error": str(exc)[:300],
            "timing_ms": 0,
        }


def wrapper_payload_to_fetch_parts(
    data: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Map wrapper JSON to fields suitable for ``record_page_visit`` / summaries."""
    ok = data.get("status") == "ok" and not data.get("error")
    traits = data.get("traits") if isinstance(data.get("traits"), dict) else {}
    design = traits.get("design_signals") if isinstance(traits, dict) else []
    tone = traits.get("tone_keywords") if isinstance(traits, dict) else []
    if not isinstance(design, list):
        design = []
    if not isinstance(tone, list):
        tone = []
    links = data.get("discovered_links") if isinstance(data.get("discovered_links"), list) else []
    return ok, {
        "summary": (data.get("summary") or "")[:300],
        "title": data.get("page_title") or "",
        "description": data.get("meta_description") or "",
        "discovered_links": [str(x) for x in links if isinstance(x, str)],
        "design_signals": [str(x) for x in design[:10]],
        "tone_keywords": [str(x) for x in tone[:8]],
    }
