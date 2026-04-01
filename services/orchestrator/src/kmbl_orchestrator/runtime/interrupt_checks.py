"""Cooperative interrupt: read persisted request and raise at graph boundaries."""

from __future__ import annotations

from uuid import UUID

from kmbl_orchestrator.domain import ACTIVE_GRAPH_RUN_STATUSES
from kmbl_orchestrator.errors import RunInterrupted
from kmbl_orchestrator.persistence.repository import Repository


def raise_if_interrupt_requested(
    repo: Repository,
    graph_run_id: UUID,
    thread_id: UUID,
) -> None:
    gr = repo.get_graph_run(graph_run_id)
    if gr is None:
        return
    if gr.status == "interrupt_requested":
        raise RunInterrupted(graph_run_id=graph_run_id, thread_id=thread_id)
    if gr.interrupt_requested_at is not None:
        raise RunInterrupted(graph_run_id=graph_run_id, thread_id=thread_id)
