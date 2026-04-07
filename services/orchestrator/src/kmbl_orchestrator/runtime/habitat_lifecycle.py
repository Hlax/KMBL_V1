"""
Habitat materialization lifecycle manager.

BOUNDARY DOCUMENTATION
======================

Durable source of truth (canonical, never evict):
    - DB / persistence layer: WorkingStagingRecord, BuildCandidateRecord, StagingSnapshotRecord,
      PublicationSnapshotRecord, BuildSpecRecord, artifact_refs, all metadata/summaries.
    - Object storage: heavier/binary assets referenced by artifact_refs when applicable.

Local disk (evictable cache layer):
    - per-thread and per-run workspace folders created by the generator / OpenClaw
    - assembled static preview bundles materialized for fast serving
    - These are ephemeral: always rebuildable from persisted state

OpenClaw workspace:
    - Transient authoring/runtime scratch space; not a long-term archive
    - When a new session or new surface is intentionally started, a new local materialization
      may be created; older ones become eviction candidates after persistence is confirmed

MATERIALIZATION POLICY
======================

1.  At most ``max_active_live`` live_habitat materializations per active thread.
    Registering a new live_habitat for a thread supersedes all existing ones.

2.  ``candidate_preview`` materializations are run-scoped; they are automatically
    eviction-eligible once the graph run is no longer active.

3.  Local materializations must be rebuildable from persisted working_staging /
    build_candidate state.  ``can_rehydrate_from_persistence`` must be True before
    a materialization can be evicted.

EVICTION RULES
==============

Eviction is conservative (safe-to-delete only):
    - Only evict if ``can_rehydrate_from_persistence`` is True
    - Only evict if the local_path actually exists (nothing to do otherwise)
    - Never evict the sole active live_habitat for an active thread
    - TTL-based: superseded materializations older than ``eviction_ttl_days`` may be evicted
    - Max-count-based: when active count exceeds ``max_active_live``, oldest superseded are evicted first
    - Never delete the only durable copy of anything

TELEMETRY EVENTS
================

    HABITAT_MATERIALIZED                 — new local habitat folder registered
    HABITAT_REHYDRATED                   — local folder rebuilt from persisted state
    HABITAT_EVICTED                      — local folder deleted safely
    HABITAT_EVICTION_SKIPPED_NOT_DURABLE — eviction skipped: persistence not confirmed
    HABITAT_EVICTION_SKIPPED_ACTIVE_THREAD — eviction skipped: still the active thread habitat

PREVIEW SERVING MODE
====================

    "persisted"   — HTML/artifacts served from DB projection (working_staging payload)
    "local_cache" — served from a local materialized workspace folder
    "degraded"    — neither source available; surface an error/placeholder to the operator
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    LocalHabitatManifest,
    MaterializationKind,
    MaterializationStatus,
    PreviewServingMode,
)
from kmbl_orchestrator.runtime.run_events import RunEventType

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process registry (lightweight; not persisted between restarts).
# Caller may supply a persistent backing store in the future.
# ---------------------------------------------------------------------------

_REGISTRY: dict[UUID, LocalHabitatManifest] = {}
_REGISTRY_LOCK = __import__("threading").Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API — materialization registration
# ---------------------------------------------------------------------------


def register_materialization(
    *,
    thread_id: UUID,
    local_path: str,
    materialization_kind: MaterializationKind,
    graph_run_id: UUID | None = None,
    source_revision: int | None = None,
    revision_id: UUID | None = None,
    checksum: str | None = None,
    entrypoint: str | None = None,
    can_rehydrate_from_persistence: bool = False,
) -> LocalHabitatManifest:
    """
    Register a newly created local materialization.

    For ``live_habitat`` kind this supersedes all prior live_habitat entries
    for the same thread (sets them to ``superseded``).  Returns the new manifest.
    """
    manifest = LocalHabitatManifest(
        manifest_id=uuid4(),
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        materialization_kind=materialization_kind,
        local_path=local_path,
        source_revision=source_revision,
        revision_id=revision_id,
        checksum=checksum,
        entrypoint=entrypoint,
        can_rehydrate_from_persistence=can_rehydrate_from_persistence,
        materialization_status="active",
        created_at=_now_iso(),
        last_accessed_at=_now_iso(),
    )

    with _REGISTRY_LOCK:
        if materialization_kind == "live_habitat":
            # Enforce at-most-one active live_habitat per thread.
            for existing in _REGISTRY.values():
                if (
                    existing.thread_id == thread_id
                    and existing.materialization_kind == "live_habitat"
                    and existing.materialization_status == "active"
                ):
                    _REGISTRY[existing.manifest_id] = existing.model_copy(
                        update={"materialization_status": "superseded"}
                    )
        _REGISTRY[manifest.manifest_id] = manifest

    _log.info(
        "habitat_lifecycle: registered %s manifest_id=%s thread=%s path=%s",
        materialization_kind,
        manifest.manifest_id,
        thread_id,
        local_path,
    )
    return manifest


def mark_materialization_accessed(manifest_id: UUID) -> LocalHabitatManifest | None:
    """Update ``last_accessed_at`` for a manifest entry (LRU hint)."""
    with _REGISTRY_LOCK:
        m = _REGISTRY.get(manifest_id)
        if m is None:
            return None
        updated = m.model_copy(update={"last_accessed_at": _now_iso()})
        _REGISTRY[manifest_id] = updated
        return updated


def get_active_live_habitat(thread_id: UUID) -> LocalHabitatManifest | None:
    """Return the single active live_habitat manifest for a thread, or None."""
    with _REGISTRY_LOCK:
        for m in _REGISTRY.values():
            if (
                m.thread_id == thread_id
                and m.materialization_kind == "live_habitat"
                and m.materialization_status == "active"
            ):
                return m
        return None


def list_manifests(
    *,
    thread_id: UUID | None = None,
    materialization_kind: MaterializationKind | None = None,
    status: MaterializationStatus | None = None,
) -> list[LocalHabitatManifest]:
    """List all registered manifests, optionally filtered."""
    with _REGISTRY_LOCK:
        results = list(_REGISTRY.values())
    if thread_id is not None:
        results = [m for m in results if m.thread_id == thread_id]
    if materialization_kind is not None:
        results = [m for m in results if m.materialization_kind == materialization_kind]
    if status is not None:
        results = [m for m in results if m.materialization_status == status]
    return results


# ---------------------------------------------------------------------------
# Eviction result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HabitatEvictionResult:
    evicted: list[str] = field(default_factory=list)
    skipped_not_durable: list[str] = field(default_factory=list)
    skipped_active_thread: list[str] = field(default_factory=list)
    skipped_other: list[str] = field(default_factory=list)
    telemetry_events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Eviction / GC
# ---------------------------------------------------------------------------


def evict_superseded_habitats(
    settings: Settings,
    *,
    active_thread_ids: frozenset[UUID] | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> HabitatEvictionResult:
    """
    Conservative GC for superseded local habitat materializations.

    Rules (all must be satisfied for eviction):
        1. ``materialization_status == 'superseded'``
        2. ``can_rehydrate_from_persistence == True``
        3. Thread is NOT in ``active_thread_ids`` (if supplied)
        4. ``created_at`` older than ``kmbl_habitat_eviction_ttl_days``
        5. Local path exists on disk

    Emits telemetry event dicts (caller may forward to ``append_graph_run_event``).
    """
    if not bool(getattr(settings, "kmbl_habitat_lifecycle_enabled", False)):
        return HabitatEvictionResult()

    ttl_days = float(getattr(settings, "kmbl_habitat_eviction_ttl_days", 7.0))
    if ttl_days <= 0:
        return HabitatEvictionResult()

    _now = now if now is not None else time.time()
    cutoff = _now - ttl_days * 86400.0
    active_threads = active_thread_ids or frozenset()

    evicted: list[str] = []
    skipped_not_durable: list[str] = []
    skipped_active_thread: list[str] = []
    skipped_other: list[str] = []
    telemetry_events: list[dict[str, Any]] = []

    with _REGISTRY_LOCK:
        candidates = [
            m for m in _REGISTRY.values() if m.materialization_status == "superseded"
        ]

    for m in candidates:
        path = m.local_path

        # Rule 3: protect active threads
        if m.thread_id in active_threads:
            skipped_active_thread.append(path)
            telemetry_events.append(
                {
                    "event_type": RunEventType.HABITAT_EVICTION_SKIPPED_ACTIVE_THREAD,
                    "payload": {
                        "manifest_id": str(m.manifest_id),
                        "thread_id": str(m.thread_id),
                        "local_path": path,
                        "materialization_kind": m.materialization_kind,
                    },
                }
            )
            continue

        # Rule 2: durability precondition
        if not m.can_rehydrate_from_persistence:
            skipped_not_durable.append(path)
            telemetry_events.append(
                {
                    "event_type": RunEventType.HABITAT_EVICTION_SKIPPED_NOT_DURABLE,
                    "payload": {
                        "manifest_id": str(m.manifest_id),
                        "thread_id": str(m.thread_id),
                        "local_path": path,
                        "materialization_kind": m.materialization_kind,
                    },
                }
            )
            continue

        # Rule 4: TTL
        try:
            created_ts = datetime.fromisoformat(m.created_at).timestamp()
        except (ValueError, TypeError):
            skipped_other.append(path)
            continue
        if created_ts > cutoff:
            continue

        # Rule 5: path must exist (nothing to evict otherwise)
        local = Path(path)
        if not local.exists():
            # Already gone — update registry status silently.
            _mark_evicted_in_registry(m.manifest_id)
            continue

        if dry_run:
            evicted.append(path)
            telemetry_events.append(_evicted_event(m))
            continue

        try:
            if local.is_dir():
                shutil.rmtree(local, ignore_errors=False)
            else:
                local.unlink()
            evicted.append(path)
            _mark_evicted_in_registry(m.manifest_id)
            telemetry_events.append(_evicted_event(m))
            _log.info(
                "habitat_lifecycle: evicted %s manifest_id=%s thread=%s",
                m.materialization_kind,
                m.manifest_id,
                m.thread_id,
            )
        except OSError as exc:
            skipped_other.append(path)
            _log.warning(
                "habitat_lifecycle: failed to evict %s: %s", path, exc
            )

    return HabitatEvictionResult(
        evicted=sorted(evicted),
        skipped_not_durable=sorted(skipped_not_durable),
        skipped_active_thread=sorted(skipped_active_thread),
        skipped_other=sorted(skipped_other),
        telemetry_events=telemetry_events,
    )


def _mark_evicted_in_registry(manifest_id: UUID) -> None:
    with _REGISTRY_LOCK:
        m = _REGISTRY.get(manifest_id)
        if m is not None:
            _REGISTRY[manifest_id] = m.model_copy(
                update={"materialization_status": "evicted"}
            )


def _evicted_event(m: LocalHabitatManifest) -> dict[str, Any]:
    return {
        "event_type": RunEventType.HABITAT_EVICTED,
        "payload": {
            "manifest_id": str(m.manifest_id),
            "thread_id": str(m.thread_id),
            "graph_run_id": str(m.graph_run_id) if m.graph_run_id else None,
            "local_path": m.local_path,
            "materialization_kind": m.materialization_kind,
            "source_revision": m.source_revision,
            "can_rehydrate_from_persistence": m.can_rehydrate_from_persistence,
        },
    }


# ---------------------------------------------------------------------------
# Rehydration helper
# ---------------------------------------------------------------------------


def record_rehydration(
    manifest_id: UUID,
    *,
    rehydrated_path: str | None = None,
) -> dict[str, Any]:
    """
    Mark a previously evicted (or pending) manifest as active again after rehydration.

    Returns a telemetry event dict.
    """
    with _REGISTRY_LOCK:
        m = _REGISTRY.get(manifest_id)
        if m is not None:
            updates: dict[str, Any] = {
                "materialization_status": "active",
                "last_accessed_at": _now_iso(),
            }
            if rehydrated_path:
                updates["local_path"] = rehydrated_path
            _REGISTRY[manifest_id] = m.model_copy(update=updates)
            m = _REGISTRY[manifest_id]

    return {
        "event_type": RunEventType.HABITAT_REHYDRATED,
        "payload": {
            "manifest_id": str(manifest_id),
            "thread_id": str(m.thread_id) if m else None,
            "rehydrated_path": rehydrated_path,
        },
    }


# ---------------------------------------------------------------------------
# Preview serving mode classification
# ---------------------------------------------------------------------------


def resolve_preview_serving_mode(
    *,
    local_manifest: LocalHabitatManifest | None,
    has_persisted_payload: bool,
) -> PreviewServingMode:
    """
    Determine the appropriate preview serving mode.

    Priority:
        1. ``persisted``  — persisted payload (working_staging / build_candidate) is available
        2. ``local_cache`` — active local materialization with an accessible path
        3. ``degraded``   — neither source is usable

    Using ``persisted`` as the preferred mode ensures the operator always sees the
    canonical state, even if a local cache is warm.  The caller may override to
    ``local_cache`` when a fresher local materialization exists (e.g. for live streaming).
    """
    if has_persisted_payload:
        return "persisted"
    if (
        local_manifest is not None
        and local_manifest.materialization_status == "active"
        and Path(local_manifest.local_path).exists()
    ):
        return "local_cache"
    return "degraded"


def preview_serving_mode_payload(
    mode: PreviewServingMode,
    *,
    manifest: LocalHabitatManifest | None = None,
) -> dict[str, Any]:
    """
    Build a compact telemetry/metadata dict describing the preview serving mode.

    Suitable for embedding in API response payloads and run_events.
    """
    out: dict[str, Any] = {"preview_serving_mode": mode}
    if manifest is not None:
        out["materialization_source"] = manifest.materialization_kind
        out["manifest_id"] = str(manifest.manifest_id)
        out["materialization_status"] = manifest.materialization_status
        if manifest.entrypoint:
            out["entrypoint"] = manifest.entrypoint
    else:
        out["materialization_source"] = None
    return out


# ---------------------------------------------------------------------------
# Registry helpers for tests / maintenance
# ---------------------------------------------------------------------------


def clear_registry_for_tests() -> None:
    """Reset the in-process registry.  Tests only."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


