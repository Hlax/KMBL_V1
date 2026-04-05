"""Hoist nested planner criteria into persisted columns (session_3 LLM shape drift)."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.normalize.planner import normalize_planner_output
from kmbl_orchestrator.normalize.planner_canonicalize import canonicalize_planner_raw
from kmbl_orchestrator.seeds import (
    build_identity_url_static_frontend_event_input,
    merge_identity_url_static_frontend_extras,
)


def test_hoists_when_only_build_spec_has_success_and_targets() -> None:
    """Planner nests criteria under build_spec only — evaluator columns must still populate."""
    raw = {
        "build_spec": {
            "type": "static_frontend_file_v1",
            "title": "Test",
            "steps": [],
            "success_criteria": ["Hero has name", "About section exists"],
            "evaluation_targets": [
                {"kind": "text_present", "substring": "Harvey"},
                {"kind": "selector_present", "selector": ".project-item"},
            ],
        },
        "constraints": {"canonical_vertical": "static_frontend_file_v1"},
    }
    canonicalize_planner_raw(raw)
    spec = normalize_planner_output(
        raw,
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
    )
    assert spec.success_criteria_json == ["Hero has name", "About section exists"]
    assert len(spec.evaluation_targets_json) == 2
    assert spec.evaluation_targets_json[0]["kind"] == "text_present"


def test_top_level_wins_when_non_empty_even_if_build_spec_also_has_lists() -> None:
    raw = {
        "build_spec": {
            "type": "static_frontend_file_v1",
            "title": "Test",
            "success_criteria": ["nested ignored"],
            "evaluation_targets": [{"kind": "nested"}],
        },
        "constraints": {},
        "success_criteria": ["top wins"],
        "evaluation_targets": [{"kind": "top"}],
    }
    canonicalize_planner_raw(raw)
    spec = normalize_planner_output(
        raw,
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
    )
    assert spec.success_criteria_json == ["top wins"]
    assert spec.evaluation_targets_json == [{"kind": "top"}]


def test_acceptance_top_level_criteria_persist_for_evaluator_contract() -> None:
    """Same shape as PlannerRoleOutput: criteria siblings of build_spec — no hoist needed."""
    raw = {
        "build_spec": {"type": "static_frontend_file_v1", "title": "P", "steps": []},
        "constraints": {},
        "success_criteria": ["s1"],
        "evaluation_targets": [{"kind": "text_present", "substring": "x"}],
    }
    canonicalize_planner_raw(raw)
    spec = normalize_planner_output(
        raw,
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
    )
    assert spec.success_criteria_json == ["s1"]
    assert spec.evaluation_targets_json[0]["substring"] == "x"


def test_verify_cool_generation_lane_merge_and_top_level_planner_independent() -> None:
    """
    Acceptance check: identity URL event_input merge keeps cool_generation_lane; normalize keeps top-level criteria.
    (Runtime uses both — they are independent code paths.)
    """
    built = build_identity_url_static_frontend_event_input(
        identity_url="https://example.com/",
        seed_summary="demo",
    )
    ev = merge_identity_url_static_frontend_extras(built, {"cool_generation_lane": True})
    assert ev.get("cool_generation_lane") is True

    raw = {
        "build_spec": {"type": "static_frontend_file_v1", "title": "H", "steps": []},
        "constraints": {},
        "success_criteria": ["needle in page"],
        "evaluation_targets": [{"kind": "text_present", "substring": "needle"}],
    }
    canonicalize_planner_raw(raw)
    spec = normalize_planner_output(
        raw,
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
    )
    assert spec.success_criteria_json == ["needle in page"]
    assert spec.evaluation_targets_json


def test_promotes_execution_contract_from_creative_brief() -> None:
    raw = {
        "build_spec": {
            "type": "static_frontend_file_v1",
            "title": "T",
            "steps": [],
            "creative_brief": {
                "design_direction": "editorial",
                "execution_contract": {
                    "surface_type": "static_bundle",
                    "layout_mode": "grid",
                },
            },
        },
        "constraints": {},
    }
    fixes = canonicalize_planner_raw(raw)
    assert "promoted_execution_contract_from_creative_brief" in fixes
    ec = raw["build_spec"]["execution_contract"]
    assert isinstance(ec, dict)
    assert ec.get("surface_type") == "static_bundle"
    assert "execution_contract" not in raw["build_spec"].get("creative_brief", {})
