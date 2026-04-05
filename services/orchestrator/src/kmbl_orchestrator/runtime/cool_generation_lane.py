"""First-class cool generation lane: execution presets, compliance metadata, generator hints."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from kmbl_orchestrator.domain import EvaluationReportRecord

_log = logging.getLogger(__name__)

# execution_acknowledgment.status — generator vocabulary (case-insensitive in annotate)
EXECUTION_ACKNOWLEDGMENT_STATUSES: frozenset[str] = frozenset(
    ("executed", "downgraded", "cannot_fulfill"),
)

_LITERAL_PREVIEW_MAX_ITEMS = 10
_LITERAL_PREVIEW_MAX_CHARS = 120

COOL_GENERATION_LANE_V1 = "cool_generation_v1"

_DEFAULT_REFERENCE_PATTERNS: tuple[str, ...] = (
    "portrait_led_editorial_hero",
    "oversized_typography_structure",
    "restrained_layered_depth_or_motion",
)

_DEFAULT_PATTERN_RULES: tuple[str, ...] = (
    "Hero must use at least one real identity image at large scale (not a tiny thumbnail).",
    "At least one display-scale headline (visual hierarchy, not body-sized only).",
    "Include one non-placeholder motion or interaction: CSS scroll-linked, reduced-motion "
    "fallback, or JS (no empty script block).",
    "Use identity palette or CSS variables derived from identity_brief.palette_hex when present.",
    "Add class `kmbl-cool-hero` on the primary hero root element.",
    'Include marker attribute data-kmbl-cool-lane="1" on the <body> or root layout element.',
)


def cool_generation_lane_active(
    event_input: dict[str, Any],
    build_spec: dict[str, Any],
) -> bool:
    """True when this run should use cool-generation presets and compliance rules."""
    ec = build_spec.get("execution_contract")
    if isinstance(ec, dict) and ec.get("lane") == COOL_GENERATION_LANE_V1:
        return True
    if event_input.get("cool_generation_lane") is True:
        return True
    return False


def reference_pattern_to_literal_token(pattern_label: str) -> str:
    """
    Stable grep-able token for a selected reference pattern label.

    Example: ``portrait_led_editorial_hero`` → ``kmbl-pattern-portrait-led-editorial-hero``.
    """
    s = (pattern_label or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return ""
    return f"kmbl-pattern-{s}"


def literal_success_checks_preview_strings(
    literal_success_checks: Any,
    *,
    max_items: int = _LITERAL_PREVIEW_MAX_ITEMS,
    max_chars: int = _LITERAL_PREVIEW_MAX_CHARS,
) -> list[str]:
    """First N literal needles, each truncated for compact generator payload."""
    if not isinstance(literal_success_checks, list):
        return []
    out: list[str] = []
    for item in literal_success_checks[:max_items]:
        if isinstance(item, str) and item.strip():
            s = item.strip()
        elif isinstance(item, dict) and isinstance(item.get("needle"), str) and item["needle"].strip():
            s = item["needle"].strip()
        else:
            continue
        if len(s) > max_chars:
            s = s[: max_chars - 1] + "…"
        out.append(s)
    return out


def summarize_execution_contract_for_generator(build_spec: dict[str, Any]) -> dict[str, Any]:
    """Compact obligations for generator payload (avoid resending full identity blobs)."""
    if not isinstance(build_spec, dict):
        return {}
    ec = build_spec.get("execution_contract")
    if not isinstance(ec, dict):
        ec = {}
    lsc = build_spec.get("literal_success_checks")
    n_lit = len(lsc) if isinstance(lsc, list) else 0
    cb = build_spec.get("creative_brief")
    return {
        "lane": ec.get("lane"),
        "surface_type": ec.get("surface_type"),
        "layout_mode": ec.get("layout_mode"),
        "selected_reference_patterns": ec.get("selected_reference_patterns"),
        "pattern_rules": ec.get("pattern_rules"),
        "required_sections": ec.get("required_sections"),
        "literal_success_checks_count": n_lit,
        "literal_success_checks_preview": literal_success_checks_preview_strings(lsc),
        "creative_brief_mood": (cb.get("mood") if isinstance(cb, dict) else None),
    }


def apply_cool_generation_lane_presets(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Merge default execution obligations and literal needles when the lane is active.

    Preserves planner-authored fields when already strong; fills gaps only.
    """
    if not cool_generation_lane_active(event_input, build_spec):
        return build_spec, {"applied": False}

    bs = copy.deepcopy(build_spec)
    ec = bs.get("execution_contract")
    if not isinstance(ec, dict):
        ec = {}
        bs["execution_contract"] = ec
    ec.setdefault("lane", COOL_GENERATION_LANE_V1)
    ec.setdefault("surface_type", "single_page_static")
    ec.setdefault("layout_mode", "editorial_split")
    ec.setdefault("required_sections", ["hero", "proof_or_work", "contact_or_cta"])

    spr = ec.get("selected_reference_patterns")
    if not (isinstance(spr, list) and len(spr) >= 1):
        ec["selected_reference_patterns"] = list(_DEFAULT_REFERENCE_PATTERNS[:3])
    else:
        ec["selected_reference_patterns"] = [str(x) for x in spr[:3]]

    pr = ec.get("pattern_rules")
    if not (isinstance(pr, list) and len(pr) >= 2):
        ec["pattern_rules"] = list(_DEFAULT_PATTERN_RULES)
    else:
        merged: list[str] = []
        seen: set[str] = set()
        for x in list(pr) + list(_DEFAULT_PATTERN_RULES):
            s = str(x).strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            merged.append(s)
        ec["pattern_rules"] = merged[:14]

    # Literal needles: planner + lane markers + first identity image URL when available
    planner_needles: list[Any] = []
    lsc = bs.get("literal_success_checks")
    if isinstance(lsc, list):
        planner_needles = list(lsc)

    extra: list[str] = []
    identity_image_needle = False
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    imgs = ib.get("image_refs")
    if isinstance(imgs, list) and imgs:
        first = str(imgs[0]).strip()
        if first.lower().startswith("http"):
            extra.append(first.lower())
            identity_image_needle = True
    elif isinstance(structured_identity, dict) and not extra:
        _log.debug("cool_generation_lane: no image_refs on identity_brief; markers only")

    # Grep-able obligations for each selected reference pattern (1–3).
    spr_final = ec.get("selected_reference_patterns") or []
    if isinstance(spr_final, list):
        for pat in spr_final[:3]:
            tok = reference_pattern_to_literal_token(str(pat))
            if tok:
                extra.append(tok)

    extra.extend(['data-kmbl-cool-lane="1"', "kmbl-cool-hero"])

    merged_lit = _dedupe_literal_needles(planner_needles, extra)
    bs["literal_success_checks"] = merged_lit[:24]

    cb = bs.get("creative_brief")
    if not isinstance(cb, dict) or not cb.get("mood"):
        bs["creative_brief"] = {
            **(cb if isinstance(cb, dict) else {}),
            "mood": "distinctive identity-forward editorial",
            "direction_summary": (
                (cb.get("direction_summary") if isinstance(cb, dict) else None)
                or "Cool generation lane: real hero imagery, typographic hierarchy, non-generic motion."
            ),
        }

    meta = {
        "applied": True,
        "lane": COOL_GENERATION_LANE_V1,
        "literal_needles_count": len(bs["literal_success_checks"]),
        "identity_image_needle": identity_image_needle,
    }
    _log.info(
        "cool_generation_lane presets merged literal_needles=%s patterns=%d",
        meta["literal_needles_count"],
        len(ec.get("selected_reference_patterns") or []),
    )
    return bs, meta


