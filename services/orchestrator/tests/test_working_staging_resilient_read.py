"""Resilient working_staging reads for graph nodes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository
from kmbl_orchestrator.runtime.run_events import RunEventType
from kmbl_orchestrator.runtime.working_staging_read import (
    get_working_staging_for_thread_resilient,
)


@pytest.fixture
def supa_repo() -> SupabaseRepository:
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


def test_resilient_returns_none_and_emits_event_on_runtime_error(
    supa_repo: SupabaseRepository,
) -> None:
    tid = uuid4()
    gid = uuid4()
    with patch.object(
        supa_repo,
        "get_working_staging_for_thread",
        side_effect=RuntimeError(
            "SupabaseRepository.get_working_staging_for_thread(working_staging) failed: "
            "APIError: JSON could not be generated"
        ),
    ):
        with patch(
            "kmbl_orchestrator.runtime.working_staging_read.append_graph_run_event"
        ) as ev:
            ws = get_working_staging_for_thread_resilient(
                supa_repo,
                tid,
                graph_run_id=gid,
                phase="generator",
                iteration_index=1,
            )
    assert ws is None
    ev.assert_called_once()
    assert ev.call_args[0][2] == RunEventType.WORKING_STAGING_FETCH_DEGRADED
    payload = ev.call_args[0][3]
    assert payload["phase"] == "generator"
    assert payload["iteration_index"] == 1


def test_in_memory_repository_unchanged() -> None:
    from kmbl_orchestrator.persistence.repository import InMemoryRepository

    repo = InMemoryRepository()
    tid = uuid4()
    assert (
        get_working_staging_for_thread_resilient(
            repo,
            tid,
            graph_run_id=uuid4(),
            phase="generator",
            iteration_index=0,
        )
        is None
    )
