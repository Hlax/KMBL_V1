"""Planner raw output → build_spec record (docs/07 §4.2, §1.8)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import BuildSpecRecord


def normalize_planner_output(
    raw: dict[str, Any],
    *,
    thread_id: UUID,
    graph_run_id: UUID,
    planner_invocation_id: UUID,
) -> BuildSpecRecord:
    """
    Map KiloClaw planner JSON into persisted build_spec columns.

    Callers must run ``canonicalize_planner_raw`` earlier in the pipeline so nested LLM
    shapes are hoisted before cool-lane presets and persistence.
    """
    build_spec_id = uuid4()
    spec = raw.get("build_spec")
    if not isinstance(spec, dict):
        spec = {"value": spec}
    constraints = raw.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {} if constraints is None else {"value": constraints}
    success = raw.get("success_criteria")
    if not isinstance(success, list):
        success = [] if success is None else [success]
    targets = raw.get("evaluation_targets")
    if not isinstance(targets, list):
        targets = [] if targets is None else [targets]
    return BuildSpecRecord(
        build_spec_id=build_spec_id,
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        planner_invocation_id=planner_invocation_id,
        spec_json=spec,
        constraints_json=constraints,
        success_criteria_json=success,
        evaluation_targets_json=targets,
        status="active",
    )
