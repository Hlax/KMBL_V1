"""Expand workspace_manifest_v1 + sandbox_ref into static or interactive frontend artifact_outputs."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from uuid import UUID

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.frontend_artifact_roles import FRONTEND_FILE_ARTIFACT_ROLES
from kmbl_orchestrator.contracts.workspace_manifest_v1 import WorkspaceManifestV1
from kmbl_orchestrator.runtime.workspace_paths import (
    CANONICAL_STATIC_PREVIEW_ENTRY,
    WorkspacePathError,
    assert_sandbox_under_workspace_root,
    normalize_manifest_relative_path,
    parse_sandbox_ref,
    paths_resolved_equal,
    resolve_generator_workspace_root,
    run_workspace_directory,
)

_log = logging.getLogger(__name__)


def workspace_ingest_should_attempt(raw: dict[str, Any]) -> bool:
    """True when manifest + sandbox are present and ingest may run (see :func:`ingest_workspace_manifest_if_present`)."""
    return workspace_ingest_not_attempted_reason(raw) is None


def workspace_ingest_not_attempted_reason(raw: dict[str, Any]) -> dict[str, Any] | None:
    """If ingest will not run, return structured reason; else ``None`` (ingest may run)."""
    cf = raw.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and cf["code"].strip():
        return {"code": "contract_failure", "detail": "contract_failure set"}
    wm = raw.get("workspace_manifest_v1")
    sr = raw.get("sandbox_ref")
    if not isinstance(wm, dict) or not wm:
        return {"code": "no_manifest", "detail": "workspace_manifest_v1 missing or not a dict"}
    files = wm.get("files")
    if not isinstance(files, list) or len(files) == 0:
        return {"code": "no_files_in_manifest", "detail": "manifest.files missing or empty"}
    if not isinstance(sr, str) or not str(sr).strip():
        return {"code": "no_sandbox_ref", "detail": "sandbox_ref missing or empty"}
    return None


class WorkspaceIngestError(ValueError):
    """Ingest could not read or validate workspace files."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


def _infer_language(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".html"):
        return "html"
    if lower.endswith(".css"):
        return "css"
    if lower.endswith(".js"):
        return "js"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".glsl"):
        return "glsl"
    if lower.endswith(".wgsl"):
        return "wgsl"
    if lower.endswith(".vert"):
        return "vert"
    if lower.endswith(".frag"):
        return "frag"
    if lower.endswith(".splat"):
        return "splat"
    if lower.endswith(".ply"):
        return "ply"
    raise WorkspaceIngestError(f"unsupported file extension for ingest: {path}")


def compute_workspace_ingest_preflight(
    settings: Settings,
    thread_id: UUID,
    graph_run_id: UUID,
    sandbox_ref: str,
    wm_raw: dict[str, Any],
) -> dict[str, Any]:
    """
    Structured snapshot before reading files: roots, recommended vs sandbox alignment,
    normalized manifest paths. Used for observability and mismatch detection.
    """
    root = resolve_generator_workspace_root(settings)
    recommended = run_workspace_directory(settings, thread_id, graph_run_id)
    out: dict[str, Any] = {
        "workspace_root_resolved": str(root),
        "recommended_write_path": str(recommended),
        "canonical_preview_entry_relative": CANONICAL_STATIC_PREVIEW_ENTRY,
    }
    try:
        sandbox = assert_sandbox_under_workspace_root(settings, parse_sandbox_ref(sandbox_ref))
    except WorkspacePathError as e:
        out["sandbox_resolved"] = None
        out["sandbox_parse_error"] = str(e)
        out["sandbox_under_workspace_root"] = False
        out["sandbox_matches_recommended_write_path"] = False
        return out
    out["sandbox_resolved"] = str(sandbox)
    out["sandbox_under_workspace_root"] = True
    out["sandbox_matches_recommended_write_path"] = paths_resolved_equal(sandbox, recommended)
    files = wm_raw.get("files")
    norms: list[str] = []
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                norms.append(normalize_manifest_relative_path(item["path"]))
        out["manifest_file_count"] = len(files)
    else:
        out["manifest_file_count"] = 0
    out["manifest_paths_normalized"] = norms
    return out


def _classify_missing_disk_artifact(
    *,
    sandbox: Path,
    manifest_rel: str,
    disk_path: Path,
) -> dict[str, Any]:
    """Turn a missing file into an explicit reason (vs opaque ENOENT)."""
    parent = disk_path.parent
    detail: dict[str, Any] = {
        "ingest_failure_class": "artifact_not_found",
        "manifest_relative_path": manifest_rel,
        "expected_absolute_path": str(disk_path),
        "sandbox_resolved": str(sandbox),
        "parent_path": str(parent),
        "parent_exists": parent.exists(),
        "parent_is_directory": parent.is_dir() if parent.exists() else False,
    }
    if not parent.exists():
        detail["ingest_failure_class"] = "parent_directory_missing"
        return detail
    if parent.is_dir():
        try:
            names = sorted([c.name for c in parent.iterdir()])
            detail["sibling_filenames_in_parent"] = names[:48]
            want = disk_path.name
            lower_names = {n.lower(): n for n in names}
            if want not in names and want.lower() in lower_names:
                detail["ingest_failure_class"] = "possible_case_mismatch"
                detail["case_insensitive_match"] = lower_names[want.lower()]
        except OSError as e:
            detail["parent_list_error"] = str(e)[:300]
    return detail


