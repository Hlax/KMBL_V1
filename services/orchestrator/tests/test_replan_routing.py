"""Tests for iterate → planner vs generator routing."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.helpers import should_route_to_planner_on_iterate


def test_replan_disabled_routes_to_generator_only() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "retry_direction": "pivot_layout",
        "current_state": {"stagnation_count": 99},
    }
    assert should_route_to_planner_on_iterate(st, s) is False


def test_pivot_directions_replan() -> None:
    s = Settings()
    for rd in ("pivot_layout", "pivot_palette", "pivot_content", "fresh_start"):
        assert should_route_to_planner_on_iterate({"retry_direction": rd}, s) is True


def test_refine_without_stagnation_threshold_no_replan() -> None:
    s = Settings(graph_replan_stagnation_threshold=0)
    st = {"retry_direction": "refine", "current_state": {"stagnation_count": 10}}
    assert should_route_to_planner_on_iterate(st, s) is False


def test_refine_with_stagnation_replans() -> None:
    s = Settings(graph_replan_stagnation_threshold=3)
    st = {"retry_direction": "refine", "current_state": {"stagnation_count": 3}}
    assert should_route_to_planner_on_iterate(st, s) is True


def test_planner_role_input_accepts_replan_context() -> None:
    from kmbl_orchestrator.contracts.role_inputs import validate_role_input

    payload = {
        "thread_id": "00000000-0000-0000-0000-000000000001",
        "replan_context": {
            "replan": True,
            "iteration_index": 1,
            "prior_build_spec_id": "x",
            "prior_evaluation_report": {"status": "fail"},
            "retry_context": {"retry_direction": "pivot_layout"},
            "prior_build_spec": {"title": "t"},
        },
    }
    out = validate_role_input("planner", payload)
    assert out["replan_context"]["replan"] is True
