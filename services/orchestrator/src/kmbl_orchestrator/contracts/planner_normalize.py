"""Planner build_spec fallback so persistence does not depend on LLM filling every field."""

from __future__ import annotations

import copy
import logging
from typing import Any

_log = logging.getLogger(__name__)


def normalize_build_spec_for_persistence(build_spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Return a copy of ``build_spec`` with safe defaults for missing type/title.

    - ``type`` default ``generic``
    - ``title`` default ``Untitled Build``
    - Whitespace trimmed for string fields when present.

    Second return value lists which fields were defaulted (for metadata / logging).
    """
    out = copy.deepcopy(build_spec)
    normalized: list[str] = []

    t = out.get("type")
    if not isinstance(t, str) or not t.strip():
        out["type"] = "generic"
        normalized.append("type")
    else:
        out["type"] = t.strip()

    title = out.get("title")
    if not isinstance(title, str) or not title.strip():
        out["title"] = "Untitled Build"
        normalized.append("title")
    else:
        out["title"] = title.strip()

    if normalized:
        _log.warning(
            "planner build_spec normalized missing/empty fields: %s",
            normalized,
        )
    return out, normalized


def _trim_str(s: str, max_len: int) -> str:
    t = s.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _compact_identity_source_in_build_spec(bs: dict[str, Any]) -> dict[str, Any]:
    """Drop redundant long echoes of identity inside ``build_spec`` (identity_context already carries signals)."""
    iso = bs.get("identity_source")
    if not isinstance(iso, dict):
        return bs
    compact: dict[str, Any] = {}
    if isinstance(iso.get("url"), str):
        compact["url"] = _trim_str(iso["url"], 500)
    if isinstance(iso.get("profile_summary"), str):
        compact["profile_summary"] = _trim_str(iso["profile_summary"], 240)
    for key, max_n, max_item in (
        ("tone_keywords", 8, 48),
        ("aesthetic_keywords", 6, 48),
        ("palette_hints", 8, 24),
        ("image_refs", 8, 200),
        ("project_evidence", 10, 80),
        ("crawled_pages", 6, 220),
    ):
        v = iso.get(key)
        if isinstance(v, list):
            compact[key] = [_trim_str(str(x), max_item) for x in v[:max_n]]
    out = dict(bs)
    out["identity_source"] = compact
    return out


def compact_planner_wire_output(raw: dict[str, Any]) -> dict[str, Any]:
    """
    After a successful planner invocation, shrink verbose JSON so downstream roles receive a smaller
    ``build_spec`` and we avoid duplicating full crawl payloads inside it.

    Only caps list sizes and trims strings; required contract keys stay present.
    """
    out = copy.deepcopy(raw)
    bs = out.get("build_spec")
    if isinstance(bs, dict):
        out["build_spec"] = _compact_identity_source_in_build_spec(bs)

    sc = out.get("success_criteria")
    if isinstance(sc, list):
        out["success_criteria"] = [_trim_str(str(x), 360) for x in sc[:14]]

    et = out.get("evaluation_targets")
    if isinstance(et, list):
        out["evaluation_targets"] = [_trim_str(str(x), 360) for x in et[:18]]

    md = out.setdefault("_kmbl_planner_metadata", {})
    md["compact_wire_output"] = True
    return out
