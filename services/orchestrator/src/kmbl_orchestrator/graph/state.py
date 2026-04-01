"""LangGraph state shape — docs/08_LANGGRAPH_ORCHESTRATOR_SPECIFICATION.md §2."""

from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    thread_id: str
    graph_run_id: str
    identity_id: str | None
    trigger_type: str
    event_input: dict[str, Any]

    identity_context: dict[str, Any]
    memory_context: dict[str, Any]
    current_state: dict[str, Any]
    compacted_context: dict[str, Any]

    # Identity brief: orchestrator-built, injected directly into generator and evaluator.
    # Not planner-mediated — survives planner reinterpretation.
    identity_brief: dict[str, Any] | None

    build_spec: dict[str, Any] | None
    build_candidate: dict[str, Any] | None
    evaluation_report: dict[str, Any] | None

    build_spec_id: str | None
    build_candidate_id: str | None
    evaluation_report_id: str | None

    # Evaluator nomination for review snapshot rows (from raw kmbl-evaluator JSON).
    evaluator_nomination: dict[str, Any] | None

    iteration_index: int
    max_iterations: int

    # Accumulated count of consecutive evaluator "pass" decisions within this run.
    # Used for quality-based early termination: once the output reaches "pass",
    # the decision_router routes to staging immediately, so this counter supports
    # future policy changes (e.g. "require two consecutive passes before staging").
    pass_count: int

    # Identity alignment tracking across iterations within a run.
    # alignment_score_history: list of (iteration_index, score) tuples as dicts.
    alignment_score_history: list[dict[str, Any]]
    # Most recent alignment score, echoed here for decision routing convenience.
    last_alignment_score: float | None

    # Retry direction: set by decision_router on iteration, consumed by planner on retry.
    # One of: "refine" | "pivot_layout" | "pivot_palette" | "pivot_content" | "fresh_start"
    retry_direction: str | None
    # Iteration-specific planner context set by orchestrator (not agent).
    # Contains: retry_direction, prior_alignment_score, failed_criteria_ids, iteration_index.
    retry_context: dict[str, Any] | None

    decision: str | None
    interrupt_reason: str | None
    status: str

    staging_snapshot_id: str | None
    working_staging_id: str | None