def _dedupe_literal_needles(planner_part: list[Any], extras: list[str]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []

    def _key(item: Any) -> str | None:
        if isinstance(item, str) and item.strip():
            return item.strip().lower()
        if isinstance(item, dict):
            n = item.get("needle")
            if isinstance(n, str) and n.strip():
                return n.strip().lower()
        return None

    for item in planner_part:
        k = _key(item)
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    for s in extras:
        sl = s.strip().lower()
        if sl and sl not in seen:
            seen.add(sl)
            out.append(s)
    return out


def annotate_cool_lane_generator_compliance(
    raw: dict[str, Any],
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> dict[str, Any]:
    """
    Tag generator JSON when cool lane is active but the model did not report execution status.

    Structured failure path (contract_failure) is left untouched.
    """
    if not cool_generation_lane_active(event_input, build_spec):
        return raw
    cf = raw.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and str(cf.get("code", "")).strip():
        return raw

    out = dict(raw)
    ea = out.get("execution_acknowledgment")
    if isinstance(ea, dict):
        status = ea.get("status")
        if isinstance(status, str) and status.strip():
            st = status.strip().lower()
            if st in EXECUTION_ACKNOWLEDGMENT_STATUSES:
                out["_kmbl_compliance"] = {
                    "cool_generation_lane": True,
                    "acknowledged": True,
                    "status": st,
                    "ambition_downgrades": ea.get("ambition_downgrades"),
                    "rules_attempted": ea.get("rules_attempted"),
                    "rules_skipped": ea.get("rules_skipped"),
                }
                return out
            out["_kmbl_compliance"] = {
                "cool_generation_lane": True,
                "invalid_execution_acknowledgment_status": True,
                "reason": (
                    "execution_acknowledgment.status must be one of: "
                    + ", ".join(sorted(EXECUTION_ACKNOWLEDGMENT_STATUSES))
                ),
                "received_status": status.strip(),
            }
            return out

    out["_kmbl_compliance"] = {
        "cool_generation_lane": True,
        "silent_acknowledgment": True,
        "reason": "execution_acknowledgment missing or status empty for cool_generation_v1 lane",
    }
    return out


def apply_cool_lane_execution_acknowledgment_gates(
    report: EvaluationReportRecord,
    *,
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    Downgrade pass→partial when cool lane acknowledgment is missing, silent, or invalid.

    Literal substring checks still apply separately.
    """
    comp = build_candidate.get("_kmbl_compliance") or {}
    if report.status not in ("pass", "partial"):
        return report

    if comp.get("silent_acknowledgment"):
        issues = list(report.issues_json or [])
        issues.append({
            "severity": "medium",
            "category": "cool_lane_silent_acknowledgment",
            "message": (
                comp.get("reason")
                or "Cool generation lane requires execution_acknowledgment.status when emitting artifacts."
            ),
        })
        m = dict(report.metrics_json or {})
        m["cool_lane_silent_acknowledgment"] = True
        return report.model_copy(
            update={
                "status": "partial",
                "issues_json": issues,
                "metrics_json": m,
            },
        )

    if comp.get("invalid_execution_acknowledgment_status"):
        issues = list(report.issues_json or [])
        issues.append({
            "severity": "medium",
            "category": "cool_lane_invalid_execution_acknowledgment_status",
            "message": comp.get("reason")
            or "execution_acknowledgment.status must be executed, downgraded, or cannot_fulfill.",
        })
        m = dict(report.metrics_json or {})
        m["cool_lane_invalid_execution_acknowledgment_status"] = True
        if comp.get("received_status") is not None:
            m["cool_lane_received_acknowledgment_status"] = comp.get("received_status")
        return report.model_copy(
            update={
                "status": "partial",
                "issues_json": issues,
                "metrics_json": m,
            },
        )

    return report


def apply_cool_lane_silent_acknowledgment_gate(
    report: EvaluationReportRecord,
    *,
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """Backward-compatible alias for ``apply_cool_lane_execution_acknowledgment_gates``."""
    return apply_cool_lane_execution_acknowledgment_gates(
        report,
        build_candidate=build_candidate,
    )


__all__ = [
    "COOL_GENERATION_LANE_V1",
    "EXECUTION_ACKNOWLEDGMENT_STATUSES",
    "annotate_cool_lane_generator_compliance",
    "apply_cool_generation_lane_presets",
    "apply_cool_lane_execution_acknowledgment_gates",
    "apply_cool_lane_silent_acknowledgment_gate",
    "cool_generation_lane_active",
    "literal_success_checks_preview_strings",
    "reference_pattern_to_literal_token",
    "summarize_execution_contract_for_generator",
]
