"""``save_graph_run_event`` idempotency (upsert / ignore duplicate PK under transport retry)."""

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


def test_save_graph_run_event_uses_upsert_ignore_duplicates_on_event_id(
    event_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    event_repo._client.table.return_value = table_chain

    event_repo.save_graph_run_event(_sample_event())

    event_repo._client.table.assert_called_once_with("graph_run_event")
    call_kw = table_chain.upsert.call_args[1]
    assert call_kw["on_conflict"] == "graph_run_event_id"
    assert call_kw["ignore_duplicates"] is True
    row = table_chain.upsert.call_args[0][0]
    assert "graph_run_event_id" in row
    table_chain.upsert.return_value.execute.assert_called_once()


def test_save_graph_run_event_repeated_call_same_row_does_not_error(
    event_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    event_repo._client.table.return_value = table_chain

    ev = _sample_event()
    event_repo.save_graph_run_event(ev)
    event_repo.save_graph_run_event(ev)

    assert table_chain.upsert.call_count == 2


def test_save_graph_run_event_unrelated_api_error_still_fails(
    event_repo: SupabaseRepository,
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
    event_repo._client.table.return_value = table_chain

    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_graph_run_event"):
        event_repo.save_graph_run_event(_sample_event())
