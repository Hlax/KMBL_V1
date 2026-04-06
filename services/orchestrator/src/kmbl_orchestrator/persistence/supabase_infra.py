"""Classify Supabase/PostgREST failures for clearer errors and safe degradation paths."""

from __future__ import annotations

import re
from typing import Any

# PostgREST / gateway messages that often indicate HTML or non-JSON upstream.
_NON_JSON_HINTS = (
    "json could not be generated",
    "could not be generated",
    "invalid json",
)


def _exc_chain(exc: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        cur = cur.__cause__
    return out


def _extract_postgrest_dict(exc: BaseException) -> dict[str, Any] | None:
    """Best-effort: ``postgrest.exceptions.APIError`` uses code/message/details/hint."""
    for e in _exc_chain(exc):
        code = getattr(e, "code", None)
        message = getattr(e, "message", None)
        details = getattr(e, "details", None)
        if code is not None or message is not None:
            return {
                "code": str(code) if code is not None else "",
                "message": str(message) if message is not None else "",
                "details": details,
                "hint": getattr(e, "hint", None),
            }
    return None


def _body_preview(text: str, max_len: int = 240) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _content_type_hint(exc: BaseException) -> str | None:
    """Best-effort from wrapped httpx/requests errors (no secrets)."""
    for e in _exc_chain(exc):
        h = getattr(e, "headers", None)
        if h is None:
            continue
        if isinstance(h, dict):
            ct = h.get("content-type") or h.get("Content-Type")
            if ct:
                return str(ct)[:120]
        get = getattr(h, "get", None)
        if callable(get):
            try:
                ct = get("content-type")  # type: ignore[misc]
                if ct:
                    return str(ct)[:120]
            except Exception:
                pass
    return None


def classify_supabase_exception(exc: BaseException) -> dict[str, Any]:
    """
    Return structured hints for logging and RunEvent payloads (no secrets).

    Keys: code, message, looks_like_html, looks_like_cloudflare, looks_like_non_json_upstream,
    body_preview, http_status_hint, content_type_hint
    """
    chain_s = " ".join(str(x).lower() for x in _exc_chain(exc))
    ct_hint = _content_type_hint(exc)
    pd = _extract_postgrest_dict(exc)
    code_s = str(pd.get("code", "")) if pd else ""
    msg_s = str(pd.get("message", "")) if pd else str(exc)
    details_raw = pd.get("details") if pd else None
    details_s = details_raw if isinstance(details_raw, str) else str(details_raw or "")

    looks_html = "<html" in details_s.lower() or "<!doctype" in details_s.lower()
    looks_cf = "cloudflare" in chain_s or "cloudflare" in details_s.lower()
    looks_non_json = looks_html or looks_cf or any(
        h in chain_s for h in _NON_JSON_HINTS
    )

    http_hint: str | None = None
    if code_s.isdigit():
        http_hint = code_s
    m = re.search(r"\b(\d{3})\b", msg_s)
    if http_hint is None and m:
        http_hint = m.group(1)

    preview = ""
    if details_s:
        preview = _body_preview(details_s, 200)
    elif msg_s:
        preview = _body_preview(msg_s, 200)

    return {
        "code": code_s,
        "message": msg_s[:500],
        "looks_like_html": looks_html,
        "looks_like_cloudflare": looks_cf,
        "looks_like_non_json_upstream": looks_non_json,
        "body_preview": preview,
        "http_status_hint": http_hint,
        "content_type_hint": ct_hint,
    }


def format_supabase_repository_error(
    op: str,
    table: str,
    exc: BaseException,
    **ctx: Any,
) -> str:
    """Human-readable single-line + hint for operators (used by SupabaseRepository._run)."""
    c = classify_supabase_exception(exc)
    pk = ctx.get("persistence_kind")
    pk_note = f"persistence_kind={pk}" if pk else None
    parts = [
        f"SupabaseRepository.{op}({table}) failed: {type(exc).__name__}: {c['message'][:400]}",
    ]
    if pk_note:
        parts.append(pk_note)
    if ctx:
        safe_ctx = {k: v for k, v in ctx.items() if k not in ("supabase_service_role_key", "key")}
        if safe_ctx:
            parts.append(f"context={safe_ctx}")
    if c["looks_like_non_json_upstream"]:
        parts.append(
            "hint=upstream_returned_non_json_response_check_SUPABASE_URL_points_to_rest_api_not_dashboard_or_proxy"
        )
    if c["looks_like_cloudflare"]:
        parts.append("hint=response_suggests_cloudflare_waf_or_wrong_host_not_postgrest_json")
    if c["http_status_hint"]:
        parts.append(f"http_status={c['http_status_hint']}")
    if c.get("content_type_hint"):
        parts.append(f"content_type={c['content_type_hint']}")
    if c["body_preview"]:
        parts.append(f"body_preview={c['body_preview'][:220]}")
    return " | ".join(parts)
