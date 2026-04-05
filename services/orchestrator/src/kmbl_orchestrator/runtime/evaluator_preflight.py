"""Skip evaluator LLM when the build candidate cannot be meaningfully scored."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.static_vertical_invariants import is_static_frontend_vertical


def should_skip_evaluator_llm(
    build_candidate: dict[str, Any],
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> tuple[bool, str]:
    """
    Return (True, reason) when OpenClaw evaluator should not run (deterministic report only).

    Static vertical with no HTML artifacts and no live preview URL is unevaluable.
    """
    if not is_static_frontend_vertical(build_spec, event_input):
        return False, ""

    ao = build_candidate.get("artifact_outputs")
    if isinstance(ao, list) and ao:
        if _static_bundle_has_html(ao):
            return False, ""
    preview = build_candidate.get("preview_url")
    if isinstance(preview, str) and preview.strip().lower().startswith("http"):
        return False, ""

    if ao is None or (isinstance(ao, list) and len(ao) == 0):
        return True, "no_artifact_outputs_for_static_vertical"
    return True, "no_html_static_bundle_and_no_preview_url"


def _static_bundle_has_html(artifacts: list[Any]) -> bool:
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        role = str(a.get("role") or "").strip().lower()
        path = str(a.get("file_path") or a.get("path") or "").lower()
        content = str(a.get("content") or "")
        if role != "static_frontend_file_v1":
            continue
        if path.endswith((".html", ".htm")):
            return True
        head = content[:1200].lower()
        if "<html" in head or "<!doctype html" in head:
            return True
    return False


def synthetic_skipped_evaluator_raw(reason: str) -> dict[str, Any]:
    """Deterministic evaluator-shaped JSON when the LLM is not invoked."""
    return {
        "status": "partial",
        "summary": (
            "Evaluator LLM was not invoked: the generator did not produce an evaluable "
            "static frontend bundle (no HTML artifacts and no preview URL)."
        ),
        "issues": [
            {
                "severity": "high",
                "category": "evaluator_skipped",
                "message": reason,
            }
        ],
        "metrics": {
            "evaluator_skipped": True,
            "evaluator_skip_reason": reason,
        },
        "artifacts": [],
    }
