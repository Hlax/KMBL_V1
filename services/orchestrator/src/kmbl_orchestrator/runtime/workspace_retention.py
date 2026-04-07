"""Conservative cleanup of on-disk per-run generator workspaces (Supabase remains authoritative)."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.workspace_paths import resolve_generator_workspace_root

_log = logging.getLogger(__name__)

# Sentinel file written into a run workspace when parsing fails.
PARSE_FAIL_MARKER = ".kmbl_parse_failed"


@dataclass(frozen=True)
class WorkspacePruneResult:
    deleted_paths: list[str]
    skipped_paths: list[str]
    skipped_reasons: dict[str, str]
    deleted_parse_failed: list[str] = field(default_factory=list)


def _parse_uuid_dir(name: str) -> UUID | None:
    try:
        return UUID(name)
    except (ValueError, TypeError):
        return None


def mark_workspace_parse_failed(run_dir: Path) -> None:
    """Write a lightweight marker so the fast-prune lane can identify parse-failed workspaces."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        marker = run_dir / PARSE_FAIL_MARKER
        marker.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        _log.debug("workspace_retention: could not write parse-fail marker to %s", run_dir)


def _is_parse_failed(run_dir: Path) -> bool:
    """Check whether a run directory is tagged as parse-failed."""
    return (run_dir / PARSE_FAIL_MARKER).is_file()


def ensure_clean_workspace(run_dir: Path) -> None:
    """Guarantee *run_dir* starts clean for a new generator run.

    If the directory already exists **and** carries a parse-fail marker from a prior
    attempt, it is wiped so stale artifacts do not leak into the new run.
    If the directory does not exist, it is created.
    If it exists without a marker (e.g. the generator CLI already pre-populated it
    during this run), it is left intact.

    Thread safety note: the ``{root}/{thread_id}/{graph_run_id}`` layout makes
    collisions between concurrent runs impossible (each ``graph_run_id`` is unique).
    """
    marker = run_dir / PARSE_FAIL_MARKER
    if run_dir.exists() and marker.is_file():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)


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

    **Parse-fail fast-prune lane**: directories carrying a ``.kmbl_parse_failed`` marker are
    pruned after ``kmbl_generator_workspace_parse_fail_retention_hours`` instead of the normal
    ``min_age_days`` — unless ``kmbl_generator_workspace_debug_retention`` is true (operator
    opted in to preserve failed workspaces for longer debugging).

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

    # Fast-prune lane config
    debug_retention = bool(getattr(settings, "kmbl_generator_workspace_debug_retention", False))
    parse_fail_hours = float(getattr(settings, "kmbl_generator_workspace_parse_fail_retention_hours", 24.0))
    # When debug_retention is on, parse-failed dirs use the normal long window.
    parse_fail_cutoff_secs = parse_fail_hours * 3600.0 if (parse_fail_hours > 0 and not debug_retention) else 0.0

    root = resolve_generator_workspace_root(settings)
    if not root.is_dir():
        return WorkspacePruneResult(
            deleted_paths=[],
            skipped_paths=[],
            skipped_reasons={str(root): "workspace root does not exist or is not a directory"},
        )

    protect = protect_graph_run_ids or frozenset()
    ts_now = now or time.time()
    cutoff = ts_now - min_days * 86400.0
    deleted: list[str] = []
    deleted_pf: list[str] = []
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

            # Determine effective cutoff: parse-failed dirs may use the shorter window.
            is_pf = _is_parse_failed(run_dir)
            effective_cutoff = cutoff
            if is_pf and parse_fail_cutoff_secs > 0:
                effective_cutoff = ts_now - parse_fail_cutoff_secs

            if mtime > effective_cutoff:
                continue
            if dry_run:
                deleted.append(str(run_dir))
                if is_pf:
                    deleted_pf.append(str(run_dir))
                continue
            try:
                shutil.rmtree(run_dir, ignore_errors=False)
                deleted.append(str(run_dir))
                if is_pf:
                    deleted_pf.append(str(run_dir))
            except OSError as e:
                skipped.append(str(run_dir))
                reasons[str(run_dir)] = f"rmtree failed: {e!s}"[:200]
                _log.warning("workspace_retention: failed to delete %s: %s", run_dir, e)

    return WorkspacePruneResult(
        deleted_paths=sorted(deleted),
        skipped_paths=sorted(skipped),
        skipped_reasons=reasons,
        deleted_parse_failed=sorted(deleted_pf),
    )


def prune_stale_generator_workspaces_summary(result: WorkspacePruneResult) -> dict[str, Any]:
    return {
        "deleted_count": len(result.deleted_paths),
        "deleted_parse_failed_count": len(result.deleted_parse_failed),
        "skipped_count": len(result.skipped_paths),
        "deleted_paths": result.deleted_paths[:64],
        "skipped_sample": result.skipped_paths[:16],
    }
