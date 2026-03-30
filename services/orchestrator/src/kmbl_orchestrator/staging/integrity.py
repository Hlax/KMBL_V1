"""Generator output and preview checks before build_candidate / staging_snapshot."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord


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
    """
    pc = output.get("proposed_changes")
    ao = output.get("artifact_outputs")
    us = output.get("updated_state")

    if not (
        _is_nonempty_proposed_changes(pc)
        or _is_nonempty_artifact_outputs(ao)
        or _is_nonempty_updated_state(us)
    ):
        raise ValueError(
            "generator output must include at least one non-empty primary field "
            "(proposed_changes, artifact_outputs, updated_state)"
        )

    sr = output.get("sandbox_ref", None)
    if sr is not None and not isinstance(sr, str):
        raise ValueError("sandbox_ref must be string or null")

    pu = output.get("preview_url", None)
    if pu is not None and not isinstance(pu, str):
        raise ValueError("preview_url must be string or null")


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
