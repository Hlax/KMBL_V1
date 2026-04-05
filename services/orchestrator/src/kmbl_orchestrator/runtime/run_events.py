"""Append-only graph_run execution timeline (DB-backed when available)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import GraphRunEventRecord
from kmbl_orchestrator.persistence.repository import Repository

# Process-local counter for observability (normalization repair paths).
_normalization_rescue_total = 0


def normalization_rescue_event_total() -> int:
    """Total NORMALIZATION_RESCUE events appended in this process (resets on restart)."""
    return _normalization_rescue_total


class RunEventType:
    GRAPH_RUN_STARTED = "graph_run_started"
    GRAPH_RUN_RESUMED = "graph_run_resumed"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    PLANNER_INVOCATION_STARTED = "planner_invocation_started"
    PLANNER_INVOCATION_COMPLETED = "planner_invocation_completed"
    PLANNER_WIRE_CANONICALIZED = "planner_wire_canonicalized"
    STATIC_VERTICAL_EXPERIENCE_MODE_CLAMPED = "static_vertical_experience_mode_clamped"
    GENERATOR_INVOCATION_STARTED = "generator_invocation_started"
    GENERATOR_INVOCATION_COMPLETED = "generator_invocation_completed"
    GENERATOR_STATIC_BUNDLE_REJECTED = "generator_static_bundle_rejected"
    EVALUATOR_INVOCATION_STARTED = "evaluator_invocation_started"
    EVALUATOR_INVOCATION_COMPLETED = "evaluator_invocation_completed"
    EVALUATOR_SKIPPED_NO_ARTIFACTS = "evaluator_skipped_no_artifacts"
    DECISION_MADE = "decision_made"
    GRAPH_RUN_COMPLETED = "graph_run_completed"
    GRAPH_RUN_FAILED = "graph_run_failed"
    STAGING_SNAPSHOT_CREATED = "staging_snapshot_created"
    STAGING_SNAPSHOT_SKIPPED = "staging_snapshot_skipped"
    STAGING_SNAPSHOT_BLOCKED = "staging_snapshot_blocked"
    STAGING_SNAPSHOT_APPROVED = "staging_snapshot_approved"
    STAGING_SNAPSHOT_UNAPPROVED = "staging_snapshot_unapproved"
    STAGING_SNAPSHOT_REJECTED = "staging_snapshot_rejected"
    STAGING_SNAPSHOT_RATED = "staging_snapshot_rated"
    PUBLICATION_SNAPSHOT_CREATED = "publication_snapshot_created"
    WORKING_STAGING_UPDATED = "working_staging_updated"
    WORKING_STAGING_CHECKPOINT_CREATED = "working_staging_checkpoint_created"
    WORKING_STAGING_ROLLBACK = "working_staging_rollback"
    OPERATOR_REVIEW_SNAPSHOT_MATERIALIZED = "operator_review_snapshot_materialized"

    # Hardening events
    OPENCLAW_RETRY = "openclaw_retry"
    CONTRACT_WARNING = "contract_warning"
    PERSISTENCE_RETRY = "persistence_retry"
    POST_INVOKE_FAILURE = "post_invoke_failure"

    # Iteration events
    ITERATION_STARTED = "iteration_started"
    DECISION_ITERATE = "decision_iterate"
    DECISION_STAGE = "decision_stage"

    # Normalization observability
    NORMALIZATION_RESCUE = "normalization_rescue"
    NORMALIZATION_ENRICHMENT = "normalization_enrichment"

    # Identity feedback loop
    IDENTITY_FEEDBACK_UPSERT = "identity_feedback_upsert"

    # Cross-run memory (inspectable provenance)
    CROSS_RUN_MEMORY_LOADED = "cross_run_memory_loaded"
    CROSS_RUN_MEMORY_UPDATED = "cross_run_memory_updated"

    # Context hydration observability
    CONTEXT_IDENTITY_ABSENT = "context_identity_absent"

    # Decision observability — degraded staging (fail/partial at max iterations)
    DEGRADED_STAGING = "degraded_staging"

    # Cooperative operator interrupt (persisted lifecycle)
    INTERRUPT_REQUESTED = "interrupt_requested"
    INTERRUPT_ACKNOWLEDGED = "interrupt_acknowledged"
    GRAPH_RUN_INTERRUPTED = "graph_run_interrupted"
    DUPLICATE_START_BLOCKED = "duplicate_start_blocked"

    # Crawl frontier observability
    CRAWL_FRONTIER_ADVANCED = "crawl_frontier_advanced"
    PLANNER_CRAWL_COMPLIANCE = "planner_crawl_compliance"


def append_graph_run_event(
    repo: Repository,
    graph_run_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    thread_id: UUID | None = None,
) -> None:
    global _normalization_rescue_total
    if event_type == RunEventType.NORMALIZATION_RESCUE:
        _normalization_rescue_total += 1
    repo.save_graph_run_event(
        GraphRunEventRecord(
            graph_run_event_id=uuid4(),
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            event_type=event_type,
            payload_json=dict(payload) if payload else {},
        )
    )
