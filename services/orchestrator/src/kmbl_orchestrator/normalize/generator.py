"""Generator raw output → build_candidate record (docs/07 §4.4, §1.9)."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.contracts.frontend_artifact_roles import (
    FRONTEND_FILE_ARTIFACT_ROLES,
    is_frontend_file_artifact_role,
)
from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
    normalize_combined_artifact_outputs_list,
)
from kmbl_orchestrator.contracts.static_frontend_patch_v1 import (
    normalize_static_frontend_preview_in_patch,
)
from kmbl_orchestrator.contracts.ui_gallery_strip_v1 import (
    normalize_ui_gallery_strip_v1_in_patch,
    resolve_gallery_artifact_refs_in_patch,
)
from kmbl_orchestrator.domain import BuildCandidateRecord
from kmbl_orchestrator.runtime.generator_wire_compact_v1 import (
    compact_generator_output_payload_for_persistence,
)

_log = logging.getLogger(__name__)


def _default_promotion_role(raw: dict[str, Any]) -> str:
    """Orchestrator may set ``_kmbl_frontend_artifact_role`` after workspace ingest."""
    r = raw.get("_kmbl_frontend_artifact_role")
    if isinstance(r, str) and r in FRONTEND_FILE_ARTIFACT_ROLES:
        return r
    return "static_frontend_file_v1"


class HabitatAssemblyError(Exception):
    """Raised when habitat assembly fails with classification."""
    
    def __init__(self, message: str, *, error_type: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


def _assemble_habitat_if_present(
    artifacts: list[Any],
    *,
    graph_run_id: UUID | None = None,
    thread_id: UUID | None = None,
    identity_id: UUID | None = None,
    enable_image_generation: bool = False,
) -> list[Any]:
    """
    Check for habitat_manifest_v2 in artifacts and assemble if found.

    Returns the artifacts list with habitat manifest replaced by assembled files.
    On failure, marks the manifest with assembly_failed flag and returns original artifacts.
    
    Args:
        artifacts: List of artifacts to process
        graph_run_id: Optional graph run ID for image generation
        thread_id: Optional thread ID for image generation
        identity_id: Optional identity ID for image generation context
        enable_image_generation: Whether to generate images (can be slow/expensive)
    """
    from pydantic import ValidationError
    
    try:
        from kmbl_orchestrator.contracts.habitat_manifest_v2 import extract_habitat_manifest
        from kmbl_orchestrator.habitat.assembler import (
            assemble_habitat,
            merge_assembled_artifacts,
            AssemblyContext,
        )

        manifest = extract_habitat_manifest(artifacts)
        if manifest is None:
            return artifacts

        _log.info(
            "habitat_manifest_v2 found: slug=%s pages=%d framework=%s libraries=%s",
            manifest.slug,
            len(manifest.pages),
            manifest.framework.base if manifest.framework else None,
            [lib.name for lib in manifest.libraries] if manifest.libraries else [],
        )

        # Build assembly context with optional image generation
        context = AssemblyContext(
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            identity_id=identity_id,
        )
        
        if enable_image_generation and graph_run_id and thread_id:
            from kmbl_orchestrator.providers.image.service import get_image_service
            context.image_service = get_image_service()
            _log.info("habitat_assembly: image generation enabled")

        assembled = assemble_habitat(manifest, context)

        _log.info(
            "habitat_assembly_complete: slug=%s assembled_files=%d",
            manifest.slug,
            len(assembled),
        )

        return merge_assembled_artifacts(artifacts, assembled)

    except ValidationError as exc:
        # Manifest validation failed - schema issue
        _log.warning(
            "habitat_assembly_failed: error_type=validation_error errors=%s",
            exc.error_count(),
        )
        # Mark manifest artifact as having failed assembly
        return _mark_habitat_assembly_failed(artifacts, "validation_error", str(exc))
        
    except ImportError as exc:
        # Missing dependencies
        _log.warning(
            "habitat_assembly_failed: error_type=import_error module=%s",
            exc.name,
        )
        return _mark_habitat_assembly_failed(artifacts, "import_error", str(exc))
        
    except Exception as exc:
        # Assembly I/O or unexpected errors
        error_type = "assembly_error" if "assemble" in str(type(exc).__module__).lower() else "unexpected_error"
        _log.warning(
            "habitat_assembly_failed: error_type=%s exc_type=%s message=%s",
            error_type,
            type(exc).__name__,
            str(exc)[:200],
        )
        return _mark_habitat_assembly_failed(artifacts, error_type, str(exc))


def _mark_habitat_assembly_failed(
    artifacts: list[Any], 
    error_type: str, 
    error_message: str
) -> list[Any]:
    """
    Mark habitat_manifest_v2 artifacts with assembly_failed flag.
    
    This allows downstream code to detect that assembly was attempted but failed.
    """
    result: list[Any] = []
    for artifact in artifacts:
        if isinstance(artifact, dict) and artifact.get("role") == "habitat_manifest_v2":
            # Add assembly failure marker
            marked = dict(artifact)
            marked["_assembly_failed"] = True
            marked["_assembly_error_type"] = error_type
            marked["_assembly_error_message"] = error_message[:500]
            result.append(marked)
        else:
            result.append(artifact)
    return result

def _is_valid_static_frontend_path(path: str) -> bool:
    """
    Validate path using the same rules as StaticFrontendFileArtifactV1.
    
    Path must:
    - Start with "component/"
    - Not contain ".." or "//" or start with "/"
    - Match the segment pattern for valid component paths
    - End with .html, .css, or .js
    """
    if not path or not isinstance(path, str):
        return False
    # Same validation as StaticFrontendFileArtifactV1
    if ".." in path or path.startswith("/") or "//" in path:
        return False
    if not path.startswith("component/"):
        return False
    # Use the same regex pattern as StaticFrontendFileArtifactV1
    # ^component/(?:[a-zA-Z0-9][a-zA-Z0-9_-]*/)*[a-zA-Z0-9][a-zA-Z0-9_-]*\.(html|css|js)$
    _path_re = re.compile(
        r"^component/(?:[a-zA-Z0-9][a-zA-Z0-9_-]*/)*[a-zA-Z0-9][a-zA-Z0-9_-]*\.(html|css|js)$"
    )
    return bool(_path_re.match(path))


def _recover_static_files_from_proposed_changes(
    proposed_changes: Any,
    existing_artifacts: list[Any],
    *,
    promotion_role: str = "static_frontend_file_v1",
) -> list[Any]:
    """
    Safety net: if artifact_outputs has no static_frontend_file_v1 rows but
    proposed_changes contains file entries matching component/**/*.{html,css,js}
    with content, promote them into static_frontend_file_v1 artifacts.

    This matches the contract described in agent docs: KMBL will attempt
    recovery promotion as a safety net, not the intended path.
    
    Uses the same path validation as StaticFrontendFileArtifactV1 for consistency.
    """
    has_frontend = any(
        isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role"))
        for a in existing_artifacts
    )
    if has_frontend:
        return existing_artifacts

    if not isinstance(proposed_changes, (dict, list)):
        return existing_artifacts

    files_to_promote: list[dict[str, Any]] = []
    candidates: list[Any] = []
    if isinstance(proposed_changes, dict):
        candidates = proposed_changes.get("files", [])
        if not isinstance(candidates, list):
            candidates = []
    elif isinstance(proposed_changes, list):
        candidates = proposed_changes

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") or entry.get("file_path") or ""
        if not isinstance(path, str):
            continue
        path = path.strip().replace("\\", "/")
        content = entry.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        
        # Use consistent path validation
        if not _is_valid_static_frontend_path(path):
            continue

        lang = None
        if path.endswith(".html"):
            lang = "html"
        elif path.endswith(".css"):
            lang = "css"
        elif path.endswith(".js"):
            lang = "js"
        if lang is None:
            continue

        files_to_promote.append({
            "role": promotion_role,
            "path": path,
            "language": lang,
            "content": content.strip(),
            "entry_for_preview": lang == "html" and len(files_to_promote) == 0,
        })

    if files_to_promote:
        _log.info(
            "recovery_promotion: promoted %d file(s) from proposed_changes to artifact_outputs",
            len(files_to_promote),
        )
        return existing_artifacts + files_to_promote

    return existing_artifacts


def _recover_static_files_from_updated_state(
    updated_state: Any,
    existing_artifacts: list[Any],
    *,
    promotion_role: str = "static_frontend_file_v1",
) -> list[Any]:
    """
    Additional recovery: check ``updated_state`` for file-like entries with
    ``component/`` paths — same logic as proposed_changes recovery.
    
    Uses the same path validation as StaticFrontendFileArtifactV1 for consistency.
    """
    has_frontend = any(
        isinstance(a, dict) and is_frontend_file_artifact_role(a.get("role"))
        for a in existing_artifacts
    )
    if has_frontend:
        return existing_artifacts

    if not isinstance(updated_state, dict):
        return existing_artifacts

    candidates: list[Any] = updated_state.get("files", [])
    if not isinstance(candidates, list):
        return existing_artifacts

    files_to_promote: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path") or entry.get("file_path") or ""
        if not isinstance(path, str):
            continue
        path = path.strip().replace("\\", "/")
        content = entry.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        
        # Use consistent path validation
        if not _is_valid_static_frontend_path(path):
            continue
            
        lang = None
        if path.endswith(".html"):
            lang = "html"
        elif path.endswith(".css"):
            lang = "css"
        elif path.endswith(".js"):
            lang = "js"
        if lang is None:
            continue
        files_to_promote.append({
            "role": promotion_role,
            "path": path,
            "language": lang,
            "content": content.strip(),
            "entry_for_preview": lang == "html" and len(files_to_promote) == 0,
        })

    if files_to_promote:
        _log.info(
            "recovery_promotion(updated_state): promoted %d file(s) to artifact_outputs",
            len(files_to_promote),
        )
        return existing_artifacts + files_to_promote
    return existing_artifacts


def _build_content_index(raw: dict[str, Any]) -> dict[str, str]:
    """
    Build a path→content index from proposed_changes and updated_state files.
    
    This allows us to cross-reference artifact_outputs that are missing content
    with the actual content from the files arrays.
    
    Handles multiple formats:
    - proposed_changes: [{file: "...", content: "..."}]  (list with 'file' key)
    - proposed_changes: {files: [{path: "...", content: "..."}]}  (dict with 'files' key)
    - updated_state: {files: [{path: "...", content: "..."}]}
    """
    index: dict[str, str] = {}
    
    for source_key in ("proposed_changes", "updated_state"):
        source = raw.get(source_key)
        if source is None:
            continue
        
        # Handle both list and dict formats
        entries: list[Any] = []
        if isinstance(source, list):
            # Direct list format: [{file: "...", content: "..."}]
            entries = source
        elif isinstance(source, dict):
            # Dict with files key: {files: [...]}
            files = source.get("files", [])
            if isinstance(files, list):
                entries = files
        
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Try multiple path field names: file, path, file_path
            path = entry.get("file") or entry.get("path") or entry.get("file_path") or ""
            if not isinstance(path, str):
                continue
            path = path.strip().replace("\\", "/")
            content = entry.get("content", "")
            if isinstance(content, str) and content.strip():
                index[path] = content
    
    return index


def _enrich_artifacts_with_content(
    artifacts: list[Any],
    content_index: dict[str, str],
) -> list[Any]:
    """
    Cross-reference artifact_outputs missing content with content_index.
    
    KiloClaw agents may emit artifact_outputs with role and path but put
    actual content in proposed_changes or updated_state files. This
    function enriches such artifacts with the content from those sources.
    """
    if not content_index:
        return artifacts
    
    enriched: list[Any] = []
    enriched_count = 0
    
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            enriched.append(artifact)
            continue
        
        if not is_frontend_file_artifact_role(artifact.get("role")):
            enriched.append(artifact)
            continue
        
        if artifact.get("content"):
            enriched.append(artifact)
            continue
        
        # Missing content - try to find it using multiple path field names
        path = artifact.get("file_path") or artifact.get("path") or artifact.get("file") or ""
        if isinstance(path, str):
            path = path.strip().replace("\\", "/")
            content = content_index.get(path)
            if content:
                new_artifact = dict(artifact)
                new_artifact["content"] = content
                enriched.append(new_artifact)
                enriched_count += 1
                _log.debug("content_enrichment: found content for %s", path)
                continue
        
        enriched.append(artifact)
    
    if enriched_count > 0:
        _log.info(
            "content_enrichment: enriched %d artifact(s) with content from proposed_changes/updated_state",
            enriched_count,
        )
    
    return enriched


def normalize_generator_output(
    raw: dict[str, Any],
    *,
    thread_id: UUID,
    graph_run_id: UUID,
    generator_invocation_id: UUID,
    build_spec_id: UUID,
    identity_id: UUID | None = None,
    enable_image_generation: bool = False,
) -> BuildCandidateRecord:
    """Map KiloClaw generator JSON into persisted build_candidate columns.

    Normalization is resilient: individual artifact validation failures are
    logged and skipped rather than crashing the entire build candidate.

    Rescue paths are tracked in ``raw_payload_json._normalization_rescues`` so
    the graph node can emit a structured ``normalization_rescue`` event for
    observability without changing this function's return type.

    Args:
        raw: Raw generator output from KiloClaw
        thread_id: Thread ID for this run
        graph_run_id: Graph run ID
        generator_invocation_id: Generator invocation ID
        build_spec_id: Build spec ID
        identity_id: Optional identity ID for image generation context
        enable_image_generation: Whether to generate images during assembly (default False)
    """
    candidate_id = uuid4()
    rescue_paths: list[str] = []
    enrichment_paths: list[str] = []

    # Build content index from proposed_changes/updated_state for cross-reference.
    # This is informational enrichment (normal bookkeeping), not rescue/correction.
    content_index = _build_content_index(raw)
    if content_index:
        enrichment_paths.append(f"content_index_built:{len(content_index)}")

    ao = raw.get("artifact_outputs")
    artifacts = list(ao) if isinstance(ao, list) else []
    promotion_role = _default_promotion_role(raw)

    # Enrich artifacts missing content with content from files arrays.
    # This is normal enrichment — artifacts referencing files in proposed_changes
    # is a valid generator pattern, not malformed output requiring rescue.
    content_before = sum(1 for a in artifacts if isinstance(a, dict) and a.get("content"))
    artifacts = _enrich_artifacts_with_content(artifacts, content_index)
    content_after = sum(1 for a in artifacts if isinstance(a, dict) and a.get("content"))
    enriched_count = content_after - content_before
    if enriched_count > 0:
        enrichment_paths.append(f"content_enrichment:{enriched_count}")

    try:
        artifacts = normalize_combined_artifact_outputs_list(artifacts)
    except Exception as exc:
        _log.warning("artifact normalization failed, falling back to raw list: %s", exc)
        artifacts = list(ao) if isinstance(ao, list) else []
        rescue_paths.append(f"artifact_norm_fallback:{type(exc).__name__}")

    pre_count = len(artifacts)
    # Only attempt static file recovery when there are NO html_block_v1 artifacts
    # (blocks are intentional partial outputs, not a missing-content scenario)
    has_blocks = any(
        isinstance(a, dict) and a.get("role") == "html_block_v1"
        for a in artifacts
    )
    if not has_blocks:
        artifacts = _recover_static_files_from_proposed_changes(
            raw.get("proposed_changes"),
            artifacts,
            promotion_role=promotion_role,
        )
        if len(artifacts) > pre_count:
            rescue_paths.append(f"recover_from_proposed_changes:{len(artifacts) - pre_count}")

        pre_count = len(artifacts)
        artifacts = _recover_static_files_from_updated_state(
            raw.get("updated_state"),
            artifacts,
            promotion_role=promotion_role,
        )
        if len(artifacts) > pre_count:
            rescue_paths.append(f"recover_from_updated_state:{len(artifacts) - pre_count}")

    artifacts = _assemble_habitat_if_present(
        artifacts,
        graph_run_id=graph_run_id,
        thread_id=thread_id,
        identity_id=identity_id,
        enable_image_generation=enable_image_generation,
    )

    try:
        artifacts = normalize_combined_artifact_outputs_list(artifacts)
    except Exception as exc:
        _log.warning("post-recovery normalization failed, using pre-norm list: %s", exc)
        rescue_paths.append(f"post_recovery_norm_fallback:{type(exc).__name__}")

    patch = raw.get("updated_state") or raw.get("proposed_changes")
    # Normalize list-shaped patches to dict wrapper
    if isinstance(patch, list):
        _log.info("patch_normalization: converting list patch to dict wrapper (files=%d)", len(patch))
        patch = {"files": patch}
        rescue_paths.append(f"list_patch_coerced:{len(raw.get('updated_state') or raw.get('proposed_changes') or [])}")
    elif not isinstance(patch, dict):
        patch = {}
    try:
        patch = resolve_gallery_artifact_refs_in_patch(patch, artifacts)
        patch = normalize_static_frontend_preview_in_patch(patch, artifacts)
        patch = normalize_ui_gallery_strip_v1_in_patch(patch)
    except Exception as exc:
        _log.warning("patch normalization error (non-fatal): %s", exc)
        rescue_paths.append(f"patch_norm_error:{type(exc).__name__}")

    sandbox = raw.get("sandbox_ref")
    preview = raw.get("preview_url")

    # Embed audit trails into raw_payload_json so the graph node can surface them.
    # Enrichments are informational (normal bookkeeping); rescues are actual recovery.
    raw_with_audit = dict(raw)
    if enrichment_paths:
        raw_with_audit["_normalization_enrichments"] = enrichment_paths
    if rescue_paths:
        raw_with_audit["_normalization_rescues"] = rescue_paths
    workspace_first = bool(
        isinstance(raw.get("workspace_manifest_v1"), dict)
        and isinstance(raw.get("sandbox_ref"), str)
        and raw.get("sandbox_ref", "").strip()
    )
    if workspace_first:
        raw_with_audit, _ = compact_generator_output_payload_for_persistence(
            raw_with_audit,
            workspace_first=True,
        )

    return BuildCandidateRecord(
        build_candidate_id=candidate_id,
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        generator_invocation_id=generator_invocation_id,
        build_spec_id=build_spec_id,
        candidate_kind="habitat",
        working_state_patch_json=patch,
        artifact_refs_json=artifacts,
        raw_payload_json=raw_with_audit,
        sandbox_ref=str(sandbox) if sandbox is not None else None,
        preview_url=str(preview) if preview is not None else None,
        status="generated",
    )
