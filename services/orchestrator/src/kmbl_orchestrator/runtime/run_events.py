"""Append-only graph_run execution timeline (DB-backed when available)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import GraphRunEventRecord
from kmbl_orchestrator.persistence.repository import Repository


class RunEventType:
    GRAPH_RUN_STARTED = "graph_run_started"
    GRAPH_RUN_RESUMED = "graph_run_resumed"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    PLANNER_INVOCATION_STARTED = "planner_invocation_started"
    PLANNER_INVOCATION_COMPLETED = "planner_invocation_completed"
    GENERATOR_INVOCATION_STARTED = "generator_invocation_started"
    GENERATOR_INVOCATION_COMPLETED = "generator_invocation_completed"
    EVALUATOR_INVOCATION_STARTED = "evaluator_invocation_started"
    EVALUATOR_INVOCATION_COMPLETED = "evaluator_invocation_completed"
    DECISION_MADE = "decision_made"
    GRAPH_RUN_COMPLETED = "graph_run_completed"
    GRAPH_RUN_FAILED = "graph_run_failed"
    STAGING_SNAPSHOT_CREATED = "staging_snapshot_created"
    STAGING_SNAPSHOT_BLOCKED = "staging_snapshot_blocked"
    STAGING_SNAPSHOT_APPROVED = "staging_snapshot_approved"
    STAGING_SNAPSHOT_UNAPPROVED = "staging_snapshot_unapproved"
    STAGING_SNAPSHOT_REJECTED = "staging_snapshot_rejected"
    STAGING_SNAPSHOT_RATED = "staging_snapshot_rated"
    PUBLICATION_SNAPSHOT_CREATED = "publication_snapshot_created"
    WORKING_STAGING_UPDATED = "working_staging_updated"
    WORKING_STAGING_CHECKPOINT_CREATED = "working_staging_checkpoint_created"
    WORKING_STAGING_ROLLBACK = "working_staging_rollback"

    # Hardening events
    KILOCLAW_RETRY = "kiloclaw_retry"
    CONTRACT_WARNING = "contract_warning"
    PERSISTENCE_RETRY = "persistence_retry"
    POST_INVOKE_FAILURE = "post_invoke_failure"

    # Iteration events
    ITERATION_STARTED = "iteration_started"
    DECISION_ITERATE = "decision_iterate"
    DECISION_STAGE = "decision_stage"


def append_graph_run_event(
    repo: Repository,
    graph_run_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    thread_id: UUID | None = None,
) -> None:
    repo.save_graph_run_event(
        GraphRunEventRecord(
            graph_run_event_id=uuid4(),
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            event_type=event_type,
            payload_json=dict(payload) if payload else {},
        )
    )
