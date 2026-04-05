"""Assemble preview payload from a persisted build_candidate (no evaluation row required)."""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.domain import BuildCandidateRecord


def preview_payload_from_build_candidate(bc: BuildCandidateRecord) -> dict[str, Any]:
    """
    Shape expected by :func:`static_preview_assembly.resolve_static_preview_entry_path`
    and :func:`static_preview_assembly.assemble_static_preview_html` — mirrors the
    ``artifacts`` + ``metadata.working_state_patch`` slice of working_staging payloads.
    """
    wsp = dict(bc.working_state_patch_json or {})
    refs = list(bc.artifact_refs_json or [])
    return {
        "artifacts": {"artifact_refs": refs},
        "metadata": {"working_state_patch": wsp},
    }
