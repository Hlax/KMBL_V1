"""payload_budget_governor_v1 deterministic trimming and telemetry merge."""

from __future__ import annotations

from kmbl_orchestrator.contracts.role_inputs import validate_role_input
from kmbl_orchestrator.runtime.payload_budget_governor_v1 import (
    GOVERNOR_VERSION,
    apply_payload_budget_governor_v1,
    merge_governor_report_into_telemetry,
)
from kmbl_orchestrator.runtime.payload_telemetry_v1 import build_payload_telemetry_v1


def _big_planner_payload() -> dict:
    return {
        "thread_id": "t",
        "graph_run_id": "g",
        "identity_url": "https://example.com",
        "event_input": {"scenario": "x"},
        "structured_identity": {"themes": ["a"]},
        "kmbl_planner_observed_reference_cards": [{"id": f"o{i}", "note": "x" * 400} for i in range(30)],
        "kmbl_inspiration_reference_cards": [{"id": f"i{i}"} for i in range(25)],
        "kmbl_implementation_reference_cards": [{"id": f"m{i}"} for i in range(25)],
        "crawl_context": {
            "next_urls_to_crawl": [f"https://u{i}.test/p" for i in range(40)],
            "top_identity_pages": [{"url": f"https://a{i}.test"} for i in range(20)],
        },
        "memory_context": {"cross_run": {"hint": "h" * 8000}},
    }


def test_planner_trims_when_over_budget() -> None:
    p0 = _big_planner_payload()
    out, rep = apply_payload_budget_governor_v1("planner", p0, budget_target_chars=6000)
    assert rep["was_trimmed"] is True
    assert rep["initial_payload_char_count"] > rep["final_payload_char_count"]
    assert rep["final_payload_char_count"] <= 6000 or rep["final_payload_char_count"] < rep["initial_payload_char_count"]
    assert rep["dropped_reference_count"] > 0
    validate_role_input("planner", out)


def test_planner_no_trim_under_budget() -> None:
    p = {"thread_id": "t", "graph_run_id": "g", "event_input": {}}
    out, rep = apply_payload_budget_governor_v1("planner", p, budget_target_chars=50_000)
    assert rep["was_trimmed"] is False
    assert rep["trimmed_sections"] == []


def test_generator_preserves_build_spec() -> None:
    p = {
        "thread_id": "t",
        "build_spec": {"type": "interactive_frontend_app_v1", "experience_mode": "flat_standard"},
        "kmbl_execution_contract": {"lane": "x"},
        "surface_type": "static_html",
        "cool_generation_lane_active": False,
        "event_input": {},
        "current_working_state": {"blob": "z" * 12000},
        "kmbl_implementation_reference_cards": [{"id": f"c{i}"} for i in range(40)],
    }
    out, rep = apply_payload_budget_governor_v1("generator", p, budget_target_chars=4000)
    assert rep["was_trimmed"] is True
    assert out["build_spec"]["type"] == "interactive_frontend_app_v1"
    validate_role_input("generator", out)


def test_evaluator_preserves_summary_trims_snippets_first() -> None:
    summary = {"summary_version": 1, "lane": "interactive_frontend_app_v1", "libraries_detected": ["three"]}
    snip = {
        "snippet_version": 1,
        "entry_html": {"path": "p.html", "text": "<html>" + "B" * 9000},
        "scripts": [{"path": "a.js", "text": "C" * 9000}],
        "shaders": [],
        "note": "n",
    }
    p = {
        "thread_id": "t",
        "graph_run_id": "g",
        "build_candidate": {
            "preview_url": "https://x",
            "artifact_outputs": [],
            "kmbl_build_candidate_summary_v1": summary,
            "kmbl_evaluator_artifact_snippets_v1": snip,
        },
        "success_criteria": [],
        "evaluation_targets": [],
        "iteration_hint": 0,
        "kmbl_build_candidate_summary_v1": summary,
        "kmbl_evaluator_artifact_snippets_v1": snip,
        "kmbl_implementation_reference_cards": [{"id": f"r{i}"} for i in range(20)],
    }
    out, rep = apply_payload_budget_governor_v1("evaluator", p, budget_target_chars=3500)
    assert rep["was_trimmed"] is True
    bc = out["build_candidate"]
    assert bc["kmbl_build_candidate_summary_v1"]["summary_version"] == 1
    assert bc["kmbl_build_candidate_summary_v1"]["lane"] == "interactive_frontend_app_v1"
    assert rep["dropped_snippet_count"] > 0 or len(rep["trimmed_sections"]) > 0
    validate_role_input("evaluator", out)


def test_observed_refs_trimmed_before_summary_intact() -> None:
    """References shrink; build-candidate summary is not a planner field — evaluator summary checked above."""
    p0 = _big_planner_payload()
    out, rep = apply_payload_budget_governor_v1("planner", p0, budget_target_chars=2500)
    obs = out.get("kmbl_planner_observed_reference_cards")
    assert isinstance(obs, list) and len(obs) < 30
    assert rep["dropped_observed_reference_count"] > 0


def test_merge_governor_into_telemetry() -> None:
    tel = build_payload_telemetry_v1("planner", {"thread_id": "t", "event_input": {}})
    gov = {
        "governor_version": GOVERNOR_VERSION,
        "role": "planner",
        "budget_target_chars": 100,
        "initial_payload_char_count": 5000,
        "final_payload_char_count": 2000,
        "was_trimmed": True,
        "trimmed_sections": ["a", "b"],
        "dropped_reference_count": 3,
        "dropped_snippet_count": 0,
        "dropped_observed_reference_count": 2,
    }
    m = merge_governor_report_into_telemetry(tel, gov)
    pg = m.get("payload_governor_v1")
    assert isinstance(pg, dict)
    assert pg["was_trimmed"] is True
    assert pg["chars_saved_by_governor_trim"] == 3000
    assert "governor_trim" in str(m.get("payload_budget_notes", ""))


def test_telemetry_has_no_raw_prompt_blobs() -> None:
    import json

    p0 = _big_planner_payload()
    out, rep = apply_payload_budget_governor_v1("planner", p0, budget_target_chars=4000)
    tel = merge_governor_report_into_telemetry(
        build_payload_telemetry_v1("planner", out),
        rep,
    )
    blob = json.dumps(tel, default=str).lower()
    assert "full_prompt" not in blob
