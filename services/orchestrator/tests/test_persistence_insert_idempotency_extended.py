"""Idempotent upserts for remaining client-PK inserts (same pattern as checkpoint / graph_run_event / build_spec)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    EvaluationReportRecord,
    IdentitySourceRecord,
    PublicationSnapshotRecord,
    RoleInvocationRecord,
    StagingSnapshotRecord,
)
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


@pytest.fixture
def repo() -> SupabaseRepository:
    with patch(
        "kmbl_orchestrator.persistence.supabase_repository.create_client",
        return_value=MagicMock(),
    ):
        return SupabaseRepository(
            Settings(
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="test-service-role",
            )
        )


def _assert_upsert_pk(table_chain: MagicMock, *, table: str, pk: str, client: MagicMock) -> None:
    client.table.assert_called_once_with(table)
    call_kw = table_chain.upsert.call_args[1]
    assert call_kw["on_conflict"] == pk
    assert call_kw["ignore_duplicates"] is True
    row = table_chain.upsert.call_args[0][0]
    assert pk in row


# --- role_invocation ---


def _sample_role_invocation() -> RoleInvocationRecord:
    return RoleInvocationRecord(
        role_invocation_id=uuid4(),
        graph_run_id=uuid4(),
        thread_id=uuid4(),
        role_type="planner",
        provider_config_key="kmbl-planner",
        input_payload_json={},
        status="completed",
    )


def test_save_role_invocation_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.save_role_invocation(_sample_role_invocation())
    _assert_upsert_pk(tc, table="role_invocation", pk="role_invocation_id", client=repo._client)


def test_save_role_invocation_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    inv = _sample_role_invocation()
    repo.save_role_invocation(inv)
    repo.save_role_invocation(inv)
    assert tc.upsert.call_count == 2


def test_save_role_invocation_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_role_invocation"):
        repo.save_role_invocation(_sample_role_invocation())


# --- build_candidate ---


def _sample_build_candidate() -> BuildCandidateRecord:
    return BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        working_state_patch_json={},
        artifact_refs_json=[],
    )


def test_save_build_candidate_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.save_build_candidate(_sample_build_candidate())
    _assert_upsert_pk(tc, table="build_candidate", pk="build_candidate_id", client=repo._client)


def test_save_build_candidate_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    rec = _sample_build_candidate()
    repo.save_build_candidate(rec)
    repo.save_build_candidate(rec)
    assert tc.upsert.call_count == 2


def test_save_build_candidate_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_build_candidate"):
        repo.save_build_candidate(_sample_build_candidate())


# --- evaluation_report ---


def _sample_evaluation_report() -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="pass",
    )


def test_save_evaluation_report_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.save_evaluation_report(_sample_evaluation_report())
    _assert_upsert_pk(tc, table="evaluation_report", pk="evaluation_report_id", client=repo._client)


def test_save_evaluation_report_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    rec = _sample_evaluation_report()
    repo.save_evaluation_report(rec)
    repo.save_evaluation_report(rec)
    assert tc.upsert.call_count == 2


def test_save_evaluation_report_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_evaluation_report"):
        repo.save_evaluation_report(_sample_evaluation_report())


# --- staging_snapshot ---


def _sample_staging_snapshot() -> StagingSnapshotRecord:
    return StagingSnapshotRecord(
        staging_snapshot_id=uuid4(),
        thread_id=uuid4(),
        build_candidate_id=uuid4(),
        snapshot_payload_json={"k": 1},
    )


def test_save_staging_snapshot_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.save_staging_snapshot(_sample_staging_snapshot())
    _assert_upsert_pk(tc, table="staging_snapshot", pk="staging_snapshot_id", client=repo._client)


def test_save_staging_snapshot_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    rec = _sample_staging_snapshot()
    repo.save_staging_snapshot(rec)
    repo.save_staging_snapshot(rec)
    assert tc.upsert.call_count == 2


def test_save_staging_snapshot_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_staging_snapshot"):
        repo.save_staging_snapshot(_sample_staging_snapshot())


# --- publication_snapshot ---


def _sample_publication_snapshot() -> PublicationSnapshotRecord:
    return PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=uuid4(),
        payload_json={},
    )


def test_save_publication_snapshot_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.save_publication_snapshot(_sample_publication_snapshot())
    _assert_upsert_pk(tc, table="publication_snapshot", pk="publication_snapshot_id", client=repo._client)


def test_save_publication_snapshot_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    rec = _sample_publication_snapshot()
    repo.save_publication_snapshot(rec)
    repo.save_publication_snapshot(rec)
    assert tc.upsert.call_count == 2


def test_save_publication_snapshot_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_publication_snapshot"):
        repo.save_publication_snapshot(_sample_publication_snapshot())


# --- identity_source ---


def _sample_identity_source() -> IdentitySourceRecord:
    return IdentitySourceRecord(
        identity_source_id=uuid4(),
        identity_id=uuid4(),
        source_type="doc",
    )


def test_create_identity_source_uses_upsert_ignore_duplicates(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    repo.create_identity_source(_sample_identity_source())
    _assert_upsert_pk(tc, table="identity_source", pk="identity_source_id", client=repo._client)


def test_create_identity_source_repeated_call_same_row(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    repo._client.table.return_value = tc
    rec = _sample_identity_source()
    repo.create_identity_source(rec)
    repo.create_identity_source(rec)
    assert tc.upsert.call_count == 2


def test_create_identity_source_unrelated_api_error(repo: SupabaseRepository) -> None:
    tc = MagicMock()
    tc.upsert.return_value.execute.side_effect = APIError(
        {"code": "PGRST301", "message": "x", "details": None, "hint": None}
    )
    repo._client.table.return_value = tc
    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.create_identity_source"):
        repo.create_identity_source(_sample_identity_source())
