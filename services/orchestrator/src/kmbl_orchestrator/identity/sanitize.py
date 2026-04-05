"""Sanitize identity brief payloads before planner/generator/evaluator injection."""

from __future__ import annotations

import re
from typing import Any


_HEADINGS_CONTAMINATION = re.compile(
    r"\n+\s*Headings:\s*",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_headings_blob(s: str) -> str:
    """Remove scraped 'Headings: A | B | C' tails from display lines."""
    if not s or not isinstance(s, str):
        return ""
    t = s.strip()
    m = _HEADINGS_CONTAMINATION.search(t)
    if m:
        t = t[: m.start()].strip()
    return t


def _is_plausible_hex(h: str) -> bool:
    if not isinstance(h, str) or not h.startswith("#"):
        return False
    rest = h[1:].lower()
    return len(rest) in (3, 4, 6, 8) and all(c in "0123456789abcdef" for c in rest)


def sanitize_display_name(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = _strip_headings_blob(value)
    if not cleaned:
        return None
    # Collapse excessive internal newlines from scrapes
    cleaned = re.sub(r"[\r\n]+", " ", cleaned).strip()
    return cleaned[:240] if cleaned else None


def sanitize_must_mention_items(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items or []:
        if not isinstance(x, str):
            continue
        s = _strip_headings_blob(x)
        s = re.sub(r"\s+", " ", s).strip()[:120]
        if not s:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
        if len(out) >= 8:
            break
    return out


def sanitize_palette_hex(colors: list[Any]) -> list[str]:
    """Drop non-hex or implausible tokens (e.g. '#8211' length-4 typo)."""
    out: list[str] = []
    for c in colors or []:
        if not isinstance(c, str):
            continue
        t = c.strip()
        if _is_plausible_hex(t) and t not in out:
            out.append(t)
        if len(out) >= 8:
            break
    return out


def sanitize_identity_brief_payload(d: dict[str, Any] | None) -> dict[str, Any]:
    """Return a shallow-copied dict with cleaned identity fields (mutates copy only)."""
    if not isinstance(d, dict):
        return {}
    out = dict(d)
    dn = sanitize_display_name(out.get("display_name"))
    if dn is not None:
        out["display_name"] = dn
    else:
        out.pop("display_name", None)
    mm = sanitize_must_mention_items(out.get("must_mention") if isinstance(out.get("must_mention"), list) else [])
    if mm:
        out["must_mention"] = mm
    ph = sanitize_palette_hex(out.get("palette_hex") if isinstance(out.get("palette_hex"), list) else [])
    if ph:
        out["palette_hex"] = ph
    pp = sanitize_palette_hex(out.get("primary_palette") if isinstance(out.get("primary_palette"), list) else [])
    if pp:
        out["primary_palette"] = pp
    return out
