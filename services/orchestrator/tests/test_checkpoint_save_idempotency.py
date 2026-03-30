"""Checkpoint ``save_checkpoint`` idempotency (upsert / ignore duplicate PK under transport retry)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


@pytest.fixture
def checkpoint_repo() -> SupabaseRepository:
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


def _sample_checkpoint() -> CheckpointRecord:
    return CheckpointRecord(
        checkpoint_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        checkpoint_kind="pre_role",
        state_json={"k": 1},
    )


def test_save_checkpoint_uses_upsert_ignore_duplicates_on_checkpoint_id(
    checkpoint_repo: SupabaseRepository,
) -> None:
    """PostgREST upsert + ignore-duplicates avoids ``23505`` when the same row is written twice."""
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    checkpoint_repo._client.table.return_value = table_chain

    checkpoint_repo.save_checkpoint(_sample_checkpoint())

    checkpoint_repo._client.table.assert_called_once_with("checkpoint")
    call_kw = table_chain.upsert.call_args[1]
    assert call_kw["on_conflict"] == "checkpoint_id"
    assert call_kw["ignore_duplicates"] is True
    row = table_chain.upsert.call_args[0][0]
    assert "checkpoint_id" in row
    table_chain.upsert.return_value.execute.assert_called_once()


def test_save_checkpoint_repeated_call_same_row_does_not_error(
    checkpoint_repo: SupabaseRepository,
) -> None:
    """Simulate retry: two ``save_checkpoint`` calls with identical row — upsert ignores duplicate."""
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    checkpoint_repo._client.table.return_value = table_chain

    cp = _sample_checkpoint()
    checkpoint_repo.save_checkpoint(cp)
    checkpoint_repo.save_checkpoint(cp)

    assert table_chain.upsert.call_count == 2
    assert table_chain.upsert.return_value.execute.call_count == 2


def test_save_checkpoint_unrelated_api_error_still_fails(
    checkpoint_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.side_effect = APIError(
        {
            "code": "PGRST301",
            "message": "unexpected database error",
            "details": None,
            "hint": None,
        }
    )
    checkpoint_repo._client.table.return_value = table_chain

    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_checkpoint"):
        checkpoint_repo.save_checkpoint(_sample_checkpoint())


def test_save_checkpoint_does_not_swallow_checkpoint_23505_if_raised(
    checkpoint_repo: SupabaseRepository,
) -> None:
    """If PostgREST still returned 23505 (should be rare with upsert), surface it — not masked here."""
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.side_effect = APIError(
        {
            "code": "23505",
            "message": "duplicate key value violates unique constraint",
            "details": "Key (checkpoint_id)=(...) already exists.",
            "hint": None,
        }
    )
    checkpoint_repo._client.table.return_value = table_chain

    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_checkpoint"):
        checkpoint_repo.save_checkpoint(_sample_checkpoint())
