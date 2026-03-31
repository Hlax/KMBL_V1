"""``save_graph_run_event`` idempotency (insert with duplicate key handling)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import GraphRunEventRecord
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


@pytest.fixture
def event_repo() -> SupabaseRepository:
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


def _sample_event() -> GraphRunEventRecord:
    return GraphRunEventRecord(
        graph_run_event_id=uuid4(),
        graph_run_id=uuid4(),
        event_type="checkpoint_written",
        payload_json={"checkpoint_id": str(uuid4())},
    )


def test_save_graph_run_event_uses_insert(
    event_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.insert.return_value.execute.return_value = MagicMock(data=[{}])
    event_repo._client.table.return_value = table_chain

    with patch.object(
        event_repo,
        "_next_graph_run_event_sequence_index",
        return_value=None,
    ):
        event_repo.save_graph_run_event(_sample_event())

    event_repo._client.table.assert_called_once_with("graph_run_event")
    table_chain.insert.assert_called_once()
    row = table_chain.insert.call_args[0][0]
    assert "graph_run_event_id" in row
    table_chain.insert.return_value.execute.assert_called_once()


def test_save_graph_run_event_duplicate_key_ignored(
    event_repo: SupabaseRepository,
) -> None:
    """Duplicate key (23505) is logged but not raised for append-only events."""
    table_chain = MagicMock()
    table_chain.insert.return_value.execute.side_effect = APIError(
        {
            "code": "23505",
            "message": "duplicate key value violates unique constraint",
            "details": None,
            "hint": None,
        }
    )
    event_repo._client.table.return_value = table_chain

    with patch.object(
        event_repo,
        "_next_graph_run_event_sequence_index",
        return_value=None,
    ):
        # Should not raise - duplicate key is silently ignored
        event_repo.save_graph_run_event(_sample_event())


def test_save_graph_run_event_unrelated_api_error_still_fails(
    event_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.insert.return_value.execute.side_effect = APIError(
        {
            "code": "PGRST301",
            "message": "unexpected database error",
            "details": None,
            "hint": None,
        }
    )
    event_repo._client.table.return_value = table_chain

    with patch.object(
        event_repo,
        "_next_graph_run_event_sequence_index",
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_graph_run_event"):
            event_repo.save_graph_run_event(_sample_event())
