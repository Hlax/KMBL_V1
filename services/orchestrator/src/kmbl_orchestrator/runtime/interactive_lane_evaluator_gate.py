"""
Deterministic metrics and light status adjustment for ``interactive_frontend_app_v1`` evaluations.
"""

from __future__ import annotations

import re
from typing import Any

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.literal_success_gate import collect_static_artifact_raw_concat
from kmbl_orchestrator.runtime.static_vertical_invariants import is_interactive_frontend_vertical
from kmbl_orchestrator.staging.integrity import scan_interactive_bundle_preview_risks


# Event / DOM hooks — not exhaustive; enough to separate "static gimmick" from wired behavior.
_INTERACTION_SIGNAL_RE = re.compile(
    r"addEventListener\s*\(|\.on\s*\(\s*['\"]click|onclick\s*=|onchange\s*=|oninput\s*=|"
    r"onkeydown\s*=|onkeyup\s*=|pointerdown|touchstart|preventDefault\s*\(|"
    r"requestAnimationFrame\s*\(",
    re.IGNORECASE,
)

_AFFORDANCE_RE = re.compile(
    r"<button\b|<input\b[^>]*\btype\s*=\s*['\"]?(?:button|submit|range|checkbox)",
    re.IGNORECASE,
)

_CANVAS_OR_WEBGL_RE = re.compile(
    r"<canvas\b|getContext\s*\(\s*['\"]webgl|three\.|THREE\.",
    re.IGNORECASE,
)


def _planned_required_interactions(build_spec: dict[str, Any]) -> int:
    ec = build_spec.get("execution_contract")
    if not isinstance(ec, dict):
        return 0
    ri = ec.get("required_interactions")
    if not isinstance(ri, list):
        return 0
    n = 0
    for x in ri:
        if isinstance(x, dict) and (x.get("id") or x.get("mechanism")):
            n += 1
        elif isinstance(x, str) and x.strip():
            n += 1
    return n


def _html_blob_for_affordances(build_candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for art in build_candidate.get("artifact_outputs") or []:
        if not isinstance(art, dict):
            continue
        path = str(art.get("file_path") or art.get("path") or "").lower()
        c = art.get("content")
        if not isinstance(c, str) or not c.strip():
            continue
        head = c[:2000].lower()
        if path.endswith((".html", ".htm")) or "<html" in head or "<!doctype" in head:
            parts.append(c)
    return "\n".join(parts)


def apply_interactive_lane_evaluator_gate(
    report: EvaluationReportRecord,
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    Merge deterministic ``interactive_lane_metrics``; optionally downgrade ``pass`` when evidence gaps
    or preview-risky module patterns conflict with a lenient LLM verdict.
    """
    if not is_interactive_frontend_vertical(build_spec, event_input):
        return report

    raw_text = collect_static_artifact_raw_concat(build_candidate)
    signal_matches = len(_INTERACTION_SIGNAL_RE.findall(raw_text))
    html_blob = _html_blob_for_affordances(build_candidate)
    affordance_matches = len(_AFFORDANCE_RE.findall(html_blob)) if html_blob else 0
    canvas_hits = len(_CANVAS_OR_WEBGL_RE.findall(raw_text))

    ao = build_candidate.get("artifact_outputs")
    mod_risks = scan_interactive_bundle_preview_risks(ao if isinstance(ao, list) else [])
    mod_risk_count = len(mod_risks)

    planned = _planned_required_interactions(build_spec)
    evidence_ok = signal_matches > 0 or canvas_hits > 0
    hollow_controls = affordance_matches > 0 and signal_matches == 0 and canvas_hits == 0

    m = dict(report.metrics_json or {})
    m["interactive_lane_metrics"] = {
        "planned_required_interactions": planned,
        "js_dom_signal_hits": signal_matches,
        "html_interactive_affordance_hits": affordance_matches,
        "canvas_or_webgl_hint_hits": canvas_hits,
        "relative_module_preview_risks": mod_risk_count,
        "interactive_evidence_ok": bool(evidence_ok),
        "hollow_control_affordances_without_js": bool(hollow_controls),
    }

    issues = list(report.issues_json or [])
    status = report.status
    summary = (report.summary or "").strip()

    def _has_code(c: str) -> bool:
        for it in issues:
            if isinstance(it, dict) and it.get("code") == c:
                return True
        return False

    new_issues: list[dict[str, Any]] = []

    if planned > 0 and not evidence_ok and status in ("pass", "partial"):
        if not _has_code("interactive_lane_evidence_gap"):
            new_issues.append(
                {
                    "severity": "high",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_evidence_gap",
                    "message": (
                        f"build_spec.execution_contract lists {planned} required interaction(s) but "
                        "artifact text shows no addEventListener/onclick/canvas/WebGL hooks — "
                        "verify real interactivity or adjust the plan."
                    ),
                }
            )

    if hollow_controls and status in ("pass", "partial"):
        if not _has_code("interactive_lane_hollow_affordances"):
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_hollow_affordances",
                    "message": (
                        "HTML shows interactive affordances (buttons/inputs) but no JS event hooks "
                        "were found in artifacts — likely a static gimmick for this lane."
                    ),
                }
            )

    if mod_risk_count > 0 and status in ("pass", "partial"):
        if not _has_code("interactive_lane_module_preview_risk"):
            new_issues.append(
                {
                    "severity": "medium",
                    "category": "interactive_lane_deterministic",
                    "code": "interactive_lane_module_preview_risk",
                    "message": (
                        "Relative ES module imports detected in JS artifacts — preview assembly "
                        "does not resolve cross-file module graphs; expect broken runtime unless refactored."
                    ),
                }
            )

    if new_issues:
        issues = issues + new_issues
        if status == "pass":
            status = "partial"
            suffix = "[Adjusted: pass→partial — interactive lane deterministic checks.]"
            if suffix not in summary:
                summary = f"{summary} {suffix}".strip() if summary else suffix

    return report.model_copy(
        update={
            "status": status,
            "summary": summary,
            "issues_json": issues,
            "metrics_json": m,
        }
    )
