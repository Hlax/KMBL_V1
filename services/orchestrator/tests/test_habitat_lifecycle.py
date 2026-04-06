"""
Tests for habitat materialization lifecycle.

Covers:
    G1  one active live_habitat per thread
    G2  superseded thread habitat becomes eviction-eligible after persistence
    G3  candidate preview can rehydrate from persisted state
    G4  no eviction when durability/rehydration preconditions fail
    G5  preview serving mode correctly reflects persisted vs local cache source
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import LocalHabitatManifest, PreviewServingMode
from kmbl_orchestrator.runtime.habitat_lifecycle import (
    HabitatEvictionResult,
    clear_registry_for_tests,
    evict_superseded_habitats,
    get_active_live_habitat,
    list_manifests,
    record_rehydration,
    register_materialization,
    registry_snapshot,
    resolve_preview_serving_mode,
    preview_serving_mode_payload,
)
from kmbl_orchestrator.runtime.run_events import RunEventType


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Ensure a clean registry for every test."""
    clear_registry_for_tests()


# ── G1: one active live_habitat per thread ──────────────────────────────────


def test_register_live_habitat_sets_active() -> None:
    tid = uuid4()
    m = register_materialization(
        thread_id=tid,
        local_path="/tmp/habitat/a",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    assert m.materialization_status == "active"
    assert m.materialization_kind == "live_habitat"
    assert m.thread_id == tid


def test_second_live_habitat_supersedes_first() -> None:
    """Registering a new live_habitat for a thread must supersede the prior one."""
    tid = uuid4()
    m1 = register_materialization(
        thread_id=tid,
        local_path="/tmp/habitat/a",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    m2 = register_materialization(
        thread_id=tid,
        local_path="/tmp/habitat/b",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )

    snapshot = {m.manifest_id: m for m in registry_snapshot()}
    assert snapshot[m1.manifest_id].materialization_status == "superseded"
    assert snapshot[m2.manifest_id].materialization_status == "active"


def test_only_one_active_live_habitat_per_thread_at_a_time() -> None:
    """After N registrations only the latest should be active."""
    tid = uuid4()
    manifests = []
    for i in range(4):
        m = register_materialization(
            thread_id=tid,
            local_path=f"/tmp/habitat/{i}",
            materialization_kind="live_habitat",
            can_rehydrate_from_persistence=True,
        )
        manifests.append(m)

    active = list_manifests(thread_id=tid, materialization_kind="live_habitat", status="active")
    assert len(active) == 1
    assert active[0].manifest_id == manifests[-1].manifest_id


def test_live_habitat_isolation_across_threads() -> None:
    """Each thread has its own active live_habitat; other threads are unaffected."""
    tid_a = uuid4()
    tid_b = uuid4()
    ma = register_materialization(
        thread_id=tid_a,
        local_path="/tmp/habitat/a",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    mb = register_materialization(
        thread_id=tid_b,
        local_path="/tmp/habitat/b",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    assert get_active_live_habitat(tid_a) is not None
    assert get_active_live_habitat(tid_a).manifest_id == ma.manifest_id
    assert get_active_live_habitat(tid_b) is not None
    assert get_active_live_habitat(tid_b).manifest_id == mb.manifest_id


def test_candidate_preview_does_not_supersede_live_habitat() -> None:
    """candidate_preview registrations must not affect the live_habitat for the same thread."""
    tid = uuid4()
    live = register_materialization(
        thread_id=tid,
        local_path="/tmp/habitat/live",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _cp = register_materialization(
        thread_id=tid,
        local_path="/tmp/habitat/preview",
        materialization_kind="candidate_preview",
        can_rehydrate_from_persistence=True,
    )
    snapshot = {m.manifest_id: m for m in registry_snapshot()}
    assert snapshot[live.manifest_id].materialization_status == "active"


# ── G2: superseded habitat becomes eviction-eligible after persistence ───────


def test_superseded_habitat_evicted_when_durable_and_old_enough(
    tmp_path: Path,
) -> None:
    """
    A superseded live_habitat with can_rehydrate_from_persistence=True and an old
    enough created_at must be deleted and its registry status set to 'evicted'.
    """
    tid = uuid4()
    old_dir = tmp_path / "old_habitat"
    old_dir.mkdir()

    # Register first habitat (will be superseded)
    m1 = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    # Register second (supersedes first)
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new_habitat"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )

    # Backdate the superseded manifest's created_at so it is past TTL
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        old_manifest = mod._REGISTRY[m1.manifest_id]
        mod._REGISTRY[m1.manifest_id] = old_manifest.model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, now=time.time())

    assert str(old_dir) in result.evicted
    assert not old_dir.exists()

    evicted_manifests = list_manifests(status="evicted")
    assert any(m.manifest_id == m1.manifest_id for m in evicted_manifests)


def test_superseded_habitat_eviction_emits_correct_event(tmp_path: Path) -> None:
    tid = uuid4()
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    m1 = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m1.manifest_id] = mod._REGISTRY[m1.manifest_id].model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, now=time.time())
    evicted_events = [
        e for e in result.telemetry_events
        if e["event_type"] == RunEventType.HABITAT_EVICTED
    ]
    assert len(evicted_events) == 1
    assert evicted_events[0]["payload"]["thread_id"] == str(tid)
    assert evicted_events[0]["payload"]["can_rehydrate_from_persistence"] is True


# ── G3: candidate preview can rehydrate from persisted state ────────────────


def test_candidate_preview_registered_and_rehydrated() -> None:
    tid = uuid4()
    gid = uuid4()
    m = register_materialization(
        thread_id=tid,
        graph_run_id=gid,
        local_path="/tmp/preview/cp",
        materialization_kind="candidate_preview",
        can_rehydrate_from_persistence=True,
        entrypoint="component/preview/index.html",
    )
    assert m.can_rehydrate_from_persistence is True
    assert m.entrypoint == "component/preview/index.html"

    event = record_rehydration(m.manifest_id, rehydrated_path="/tmp/preview/cp_new")
    assert event["event_type"] == RunEventType.HABITAT_REHYDRATED
    assert event["payload"]["rehydrated_path"] == "/tmp/preview/cp_new"

    snapshot = {em.manifest_id: em for em in registry_snapshot()}
    assert snapshot[m.manifest_id].materialization_status == "active"
    assert snapshot[m.manifest_id].local_path == "/tmp/preview/cp_new"


def test_record_rehydration_without_path_updates_status_only() -> None:
    """record_rehydration with no rehydrated_path must still set status=active."""
    tid = uuid4()
    m = register_materialization(
        thread_id=tid,
        local_path="/tmp/preview/cp",
        materialization_kind="candidate_preview",
        can_rehydrate_from_persistence=True,
    )
    # Supersede so the manifest is not already active
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m.manifest_id] = mod._REGISTRY[m.manifest_id].model_copy(
            update={"materialization_status": "evicted"}
        )

    event = record_rehydration(m.manifest_id)
    assert event["event_type"] == RunEventType.HABITAT_REHYDRATED
    assert event["payload"]["rehydrated_path"] is None

    snapshot = {em.manifest_id: em for em in registry_snapshot()}
    assert snapshot[m.manifest_id].materialization_status == "active"
    assert snapshot[m.manifest_id].local_path == "/tmp/preview/cp"  # unchanged


# ── G4: no eviction when durability/rehydration preconditions fail ───────────


def test_eviction_skipped_when_not_durable(tmp_path: Path) -> None:
    """Materialization with can_rehydrate_from_persistence=False must never be evicted."""
    tid = uuid4()
    old_dir = tmp_path / "fragile"
    old_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=False,  # not durable
    )
    # Supersede it
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m.manifest_id] = mod._REGISTRY[m.manifest_id].model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, now=time.time())

    assert str(old_dir) in result.skipped_not_durable
    assert old_dir.exists()  # not deleted
    not_durable_events = [
        e for e in result.telemetry_events
        if e["event_type"] == RunEventType.HABITAT_EVICTION_SKIPPED_NOT_DURABLE
    ]
    assert len(not_durable_events) == 1


