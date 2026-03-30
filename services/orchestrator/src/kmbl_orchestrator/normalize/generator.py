"""Generator raw output → build_candidate record (docs/07 §4.4, §1.9)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.contracts.gallery_image_artifact_v1 import (
    normalize_gallery_artifact_outputs_list,
)
from kmbl_orchestrator.contracts.ui_gallery_strip_v1 import (
    normalize_ui_gallery_strip_v1_in_patch,
    resolve_gallery_artifact_refs_in_patch,
)
from kmbl_orchestrator.domain import BuildCandidateRecord


def normalize_generator_output(
    raw: dict[str, Any],
    *,
    thread_id: UUID,
    graph_run_id: UUID,
    generator_invocation_id: UUID,
    build_spec_id: UUID,
) -> BuildCandidateRecord:
    """Map KiloClaw generator JSON into persisted build_candidate columns."""
    candidate_id = uuid4()
    artifacts = normalize_gallery_artifact_outputs_list(raw.get("artifact_outputs"))
    patch = raw.get("updated_state") or raw.get("proposed_changes")
    if not isinstance(patch, dict):
        patch = {}
    patch = resolve_gallery_artifact_refs_in_patch(patch, artifacts)
    patch = normalize_ui_gallery_strip_v1_in_patch(patch)
    sandbox = raw.get("sandbox_ref")
    preview = raw.get("preview_url")
    return BuildCandidateRecord(
        build_candidate_id=candidate_id,
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        generator_invocation_id=generator_invocation_id,
        build_spec_id=build_spec_id,
        candidate_kind="habitat",
        working_state_patch_json=patch,
        artifact_refs_json=artifacts,
        sandbox_ref=str(sandbox) if sandbox is not None else None,
        preview_url=str(preview) if preview is not None else None,
        status="generated",
    )
