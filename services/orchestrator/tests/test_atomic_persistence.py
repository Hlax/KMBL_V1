"""Atomic staging persistence: in-memory transaction semantics + Supabase RPC wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    PublicationSnapshotRecord,
    StagingCheckpointRecord,
    StagingSnapshotRecord,
    ThreadRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.persistence.exceptions import WriteSnapshotNotSupportedError
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository
from kmbl_orchestrator.runtime.operator_action_read_model import OPERATOR_TRIGGERED_EVENT_TYPES
from kmbl_orchestrator.runtime.run_events import RunEventType


def _minimal_ws(thread_id, ws_id) -> WorkingStagingRecord:
    return WorkingStagingRecord(
        working_staging_id=ws_id,
        thread_id=thread_id,
        revision=1,
        status="review_ready",
    )


def _minimal_cp(ws: WorkingStagingRecord) -> StagingCheckpointRecord:
    return StagingCheckpointRecord(
        staging_checkpoint_id=uuid4(),
        working_staging_id=ws.working_staging_id,
        thread_id=ws.thread_id,
        revision_at_checkpoint=ws.revision,
        trigger="post_patch",
    )


def _minimal_snap(thread_id, bc_id, gr_id) -> StagingSnapshotRecord:
    return StagingSnapshotRecord(
        staging_snapshot_id=uuid4(),
        thread_id=thread_id,
        build_candidate_id=bc_id,
        graph_run_id=gr_id,
        snapshot_payload_json={"k": 1},
    )


def test_in_memory_atomic_persist_all_or_nothing() -> None:
    tid = uuid4()
    ws_id = uuid4()
    bc_id = uuid4()
    gr_id = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, identity_id=None))
    ws = _minimal_ws(tid, ws_id)
    cp = _minimal_cp(ws)
    snap = _minimal_snap(tid, bc_id, gr_id)

    def _boom(_: StagingSnapshotRecord) -> None:
        raise RuntimeError("simulated failure")

    repo.save_staging_snapshot = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated"):
        repo.atomic_persist_staging_node_writes(
            checkpoints=[cp],
            working_staging=ws,
            staging_snapshot=snap,
        )

    assert repo.get_staging_checkpoint(cp.staging_checkpoint_id) is None
    assert repo.get_working_staging_for_thread(tid) is None


def test_in_memory_atomic_persist_success() -> None:
    tid = uuid4()
    ws_id = uuid4()
    bc_id = uuid4()
    gr_id = uuid4()
    repo = InMemoryRepository()
    repo.ensure_thread(ThreadRecord(thread_id=tid, identity_id=None))
    ws = _minimal_ws(tid, ws_id)
    cp = _minimal_cp(ws)
    snap = _minimal_snap(tid, bc_id, gr_id)
    repo.atomic_persist_staging_node_writes(
        checkpoints=[cp],
        working_staging=ws,
        staging_snapshot=snap,
    )
    assert repo.get_staging_checkpoint(cp.staging_checkpoint_id) is not None
    assert repo.get_working_staging_for_thread(tid) is not None
    assert repo.get_staging_snapshot(snap.staging_snapshot_id) is not None


def test_in_memory_atomic_approve_all_or_nothing() -> None:
    tid = uuid4()
    ws_id = uuid4()
    repo = InMemoryRepository()
    ws = _minimal_ws(tid, ws_id)
    cp = StagingCheckpointRecord(
        staging_checkpoint_id=uuid4(),
        working_staging_id=ws.working_staging_id,
        thread_id=ws.thread_id,
        trigger="pre_approval",
    )
    pub = PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=uuid4(),
        thread_id=tid,
        payload_json={},
    )

    def _boom(_: PublicationSnapshotRecord) -> None:
        raise RuntimeError("pub fail")

    repo.save_publication_snapshot = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="pub fail"):
        repo.atomic_commit_working_staging_approval(
            checkpoint=cp, publication=pub, working_staging=ws,
        )

    assert repo.get_staging_checkpoint(cp.staging_checkpoint_id) is None


@patch("kmbl_orchestrator.persistence.supabase_repository.create_client")
def test_supabase_atomic_staging_node_calls_rpc(mock_create: MagicMock) -> None:
    mock_client = MagicMock()
    mock_create.return_value = mock_client
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)

    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
    )
    repo = SupabaseRepository(settings)
    tid = uuid4()
    ws_id = uuid4()
    bc_id = uuid4()
    gr_id = uuid4()
    ws = _minimal_ws(tid, ws_id)
    cp = _minimal_cp(ws)
    snap = _minimal_snap(tid, bc_id, gr_id)

    repo.atomic_persist_staging_node_writes(
        checkpoints=[cp],
        working_staging=ws,
        staging_snapshot=snap,
    )

    mock_client.rpc.assert_called_once()
    call_name, call_kwargs = mock_client.rpc.call_args[0][0], mock_client.rpc.call_args[0][1]
    assert call_name == "kmbl_atomic_staging_node_persist"
    assert call_kwargs["p_thread_id"] == str(tid)
    assert len(call_kwargs["p_checkpoints"]) == 1
    assert call_kwargs["p_checkpoints"][0]["staging_checkpoint_id"] == str(cp.staging_checkpoint_id)
    assert call_kwargs["p_working_staging"]["working_staging_id"] == str(ws_id)
    assert call_kwargs["p_staging_snapshot"]["staging_snapshot_id"] == str(snap.staging_snapshot_id)


@patch("kmbl_orchestrator.persistence.supabase_repository.create_client")
def test_supabase_save_working_staging_uses_locked_upsert_rpc(mock_create: MagicMock) -> None:
    mock_client = MagicMock()
    mock_create.return_value = mock_client
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)

    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
    )
    repo = SupabaseRepository(settings)
    tid = uuid4()
    ws = _minimal_ws(tid, uuid4())
    repo.save_working_staging(ws)

    mock_client.rpc.assert_called_once()
    name, params = mock_client.rpc.call_args[0]
    assert name == "kmbl_atomic_upsert_working_staging"
    assert params["p_thread_id"] == str(tid)
    assert params["p_working_staging"]["working_staging_id"] == str(ws.working_staging_id)


@patch("kmbl_orchestrator.persistence.supabase_repository.create_client")
def test_supabase_atomic_approve_calls_rpc(mock_create: MagicMock) -> None:
    mock_client = MagicMock()
    mock_create.return_value = mock_client
    mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)

    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
    )
    repo = SupabaseRepository(settings)
    tid = uuid4()
    ws = _minimal_ws(tid, uuid4())
    cp = StagingCheckpointRecord(
        staging_checkpoint_id=uuid4(),
        working_staging_id=ws.working_staging_id,
        thread_id=tid,
        trigger="pre_approval",
    )
    pub = PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=uuid4(),
        thread_id=tid,
        payload_json={},
    )
    repo.atomic_commit_working_staging_approval(
        checkpoint=cp, publication=pub, working_staging=ws,
    )
    mock_client.rpc.assert_called_once()
    name, _params = mock_client.rpc.call_args[0]
    assert name == "kmbl_atomic_working_staging_approve"


def test_supabase_in_memory_write_snapshot_raises() -> None:
    with patch("kmbl_orchestrator.persistence.supabase_repository.create_client") as mock_create:
        mock_create.return_value = MagicMock()
        settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="test-key",
        )
        repo = SupabaseRepository(settings)
        with pytest.raises(WriteSnapshotNotSupportedError):
            with repo.in_memory_write_snapshot():
                pass  # pragma: no cover


def test_operator_triggered_event_types_include_staging_mutations() -> None:
    assert RunEventType.WORKING_STAGING_ROLLBACK in OPERATOR_TRIGGERED_EVENT_TYPES
    assert RunEventType.OPERATOR_REVIEW_SNAPSHOT_MATERIALIZED in OPERATOR_TRIGGERED_EVENT_TYPES
    assert RunEventType.PUBLICATION_SNAPSHOT_CREATED in OPERATOR_TRIGGERED_EVENT_TYPES