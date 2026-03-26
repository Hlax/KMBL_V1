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

    build_spec: dict[str, Any] | None
    build_candidate: dict[str, Any] | None
    evaluation_report: dict[str, Any] | None

    build_spec_id: str | None
    build_candidate_id: str | None
    evaluation_report_id: str | None

    iteration_index: int
    max_iterations: int

    decision: str | None
    interrupt_reason: str | None
    status: str

    staging_snapshot_id: str | None
