"""graph_run_event duplicate PK handling (transport retry after successful insert)."""

from __future__ import annotations

from kmbl_orchestrator.persistence.supabase_repository import (
    _is_duplicate_graph_run_event_pkey,
)


def test_duplicate_pkey_detected_from_postgrest_error() -> None:
    msg = (
        "SupabaseRepository.save_graph_run_event(graph_run_event) failed: APIError: "
        "{'code': '23505', 'details': "
        "'Key (graph_run_event_id)=(2c584469-fa8c-49fb-af47-a5fd6f81eea8) already exists.', "
        "'message': 'duplicate key value violates unique constraint \"graph_run_event_pkey\"'}"
    )
    assert _is_duplicate_graph_run_event_pkey(RuntimeError(msg)) is True


def test_non_duplicate_23505_not_treated_as_pkey() -> None:
    msg = (
        "failed: {'code': '23505', 'details': "
        "'Key (graph_run_id, sequence_index)=(a, 1) already exists.'}"
    )
    assert _is_duplicate_graph_run_event_pkey(RuntimeError(msg)) is False
