"""Conservative cleanup of on-disk per-run generator workspaces (Supabase remains authoritative)."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.workspace_paths import resolve_generator_workspace_root

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspacePruneResult:
    deleted_paths: list[str]
    skipped_paths: list[str]
    skipped_reasons: dict[str, str]


def _parse_uuid_dir(name: str) -> UUID | None:
    try:
        return UUID(name)
    except (ValueError, TypeError):
        return None


def prune_stale_generator_workspaces(
    settings: Settings,
    *,
    dry_run: bool = False,
    protect_graph_run_ids: frozenset[UUID] | None = None,
    now: float | None = None,
) -> WorkspacePruneResult:
    """
    Remove per-run workspace folders under ``kmbl_generator_workspace_root`` that are older than
    ``kmbl_generator_workspace_retention_min_age_days`` (by directory mtime).

    No-op unless ``kmbl_generator_workspace_retention_enabled`` is true. Never deletes the
    workspace root itself or paths outside it. Skips unparseable directory names and optional
    ``protect_graph_run_ids`` (e.g. currently active runs — caller must supply).
    """
    if not bool(getattr(settings, "kmbl_generator_workspace_retention_enabled", False)):
        return WorkspacePruneResult(deleted_paths=[], skipped_paths=[], skipped_reasons={})

    min_days = float(getattr(settings, "kmbl_generator_workspace_retention_min_age_days", 14.0))
    if min_days <= 0:
        return WorkspacePruneResult(
            deleted_paths=[],
            skipped_paths=[],
            skipped_reasons={"_": "min_age_days must be positive"},
        )

    root = resolve_generator_workspace_root(settings)
    if not root.is_dir():
        return WorkspacePruneResult(
            deleted_paths=[],
            skipped_paths=[],
            skipped_reasons={str(root): "workspace root does not exist or is not a directory"},
        )

    protect = protect_graph_run_ids or frozenset()
    cutoff = (now or time.time()) - min_days * 86400.0
    deleted: list[str] = []
    skipped: list[str] = []
    reasons: dict[str, str] = {}

    for thread_dir in sorted(root.iterdir()):
        if not thread_dir.is_dir():
            continue
        if _parse_uuid_dir(thread_dir.name) is None:
            skipped.append(str(thread_dir))
            reasons[str(thread_dir)] = "thread directory name is not a UUID"
            continue
        for run_dir in sorted(thread_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            rid = _parse_uuid_dir(run_dir.name)
            if rid is None:
                skipped.append(str(run_dir))
                reasons[str(run_dir)] = "run directory name is not a UUID"
                continue
            if rid in protect:
                skipped.append(str(run_dir))
                reasons[str(run_dir)] = "protected graph_run_id"
                continue
            try:
                mtime = run_dir.stat().st_mtime
            except OSError as e:
                skipped.append(str(run_dir))
                reasons[str(run_dir)] = f"stat failed: {e!s}"[:200]
                continue
            if mtime > cutoff:
                continue
            if dry_run:
                deleted.append(str(run_dir))
                continue
            try:
                shutil.rmtree(run_dir, ignore_errors=False)
                deleted.append(str(run_dir))
            except OSError as e:
                skipped.append(str(run_dir))
                reasons[str(run_dir)] = f"rmtree failed: {e!s}"[:200]
                _log.warning("workspace_retention: failed to delete %s: %s", run_dir, e)

    return WorkspacePruneResult(
        deleted_paths=sorted(deleted),
        skipped_paths=sorted(skipped),
        skipped_reasons=reasons,
    )


def prune_stale_generator_workspaces_summary(result: WorkspacePruneResult) -> dict[str, Any]:
    return {
        "deleted_count": len(result.deleted_paths),
        "skipped_count": len(result.skipped_paths),
        "deleted_paths": result.deleted_paths[:64],
        "skipped_sample": result.skipped_paths[:16],
    }
