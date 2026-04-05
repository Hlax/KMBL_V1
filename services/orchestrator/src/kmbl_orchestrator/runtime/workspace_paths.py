"""Resolve and validate on-disk paths for local generator workspaces."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from kmbl_orchestrator.config import Settings

# Hint for OpenClaw + ingest: static bundle entry relative to sandbox / recommended_write_path.
CANONICAL_STATIC_PREVIEW_ENTRY = "component/preview/index.html"


class WorkspacePathError(ValueError):
    """Raised when a path escapes the allowed workspace or is invalid."""


def default_generator_workspace_root() -> Path:
    """Default root when ``KMBL_GENERATOR_WORKSPACE_ROOT`` is unset (not under the git repo)."""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            return (Path(local) / "KMBL" / "generator_workspaces").resolve()
    return Path(tempfile.gettempdir()).resolve() / "kmbl_generator_workspaces"


def resolve_generator_workspace_root(settings: Settings) -> Path:
    raw = (getattr(settings, "kmbl_generator_workspace_root", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return default_generator_workspace_root()


def run_workspace_directory(settings: Settings, thread_id: UUID, graph_run_id: UUID) -> Path:
    """Recommended directory for one graph run: ``{root}/{thread_id}/{graph_run_id}``."""
    root = resolve_generator_workspace_root(settings)
    return (root / str(thread_id) / str(graph_run_id)).resolve()


def normalize_manifest_relative_path(path: str) -> str:
    """
    Normalize manifest file paths so backslashes, stray spaces, and duplicate slashes
    do not diverge from on-disk paths written by tools (POSIX-style ``component/...``).
    """
    s = str(path or "").strip().replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    return s


def paths_resolved_equal(a: Path, b: Path) -> bool:
    """True if resolved paths refer to the same location (case-insensitive on Windows)."""
    ra = a.resolve()
    rb = b.resolve()
    if os.name == "nt":
        return str(ra).casefold() == str(rb).casefold()
    return ra == rb


def parse_sandbox_ref(ref: str) -> Path:
    """
    Parse ``sandbox_ref`` from generator output: plain absolute path or ``file://`` URI.
    """
    s = ref.strip()
    if not s:
        raise WorkspacePathError("sandbox_ref is empty")
    if s.startswith("file://"):
        parsed = urlparse(s)
        path = unquote(parsed.path or "")
        if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return Path(path).resolve()
    return Path(s).expanduser().resolve()


def ensure_path_under(allowed_root: Path, p: Path) -> Path:
    """Resolve ``p`` and ensure it is ``allowed_root`` or a descendant."""
    root = allowed_root.resolve()
    candidate = p.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise WorkspacePathError(
            f"path not under workspace root: {candidate} (root={root})"
        ) from e
    return candidate


def assert_sandbox_under_workspace_root(settings: Settings, sandbox: Path) -> Path:
    """``sandbox`` must lie under :func:`resolve_generator_workspace_root`."""
    root = resolve_generator_workspace_root(settings)
    return ensure_path_under(root, sandbox)


def build_workspace_context_for_generator(
    settings: Settings,
    thread_id: UUID,
    graph_run_id: UUID,
) -> dict[str, str]:
    """Machine-readable paths injected into ``GeneratorRoleInput.workspace_context``."""
    root = resolve_generator_workspace_root(settings)
    rw = run_workspace_directory(settings, thread_id, graph_run_id)
    return {
        "workspace_root_resolved": str(root),
        "recommended_write_path": str(rw),
        # Stable relative path for static preview HTML (under sandbox = recommended_write_path).
        "canonical_preview_entry_relative": CANONICAL_STATIC_PREVIEW_ENTRY,
    }
