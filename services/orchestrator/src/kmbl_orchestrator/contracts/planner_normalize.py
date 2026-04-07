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
    - ``site_archetype`` — **never** defaulted to ``portfolio``; left empty when
      planner did not set it so generator uses a neutral / interactive-first bias.
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

    # Neutralize portfolio-shaped site_archetype: only keep it when the planner
    # explicitly chose it based on identity/instructions.  An empty or absent
    # archetype lets the generator adopt an app-like / interactive-first bias
    # instead of collapsing into hero/proof/story/cta portfolio templates.
    sa = out.get("site_archetype")
    if isinstance(sa, str):
        out["site_archetype"] = sa.strip() or None

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


def _compact_creative_brief(bs: dict[str, Any]) -> dict[str, Any]:
    cb = bs.get("creative_brief")
    if not isinstance(cb, dict):
        return bs
    out = dict(bs)
    compact: dict[str, Any] = {}
    for key, max_len in (
        ("mood", 240),
        ("direction_summary", 900),
        ("identity_interpretation", 900),
    ):
        v = cb.get(key)
        if isinstance(v, str):
            compact[key] = _trim_str(v, max_len)
    for k, v in cb.items():
        if k not in compact and isinstance(v, str):
            compact[k] = _trim_str(v, 360)
        elif k not in compact:
            compact[k] = v
    out["creative_brief"] = compact
    return out


def _compact_execution_contract_fields(bs: dict[str, Any]) -> dict[str, Any]:
    """Trim list sizes and strings so two-layer contract survives compact_planner_wire_output."""
    ec = bs.get("execution_contract")
    if not isinstance(ec, dict):
        return bs
    out = dict(bs)
    ec2: dict[str, Any] = dict(ec)
    for key, max_n, max_item in (
        ("selected_reference_patterns", 3, 80),
        ("pattern_rules", 14, 480),
        ("required_sections", 12, 64),
        ("required_interactions", 8, 120),
        ("required_visual_motifs", 10, 80),
        ("allowed_libraries", 8, 48),
        ("forbidden_fallback_patterns", 8, 80),
    ):
        v = ec2.get(key)
        if isinstance(v, list):
            ec2[key] = [_trim_str(str(x), max_item) for x in v[:max_n]]
    if isinstance(ec2.get("surface_type"), str):
        ec2["surface_type"] = _trim_str(ec2["surface_type"], 64)
    if isinstance(ec2.get("layout_mode"), str):
        ec2["layout_mode"] = _trim_str(ec2["layout_mode"], 64)
    if isinstance(ec2.get("lane"), str):
        ec2["lane"] = _trim_str(ec2["lane"], 48)
    if isinstance(ec2.get("escalation_lane"), str):
        ec2["escalation_lane"] = _trim_str(ec2["escalation_lane"], 48)
    out["execution_contract"] = ec2
    return out


# First graph iteration: avoid evaluator literal gates dominating before any artifact exists.
_FIRST_ITERATION_LITERAL_CHECKS_MAX = 8


def apply_first_iteration_literal_cap(
    build_spec: dict[str, Any],
    iteration_index: int,
) -> tuple[dict[str, Any], bool]:
    """Cap ``literal_success_checks`` length on iteration 0 to reduce over-constraint.

    Returns (possibly updated build_spec, True if capped).
    """
    if iteration_index != 0:
        return build_spec, False
    raw = build_spec.get("literal_success_checks")
    if not isinstance(raw, list) or len(raw) <= _FIRST_ITERATION_LITERAL_CHECKS_MAX:
        return build_spec, False
    out = dict(build_spec)
    out["literal_success_checks"] = list(raw[:_FIRST_ITERATION_LITERAL_CHECKS_MAX])
    meta = out.setdefault("_kmbl_iteration_literal_meta", {})
    if isinstance(meta, dict):
        meta["capped_from"] = len(raw)
        meta["capped_to"] = _FIRST_ITERATION_LITERAL_CHECKS_MAX
    return out, True


def _compact_literal_success_checks_in_build_spec(bs: dict[str, Any]) -> dict[str, Any]:
    raw = bs.get("literal_success_checks")
    if not isinstance(raw, list):
        return bs
    out = dict(bs)
    compact_list: list[Any] = []
    for item in raw[:24]:
        if isinstance(item, str):
            compact_list.append(_trim_str(item, 800))
        elif isinstance(item, dict):
            n = item.get("needle")
            if isinstance(n, str):
                compact_list.append({"needle": _trim_str(n, 800), **{k: v for k, v in item.items() if k != "needle"}})
            else:
                compact_list.append(item)
        else:
            compact_list.append(item)
    out["literal_success_checks"] = compact_list
    return out


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
        bs = _compact_identity_source_in_build_spec(bs)
        bs = _compact_creative_brief(bs)
        bs = _compact_execution_contract_fields(bs)
        bs = _compact_literal_success_checks_in_build_spec(bs)
        out["build_spec"] = bs

    sc = out.get("success_criteria")
    if isinstance(sc, list):
        out["success_criteria"] = [_trim_str(str(x), 360) for x in sc[:14]]

    et = out.get("evaluation_targets")
    if isinstance(et, list):
        out["evaluation_targets"] = [_trim_str(str(x), 360) for x in et[:18]]

    md = out.setdefault("_kmbl_planner_metadata", {})
    md["compact_wire_output"] = True
    return out
