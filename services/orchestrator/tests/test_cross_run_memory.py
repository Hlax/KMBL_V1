"""Cross-run memory: write rules, taste aggregation, bias, repository merge."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    GraphRunRecord,
    IdentityCrossRunMemoryRecord,
    ThreadRecord,
)
from kmbl_orchestrator.memory.guardrails import clamp_strength, effective_strength_at_read
from kmbl_orchestrator.memory.keys import KEY_AGGREGATE_RUN_OUTCOME, KEY_PREFERRED_EXPERIENCE_MODE
from kmbl_orchestrator.memory.ops import memory_bias_for_experience_mode
from kmbl_orchestrator.memory.taste import build_taste_profile
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def _settings() -> Settings:
    return Settings()


def test_in_memory_upsert_merge_by_triple() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    r1 = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=uuid4(),
        identity_id=iid,
        category="run_outcome",
        memory_key=KEY_AGGREGATE_RUN_OUTCOME,
        payload_json={"run_count": 1},
        strength=0.3,
        provenance="test",
        source_graph_run_id=None,
        operator_signal=None,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(r1)
    r2 = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=uuid4(),
        identity_id=iid,
        category="run_outcome",
        memory_key=KEY_AGGREGATE_RUN_OUTCOME,
        payload_json={"run_count": 2},
        strength=0.5,
        provenance="test2",
        source_graph_run_id=None,
        operator_signal=None,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(r2)
    got = repo.get_identity_cross_run_memory(iid, "run_outcome", KEY_AGGREGATE_RUN_OUTCOME)
    assert got is not None
    assert got.payload_json["run_count"] == 2
    assert got.strength == 0.5


def test_operator_confirmed_wins_taste_for_mode() -> None:
    settings = _settings()
    iid = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        IdentityCrossRunMemoryRecord(
            identity_cross_run_memory_id=uuid4(),
            identity_id=iid,
            category="run_outcome",
            memory_key=KEY_PREFERRED_EXPERIENCE_MODE,
            payload_json={"experience_mode": "flat_standard"},
            strength=0.9,
            provenance="run",
            created_at=now,
            updated_at=now,
        ),
        IdentityCrossRunMemoryRecord(
            identity_cross_run_memory_id=uuid4(),
            identity_id=iid,
            category="operator_confirmed",
            memory_key=KEY_PREFERRED_EXPERIENCE_MODE,
            payload_json={"experience_mode": "immersive_spatial_portfolio"},
            strength=0.8,
            provenance="operator",
            operator_signal="staging_approved",
            created_at=now,
            updated_at=now,
        ),
    ]
    taste = build_taste_profile(rows, settings)
    assert taste.operator_confirmed_experience_mode == "immersive_spatial_portfolio"
    assert taste.favored_experience_modes[0][0] == "immersive_spatial_portfolio"


def test_memory_bias_only_when_identity_ambiguous() -> None:
    settings = _settings()
    taste = {
        "operator_confirmed_experience_mode": "immersive_spatial_portfolio",
        "operator_confirmed_strength": 0.9,
        "favored_experience_modes": [],
    }
    # Empty structured identity → derive_experience_mode confidence is low (default flat ~0.4)
    mode, reason = memory_bias_for_experience_mode(
        structured_identity=None,
        taste_summary=taste,
        settings=settings,
    )
    assert mode == "immersive_spatial_portfolio"
    assert reason == "operator_confirmed_experience_mode"


def test_effective_strength_decay() -> None:
    settings = _settings()
    old = "2020-01-01T00:00:00+00:00"
    eff = effective_strength_at_read(1.0, old, settings)
    assert eff < 0.5


def test_clamp_strength() -> None:
    assert clamp_strength(1.5) == 1.0
    assert clamp_strength(-0.1) == 0.0


def test_list_by_source_graph_run() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    gid = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    r = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=uuid4(),
        identity_id=iid,
        category="run_outcome",
        memory_key=KEY_AGGREGATE_RUN_OUTCOME,
        payload_json={},
        strength=0.2,
        provenance="x",
        source_graph_run_id=gid,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(r)
    rows = repo.list_identity_cross_run_memory_by_source_run(gid)
    assert len(rows) == 1
    assert rows[0].memory_key == KEY_AGGREGATE_RUN_OUTCOME


def test_graph_run_record_identity_for_detail_taste() -> None:
    """Detail endpoint uses thread.identity_id for taste when graph_run.identity_id unset."""
    repo = InMemoryRepository()
    tid = uuid4()
    gid = uuid4()
    iid = uuid4()
    repo.ensure_thread(
        ThreadRecord(
            thread_id=tid,
            identity_id=iid,
            thread_kind="build",
            status="active",
        )
    )
    repo.save_graph_run(
        GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            identity_id=None,
            trigger_type="prompt",
            status="completed",
            started_at="2026-03-29T10:00:00+00:00",
            ended_at="2026-03-29T10:05:00+00:00",
        )
    )
    now = datetime.now(timezone.utc).isoformat()
    repo.upsert_identity_cross_run_memory(
        IdentityCrossRunMemoryRecord(
            identity_cross_run_memory_id=uuid4(),
            identity_id=iid,
            category="operator_confirmed",
            memory_key=KEY_PREFERRED_EXPERIENCE_MODE,
            payload_json={"experience_mode": "webgl_3d_portfolio"},
            strength=0.9,
            provenance="op",
            operator_signal="publication_created",
            created_at=now,
            updated_at=now,
        )
    )
    rows = repo.list_identity_cross_run_memory(iid, limit=20)
    taste = build_taste_profile(rows, _settings())
    assert taste.operator_confirmed_experience_mode == "webgl_3d_portfolio"