def _non_frontend_file_artifacts(raw_ao: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in raw_ao:
        if isinstance(a, dict) and str(a.get("role") or "") not in FRONTEND_FILE_ARTIFACT_ROLES:
            out.append(a)
    return out


def ingest_workspace_manifest_if_present(
    raw: dict[str, Any],
    *,
    settings: Settings,
    thread_id: UUID,
    graph_run_id: UUID,
    ingested_artifact_role: str = "static_frontend_file_v1",
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """
    If ``workspace_manifest_v1`` and non-empty ``sandbox_ref`` are present, read files from disk
    and set ``artifact_outputs`` rows (``static_frontend_file_v1`` or ``interactive_frontend_app_v1``).

    Returns ``(raw, stats, inline_skip_reason)``. ``inline_skip_reason`` is ``inline_html`` when
    ingest skipped because inline HTML already occupied the bundle; otherwise ``None``.
    """
    if ingested_artifact_role not in FRONTEND_FILE_ARTIFACT_ROLES:
        raise ValueError(
            f"ingested_artifact_role must be one of {sorted(FRONTEND_FILE_ARTIFACT_ROLES)}"
        )
    _ = thread_id
    _ = graph_run_id
    cf = raw.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and cf["code"].strip():
        return raw, None, None

    wm_raw = raw.get("workspace_manifest_v1")
    sr_raw = raw.get("sandbox_ref")
    if not isinstance(wm_raw, dict) or not wm_raw:
        return raw, None, None
    if not isinstance(sr_raw, str) or not sr_raw.strip():
        return raw, None, None

    try:
        manifest = WorkspaceManifestV1.model_validate(wm_raw)
    except Exception as e:
        raise WorkspaceIngestError(f"invalid workspace_manifest_v1: {e}") from e

    try:
        sandbox = assert_sandbox_under_workspace_root(settings, parse_sandbox_ref(sr_raw))
    except WorkspacePathError as e:
        raise WorkspaceIngestError(str(e)) from e

    max_total = int(getattr(settings, "kmbl_workspace_ingest_max_bytes_total", 2_000_000))
    total_bytes = 0
    ingested: list[dict[str, Any]] = []
    entry_norm = (
        normalize_manifest_relative_path(manifest.entry_html)
        if isinstance(manifest.entry_html, str) and manifest.entry_html.strip()
        else None
    )

    for f in manifest.files:
        path = normalize_manifest_relative_path(f.path)
        if ".." in path or path.startswith("/"):
            raise WorkspaceIngestError(f"unsafe manifest path: {path}")
        if not path.startswith("component/"):
            raise WorkspaceIngestError(f'manifest path must start with "component/": {path}')
        disk_path = (sandbox / path).resolve()
        try:
            disk_path.relative_to(sandbox.resolve())
        except ValueError as e:
            raise WorkspaceIngestError(f"path escapes sandbox: {path}") from e
        if not disk_path.is_file():
            d = _classify_missing_disk_artifact(
                sandbox=sandbox, manifest_rel=path, disk_path=disk_path,
            )
            msg = (
                f"manifest file not on disk: {path} — {d.get('ingest_failure_class', 'unknown')} "
                f"(expected {disk_path})"
            )
            raise WorkspaceIngestError(msg, details=d) from None
        data = disk_path.read_bytes()
        total_bytes += len(data)
        if total_bytes > max_total:
            raise WorkspaceIngestError(
                f"workspace ingest exceeds kmbl_workspace_ingest_max_bytes_total ({max_total})"
            )
        if f.sha256:
            h = hashlib.sha256(data).hexdigest()
            if h.lower() != f.sha256.strip().lower():
                raise WorkspaceIngestError(f"sha256 mismatch for {path}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise WorkspaceIngestError(f"non-utf8 file: {path}") from e
        lang = _infer_language(path)
        ingested.append(
            {
                "role": ingested_artifact_role,
                "path": path,
                "language": lang,
                "content": text,
                "bundle_id": "workspace_ingest",
                "entry_for_preview": bool(entry_norm and path == entry_norm),
            }
        )

    if not ingested:
        raise WorkspaceIngestError("workspace_manifest_v1 produced no files")

    others = _non_frontend_file_artifacts(list(raw.get("artifact_outputs") or []))
    raw = dict(raw)
    raw["artifact_outputs"] = others + ingested
    stats = {
        "sandbox_ref": str(sandbox),
        "file_count": len(ingested),
        "total_bytes": total_bytes,
        "workspace_authoritative": True,
    }
    raw["_workspace_ingest"] = stats
    return raw, stats, None
