"""Tests for iterate → planner vs generator routing."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.helpers import (
    compute_hard_replan_reason,
    legacy_would_route_to_planner_on_iterate,
    resolve_iterate_planner_routing,
    should_route_to_planner_on_iterate,
)


def test_replan_disabled_routes_to_generator_only() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "retry_direction": "pivot_layout",
        "current_state": {"stagnation_count": 99},
    }
    assert should_route_to_planner_on_iterate(st, s) is False


def test_pivot_directions_replan_when_legacy_enabled() -> None:
    s = Settings(graph_replan_on_iterate_enabled=True)
    for rd in ("pivot_layout", "pivot_palette", "pivot_content", "fresh_start"):
        assert should_route_to_planner_on_iterate({"retry_direction": rd}, s) is True


def test_pivot_directions_no_replan_when_legacy_disabled_by_default() -> None:
    s = Settings()
    assert s.graph_replan_on_iterate_enabled is False
    for rd in ("pivot_layout", "pivot_palette", "pivot_content", "fresh_start"):
        assert should_route_to_planner_on_iterate({"retry_direction": rd}, s) is False


def test_refine_without_stagnation_threshold_no_replan() -> None:
    s = Settings(graph_replan_stagnation_threshold=0, graph_replan_on_iterate_enabled=True)
    st = {"retry_direction": "refine", "current_state": {"stagnation_count": 10}}
    assert should_route_to_planner_on_iterate(st, s) is False


def test_refine_with_stagnation_replans_when_legacy_enabled() -> None:
    s = Settings(graph_replan_stagnation_threshold=3, graph_replan_on_iterate_enabled=True)
    st = {"retry_direction": "refine", "current_state": {"stagnation_count": 3}}
    assert should_route_to_planner_on_iterate(st, s) is True


def test_hard_replan_evaluator_build_spec_invalid() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "retry_direction": "pivot_layout",
        "evaluation_report": {
            "issues": [{"type": "build_spec_invalid", "detail": "x"}],
        },
        "build_spec": {"type": "interactive_frontend_app_v1"},
        "event_input": {},
    }
    assert compute_hard_replan_reason(st) is None
    assert should_route_to_planner_on_iterate(st, s) is False


def test_hard_replan_canonical_vertical_mismatch() -> None:
    s = Settings()
    st = {
        "retry_direction": "refine",
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    }
    assert compute_hard_replan_reason(st) is None
    assert should_route_to_planner_on_iterate(st, s) is False


def test_hard_replan_empty_build_spec_type() -> None:
    s = Settings()
    st = {"build_spec": {}, "event_input": {}}
    assert compute_hard_replan_reason(st) is None
    assert should_route_to_planner_on_iterate(st, s) is False


def test_hard_replan_operator_force() -> None:
    st = {
        "build_spec": {"type": "interactive_frontend_app_v1"},
        "event_input": {"constraints": {"kmbl_force_replan": True}},
    }
    assert compute_hard_replan_reason(st) == "operator_force_replan"


def test_explicit_evaluator_replan_signal_routes_to_planner() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "evaluation_report": {
            "issues": [{"type": "explicit_replan_requested"}],
        },
        "build_spec": {"type": "interactive_frontend_app_v1"},
        "event_input": {},
    }
    assert compute_hard_replan_reason(st) == "evaluator_explicit_replan_requested"
    assert should_route_to_planner_on_iterate(st, s) is True


def test_resolve_iterate_planner_skipped_legacy_flag() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {"retry_direction": "pivot_layout"}
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is False
    assert reason is None
    assert skipped is True
    assert legacy_would_route_to_planner_on_iterate(st, s) is True


def test_identity_url_static_layout_stagnation_routes_to_planner() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 1,
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        "evaluation_report": {"issues": [{"type": "layout_stagnation"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is True
    assert reason == "identity_url_static_structural_stuck:layout_stagnation"
    assert skipped is False


def test_identity_url_static_archetype_mismatch_routes_to_planner() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 1,
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        "evaluation_report": {"issues": [{"type": "archetype_mismatch"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is True
    assert reason == "identity_url_static_structural_stuck:archetype_mismatch"
    assert skipped is False


def test_identity_url_static_polish_only_preserves_generator_retry() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 1,
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        "evaluation_report": {"issues": [{"type": "visual_polish"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is False
    assert reason is None
    assert skipped is False


def test_non_identity_url_stagnation_preserves_existing_behavior() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 1,
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"scenario": "kmbl_other_static_scenario"},
        "evaluation_report": {"issues": [{"type": "layout_stagnation"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is False
    assert reason is None
    assert skipped is False


def test_interactive_lane_preserves_existing_behavior() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 1,
        "build_spec": {"type": "interactive_frontend_app_v1"},
        "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        "evaluation_report": {"issues": [{"type": "layout_stagnation"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is False
    assert reason is None
    assert skipped is False


def test_identity_url_static_structural_replan_is_bounded_after_first_replan_window() -> None:
    s = Settings(graph_replan_on_iterate_enabled=False)
    st = {
        "iteration_index": 2,
        "build_spec": {"type": "static_frontend_file_v1"},
        "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        "evaluation_report": {"issues": [{"type": "layout_stagnation"}]},
    }
    route, reason, skipped = resolve_iterate_planner_routing(st, s)
    assert route is False
    assert reason is None
    assert skipped is False


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