def test_eviction_skipped_for_active_thread(tmp_path: Path) -> None:
    """Superseded habitat belonging to an active thread must not be evicted."""
    tid = uuid4()
    old_dir = tmp_path / "active_thread_old"
    old_dir.mkdir()
    m1 = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m1.manifest_id] = mod._REGISTRY[m1.manifest_id].model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(
        settings,
        active_thread_ids=frozenset({tid}),
        now=time.time(),
    )

    assert str(old_dir) in result.skipped_active_thread
    assert old_dir.exists()
    active_thread_events = [
        e for e in result.telemetry_events
        if e["event_type"] == RunEventType.HABITAT_EVICTION_SKIPPED_ACTIVE_THREAD
    ]
    assert len(active_thread_events) == 1


def test_eviction_disabled_by_config(tmp_path: Path) -> None:
    """When kmbl_habitat_lifecycle_enabled=False, evict_superseded_habitats is a no-op."""
    tid = uuid4()
    old_dir = tmp_path / "noop"
    old_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m.manifest_id] = mod._REGISTRY[m.manifest_id].model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=False,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, now=time.time())
    assert result.evicted == []
    assert old_dir.exists()


def test_eviction_within_ttl_skipped(tmp_path: Path) -> None:
    """Superseded manifest still within TTL must not be evicted."""
    tid = uuid4()
    old_dir = tmp_path / "recent"
    old_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    # created_at is very recent (just now) → within TTL

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, now=time.time())
    assert str(old_dir) not in result.evicted
    assert old_dir.exists()


