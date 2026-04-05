"""Deterministic checks against static artifact text — planner-authored literal_success_checks."""

from __future__ import annotations

import re
from typing import Any

from kmbl_orchestrator.domain import EvaluationReportRecord


def collect_static_artifact_search_blob(build_candidate: dict[str, Any]) -> str:
    """
    Concatenate searchable text from generator build_candidate artifact_outputs.

    Mirrors the approach used for the 3D keyword guardrail in evaluator_node.
    """
    parts: list[str] = []
    for art in build_candidate.get("artifact_outputs") or []:
        if not isinstance(art, dict):
            continue
        role = str(art.get("role", ""))
        path = str(art.get("path", ""))
        content = art.get("content")
        c_str = content if isinstance(content, str) else ""
        parts.append(f"{role}\n{path}\n{c_str}")
    return "\n".join(parts).lower()


def collect_static_artifact_raw_concat(build_candidate: dict[str, Any]) -> str:
    """Concatenate raw artifact content (case preserved) for motion/script heuristics."""
    parts: list[str] = []
    for art in build_candidate.get("artifact_outputs") or []:
        if not isinstance(art, dict):
            continue
        c = art.get("content")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def cool_lane_artifact_has_motion_signal(raw_concat: str) -> bool:
    """
    Cheap cool-lane signal: CSS motion/animation or non-trivial inline script.

    Not a full parser — substring and script-body length heuristics only.
    """
    if not raw_concat.strip():
        return False
    low = raw_concat.lower()
    if "@keyframes" in low:
        return True
    if "animation:" in low:
        return True
    if "transition:" in low:
        return True
    for m in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", raw_concat, re.I):
        body = m.group(1)
        stripped = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", "", body)
        if len(re.sub(r"\s+", "", stripped)) >= 28:
            return True
    return False


def apply_cool_lane_motion_signal_gate(
    report: EvaluationReportRecord,
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    Cool lane only: require at least one motion/interaction signal in static artifacts.

    Skips when lane inactive, report not pass/partial, no artifact text, or generator
    declared ``cannot_fulfill`` (honest failure — no double penalty vs literals/ack).
    """
    from kmbl_orchestrator.runtime.cool_generation_lane import cool_generation_lane_active

    if not cool_generation_lane_active(event_input, build_spec):
        return report
    if report.status not in ("pass", "partial"):
        return report
    comp = build_candidate.get("_kmbl_compliance") or {}
    if comp.get("status") == "cannot_fulfill":
        return report

    raw = collect_static_artifact_raw_concat(build_candidate)
    if not raw.strip():
        return report

    if cool_lane_artifact_has_motion_signal(raw):
        m = dict(report.metrics_json or {})
        m["cool_lane_motion_signal_ok"] = True
        return report.model_copy(update={"metrics_json": m})

    issues = list(report.issues_json or [])
    issues.append({
        "severity": "high",
        "category": "cool_lane_motion_signal_missing",
        "message": (
            "Cool generation lane requires a motion/interaction signal: @keyframes, animation:, "
            "transition:, or a non-trivial <script> body (not comments-only)."
        ),
    })
    m = dict(report.metrics_json or {})
    m["cool_lane_motion_signal_missing"] = True
    return report.model_copy(
        update={
            "status": "partial",
            "issues_json": issues,
            "metrics_json": m,
        },
    )


def _normalize_literal_checks(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    needles: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            needles.append(item.strip().lower())
        elif isinstance(item, dict):
            n = item.get("needle")
            if isinstance(n, str) and n.strip():
                needles.append(n.strip().lower())
    return needles


def apply_literal_success_checks(
    report: EvaluationReportRecord,
    *,
    build_spec: dict[str, Any],
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    If build_spec.literal_success_checks is non-empty, require each needle as a
    case-insensitive substring of concatenated static artifact content.

    When any needle is missing, downgrade pass→partial (or keep partial) and
    record metrics so iteration can fix without relying on LLM evaluator generosity.
    """
    needles = _normalize_literal_checks(build_spec.get("literal_success_checks"))
    if not needles:
        return report
    if report.status not in ("pass", "partial"):
        return report

    blob = collect_static_artifact_search_blob(build_candidate)
    missing = [n for n in needles if n not in blob]

    m = dict(report.metrics_json or {})
    if not missing:
        m["literal_success_checks_passed"] = True
        m["literal_success_checks_count"] = len(needles)
        return report.model_copy(update={"metrics_json": m})

    issues = list(report.issues_json or [])
    for n in missing:
        issues.append({
            "severity": "high",
            "category": "literal_success_check_failed",
            "message": (
                f"Required literal_success_checks needle not found in static artifacts: {n!r}"
            ),
        })
    m["literal_success_checks_failed"] = missing
    m["literal_success_checks_passed"] = False
    return report.model_copy(
        update={
            "status": "partial",
            "issues_json": issues,
            "metrics_json": m,
        }
    )


__all__ = [
    "apply_cool_lane_motion_signal_gate",
    "apply_literal_success_checks",
    "collect_static_artifact_raw_concat",
    "collect_static_artifact_search_blob",
    "cool_lane_artifact_has_motion_signal",
]
