"""``save_build_spec`` idempotency (upsert / ignore duplicate PK under transport retry)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import BuildSpecRecord
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


@pytest.fixture
def build_spec_repo() -> SupabaseRepository:
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


def _sample_build_spec() -> BuildSpecRecord:
    return BuildSpecRecord(
        build_spec_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
        spec_json={"task": "smoke"},
    )


def test_save_build_spec_uses_upsert_ignore_duplicates_on_build_spec_id(
    build_spec_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    build_spec_repo._client.table.return_value = table_chain

    build_spec_repo.save_build_spec(_sample_build_spec())

    build_spec_repo._client.table.assert_called_once_with("build_spec")
    call_kw = table_chain.upsert.call_args[1]
    assert call_kw["on_conflict"] == "build_spec_id"
    assert call_kw["ignore_duplicates"] is True
    row = table_chain.upsert.call_args[0][0]
    assert "build_spec_id" in row
    table_chain.upsert.return_value.execute.assert_called_once()


def test_save_build_spec_repeated_call_same_row_does_not_error(
    build_spec_repo: SupabaseRepository,
) -> None:
    table_chain = MagicMock()
    table_chain.upsert.return_value.execute.return_value = MagicMock(data=[{}])
    build_spec_repo._client.table.return_value = table_chain

    spec = _sample_build_spec()
    build_spec_repo.save_build_spec(spec)
    build_spec_repo.save_build_spec(spec)

    assert table_chain.upsert.call_count == 2


def test_save_build_spec_unrelated_api_error_still_fails(
    build_spec_repo: SupabaseRepository,
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
    build_spec_repo._client.table.return_value = table_chain

    with pytest.raises(RuntimeError, match=r"SupabaseRepository\.save_build_spec"):
        build_spec_repo.save_build_spec(_sample_build_spec())