# ── G5: preview serving mode reflects persisted vs local cache ───────────────


def test_preview_mode_persisted_when_payload_available() -> None:
    mode = resolve_preview_serving_mode(
        local_manifest=None,
        has_persisted_payload=True,
    )
    assert mode == "persisted"


def test_preview_mode_local_cache_when_active_path_exists(tmp_path: Path) -> None:
    tid = uuid4()
    local_dir = tmp_path / "habitat"
    local_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(local_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    mode = resolve_preview_serving_mode(
        local_manifest=m,
        has_persisted_payload=False,
    )
    assert mode == "local_cache"


def test_preview_mode_persisted_takes_priority_over_local_cache(tmp_path: Path) -> None:
    """persisted payload is the canonical source and wins over local_cache."""
    tid = uuid4()
    local_dir = tmp_path / "habitat"
    local_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(local_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    mode = resolve_preview_serving_mode(
        local_manifest=m,
        has_persisted_payload=True,  # persisted wins
    )
    assert mode == "persisted"


def test_preview_mode_degraded_when_neither_available() -> None:
    mode = resolve_preview_serving_mode(
        local_manifest=None,
        has_persisted_payload=False,
    )
    assert mode == "degraded"


def test_preview_mode_degraded_when_local_path_missing() -> None:
    """Active manifest but local_path does not exist → degraded."""
    tid = uuid4()
    m = register_materialization(
        thread_id=tid,
        local_path="/tmp/does_not_exist_xyz",
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    mode = resolve_preview_serving_mode(
        local_manifest=m,
        has_persisted_payload=False,
    )
    assert mode == "degraded"


def test_preview_mode_degraded_when_manifest_superseded(tmp_path: Path) -> None:
    """Superseded manifest must not qualify as local_cache even if path exists."""
    tid = uuid4()
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    m1 = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    snapshot = {m.manifest_id: m for m in registry_snapshot()}
    superseded = snapshot[m1.manifest_id]
    assert superseded.materialization_status == "superseded"

    mode = resolve_preview_serving_mode(
        local_manifest=superseded,
        has_persisted_payload=False,
    )
    assert mode == "degraded"


def test_preview_serving_mode_payload_includes_telemetry_fields(tmp_path: Path) -> None:
    tid = uuid4()
    local_dir = tmp_path / "h"
    local_dir.mkdir()
    m = register_materialization(
        thread_id=tid,
        local_path=str(local_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
        entrypoint="component/preview/index.html",
    )
    payload = preview_serving_mode_payload("local_cache", manifest=m)
    assert payload["preview_serving_mode"] == "local_cache"
    assert payload["materialization_source"] == "live_habitat"
    assert payload["manifest_id"] == str(m.manifest_id)
    assert payload["entrypoint"] == "component/preview/index.html"
    assert payload["materialization_status"] == "active"


def test_preview_serving_mode_payload_no_manifest() -> None:
    payload = preview_serving_mode_payload("persisted")
    assert payload["preview_serving_mode"] == "persisted"
    assert payload["materialization_source"] is None


# ── dry_run mode ─────────────────────────────────────────────────────────────


def test_eviction_dry_run_does_not_delete(tmp_path: Path) -> None:
    tid = uuid4()
    old_dir = tmp_path / "dry"
    old_dir.mkdir()
    m1 = register_materialization(
        thread_id=tid,
        local_path=str(old_dir),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    _m2 = register_materialization(
        thread_id=tid,
        local_path=str(tmp_path / "new"),
        materialization_kind="live_habitat",
        can_rehydrate_from_persistence=True,
    )
    import kmbl_orchestrator.runtime.habitat_lifecycle as mod
    with mod._REGISTRY_LOCK:
        mod._REGISTRY[m1.manifest_id] = mod._REGISTRY[m1.manifest_id].model_copy(
            update={"created_at": "2020-01-01T00:00:00+00:00"}
        )

    settings = Settings.model_construct(
        kmbl_habitat_lifecycle_enabled=True,
        kmbl_habitat_eviction_ttl_days=7.0,
    )
    result = evict_superseded_habitats(settings, dry_run=True, now=time.time())
    assert str(old_dir) in result.evicted
    assert old_dir.exists()  # still on disk — dry run only