def registry_snapshot() -> list[LocalHabitatManifest]:
    """Return a copy of all registry entries (diagnostic / test helper)."""
    with _REGISTRY_LOCK:
        return list(_REGISTRY.values())


def materialize_workspace_to_live_habitat(
    *,
    thread_id: UUID,
    graph_run_id: UUID,
    workspace_path: str,
    source_revision: int | None = None,
    revision_id: UUID | None = None,
    entrypoint: str | None = None,
) -> LocalHabitatManifest:
    """Promote a workspace build to the live habitat for a thread.

    On ``pass`` or ``stage`` the accepted workspace build becomes the live
    habitat.  This supersedes any prior live_habitat for the thread and
    registers the new materialization backed by the workspace folder.

    The workspace is the single source of truth — inline artifact bodies in
    the persistence layer are **not** required for the live habitat to render.
    """
    manifest = register_materialization(
        thread_id=thread_id,
        local_path=workspace_path,
        materialization_kind="live_habitat",
        graph_run_id=graph_run_id,
        source_revision=source_revision,
        revision_id=revision_id,
        entrypoint=entrypoint,
        can_rehydrate_from_persistence=True,
    )
    _log.info(
        "habitat_lifecycle: workspace→live_habitat thread=%s manifest_id=%s path=%s",
        thread_id,
        manifest.manifest_id,
        workspace_path,
    )
    return manifest
