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
