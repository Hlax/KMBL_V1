"""Generator output and preview checks before build_candidate / staging_snapshot."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord
from kmbl_orchestrator.runtime.static_vertical_invariants import is_static_frontend_vertical

# Telemetry: generator returned planning-shaped JSON without shipping files (session_4-style failure).
PLANNER_DRIFT_CHECKLIST = "planner_drift_checklist_without_artifacts"


class StaticVerticalBundleRejected(ValueError):
    """Static vertical bundle validation failed; optional ``output_class`` for operator telemetry."""

    def __init__(self, message: str, *, output_class: str | None = None) -> None:
        super().__init__(message)
        self.output_class = output_class


def _static_vertical_planner_drift_class(output: dict[str, Any]) -> str | None:
    """
    Detect checklist/plan-only proposed_changes when no HTML bundle is present — models often
    confuse this role with the planner and emit checklist_steps instead of artifact_outputs.
    """
    ao = output.get("artifact_outputs")
    if isinstance(ao, list) and len(ao) > 0:
        return None
    pc = output.get("proposed_changes")
    if not isinstance(pc, dict) or not pc:
        return None
    keys = {str(k) for k in pc.keys() if pc.get(k) not in (None, [], {})}
    if not keys:
        return None
    planning_only = frozenset(
        {
            "checklist_steps",
            "plan_steps",
            "analysis_steps",
            "approach_notes",
            "design_rationale",
        }
    )
    if keys <= planning_only:
        return PLANNER_DRIFT_CHECKLIST
    if "checklist_steps" in keys:
        non_check = keys - {"checklist_steps", "notes", "summary"}
        if not non_check:
            return PLANNER_DRIFT_CHECKLIST
    return None


def _is_nonempty_proposed_changes(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, dict):
        return len(v) > 0
    if isinstance(v, list):
        return len(v) > 0
    return True


def _is_nonempty_updated_state(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, dict):
        return len(v) > 0
    return True


def _is_nonempty_artifact_outputs(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return len(v) > 0
    return True


def validate_generator_output_for_candidate(output: dict[str, Any]) -> None:
    """
    Ensure generator output is meaningful before ``build_candidate`` persistence.

    Raises ValueError on invalid shape or empty primary payload.
    Accepts ``html_block_v1`` artifacts in ``artifact_outputs`` as a valid form
    of non-empty output (incremental block amendments).
    Accepts ``contract_failure`` with ``code`` + ``message`` (structured decline; graph fails fast).
    """
    cf = output.get("contract_failure")
    if isinstance(cf, dict):
        code = cf.get("code")
        msg = cf.get("message")
        if isinstance(code, str) and code.strip() and isinstance(msg, str) and msg.strip():
            return

    pc = output.get("proposed_changes")
    ao = output.get("artifact_outputs")
    us = output.get("updated_state")

    # Check html_block_v1 artifacts separately so a block-only output is valid
    has_blocks = isinstance(ao, list) and any(
        isinstance(a, dict) and a.get("role") == "html_block_v1"
        for a in ao
    )

    if not (
        _is_nonempty_proposed_changes(pc)
        or _is_nonempty_artifact_outputs(ao)
        or _is_nonempty_updated_state(us)
        or has_blocks
    ):
        raise ValueError(
            "generator output must include at least one non-empty primary field "
            "(proposed_changes, artifact_outputs, updated_state) "
            "or at least one html_block_v1 artifact"
        )

    sr = output.get("sandbox_ref", None)
    if sr is not None and not isinstance(sr, str):
        raise ValueError("sandbox_ref must be string or null")

    pu = output.get("preview_url", None)
    if pu is not None and not isinstance(pu, str):
        raise ValueError("preview_url must be string or null")


def validate_static_frontend_bundle_requirement(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    output: dict[str, Any],
) -> None:
    """
    For identity static vertical, reject checklist-only / planning-only generator output.

    Requires at least one ``static_frontend_file_v1`` artifact that looks like HTML unless the model
    emitted a structured ``contract_failure``.
    """
    if not is_static_frontend_vertical(build_spec, event_input):
        return
    cf = output.get("contract_failure")
    if isinstance(cf, dict):
        code = cf.get("code")
        msg = cf.get("message")
        if isinstance(code, str) and code.strip() and isinstance(msg, str) and msg.strip():
            return

    ao = output.get("artifact_outputs")
    if not isinstance(ao, list) or not ao:
        drift = _static_vertical_planner_drift_class(output)
        msg = (
            "static_frontend_file_v1 vertical requires artifact_outputs with at least one file "
            "or a structured contract_failure with code and message"
        )
        if drift:
            msg += (
                f". Detected non-build output (checklist/plan only, no HTML): output_class={drift}. "
                "The planner already provided steps in build_spec — implement them as real "
                "static_frontend_file_v1 files, not checklist_steps."
            )
        raise StaticVerticalBundleRejected(msg, output_class=drift)

    has_html_bundle = False
    for a in ao:
        if not isinstance(a, dict):
            continue
        role = str(a.get("role") or "").strip().lower()
        path = str(a.get("file_path") or a.get("path") or "").lower()
        content = str(a.get("content") or "")
        if role != "static_frontend_file_v1":
            continue
        if path.endswith((".html", ".htm")):
            has_html_bundle = True
            break
        head = content[:1200].lower()
        if "<html" in head or "<!doctype html" in head:
            has_html_bundle = True
            break

    if not has_html_bundle:
        drift = _static_vertical_planner_drift_class(output)
        msg = (
            "static_frontend_file_v1 vertical requires at least one static_frontend_file_v1 "
            "artifact with HTML content or an .html/.htm path"
        )
        if drift:
            msg += f" (output_class={drift})"
        raise StaticVerticalBundleRejected(msg, output_class=drift)


def validate_preview_integrity(
    bc: BuildCandidateRecord,
    ev: EvaluationReportRecord,
) -> None:
    """
    Preview URL rules before staging_snapshot.

    - If ``preview_url`` is set on the candidate, it must be a non-empty http(s) URL.
    - If preview is absent but ``metrics_json.preview_required`` is true and evaluation
      passed, reject (cannot stage without preview).
    """
    pu = bc.preview_url
    if pu is not None:
        if not isinstance(pu, str) or not pu.strip():
            raise ValueError("preview_url must be null or a non-empty string")
        s = pu.strip()
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValueError("preview_url must start with http:// or https://")

    missing_preview = pu is None or (isinstance(pu, str) and not pu.strip())
    if missing_preview:
        if ev.metrics_json.get("preview_required") is True and ev.status == "pass":
            raise ValueError(
                "evaluation marked preview_required but build_candidate has no preview_url"
            )
