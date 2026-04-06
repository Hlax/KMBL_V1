"""Curated reference library loading, lane selection, and observed-reference shaping."""

from __future__ import annotations

from kmbl_orchestrator.contracts.interactive_build_spec_v1 import (
    apply_interactive_build_spec_hardening,
)
from kmbl_orchestrator.domain import RoleInvocationRecord
from kmbl_orchestrator.runtime.graph_run_detail_read_model import build_graph_run_detail_read_model
from kmbl_orchestrator.runtime.reference_library import (
    REFERENCE_LIBRARY_VERSION,
    build_planner_observed_reference_cards,
    build_planner_reference_payload,
    build_reference_sketch_from_wrapper,
    load_curated_reference_cards,
    reference_payload_json_size_estimate,
    select_generator_reference_slice,
    select_planner_reference_slice,
)
from kmbl_orchestrator.contracts.role_inputs import validate_role_input
from kmbl_orchestrator.runtime import reference_library as reference_library_mod


def test_curated_library_has_twenty_cards() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    cards = load_curated_reference_cards()
    assert len(cards) == 20
    ids = {str(c.get("id")) for c in cards}
    assert "ref_gaussian_splats_3d" in ids
    assert "ref_awwwards" in ids


def test_curated_cards_have_expected_schema_keys() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    for c in load_curated_reference_cards():
        for k in (
            "id",
            "title",
            "lane",
            "source_type",
            "source_url",
            "tags",
            "why_it_matters",
            "use_when",
            "avoid_when",
            "implementation_notes",
            "design_notes",
        ):
            assert k in c


def test_generator_default_lane_no_gaussian_implementation_card() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    bs = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "experience_mode": "flat_standard",
    }
    apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    block = select_generator_reference_slice(bs, {}, graph_run_id="run-a")
    impl_ids = [str(x.get("id")) for x in block["implementation_reference_cards"]]
    assert "ref_gaussian_splats_3d" not in impl_ids
    assert block["reference_selection_meta"].get("lane_bucket") == "default_three_gsap"
    assert len(block["implementation_reference_cards"]) <= 4
    assert len(block["inspiration_reference_cards"]) <= 2


def test_generator_gaussian_lane_includes_splat_reference() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    bs = {
        "type": "interactive_frontend_app_v1",
        "title": "t",
        "steps": [],
        "experience_mode": "immersive_spatial_portfolio",
        "execution_contract": {
            "surface_type": "webgl_experience",
            "layout_mode": "canvas_primary",
            "allowed_libraries": ["three", "gsap", "gaussian-splats-3d"],
            "escalation_lane": "gaussian_splat_v1",
            "required_interactions": [{"id": "orbit"}],
        },
    }
    apply_interactive_build_spec_hardening(
        bs,
        {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    block = select_generator_reference_slice(bs, {}, graph_run_id="run-b")
    impl_ids = [str(x.get("id")) for x in block["implementation_reference_cards"]]
    assert "ref_gaussian_splats_3d" in impl_ids
    assert all(str(x.get("lane")) == "gaussian_splat" for x in block["implementation_reference_cards"])


def test_planner_gaussian_hint_adds_splat_reference() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    si = {"themes": ["spatial"], "notable_entities": ["gaussian splat scan"]}
    out = select_planner_reference_slice(
        structured_identity=si,
        crawl_context=None,
        graph_run_id="g1",
    )
    impl_ids = [str(x.get("id")) for x in out["kmbl_implementation_reference_cards"]]
    assert "ref_gaussian_splats_3d" in impl_ids
    assert out["kmbl_reference_selection_meta"]["preferred_lane_hint"] == "gaussian_splat"


def test_planner_reference_payload_bounded() -> None:
    reference_library_mod._load_library_raw.cache_clear()
    p = build_planner_reference_payload(
        structured_identity={"tone": ["minimal"]},
        crawl_context={
            "crawl_phase": "inspiration_expansion",
            "recent_portfolio_summaries": [
                {
                    "url": "https://brand.example/about",
                    "summary": "About us page with grid layout",
                    "design_signals": ["grid", "hero"],
                    "tone_keywords": ["minimal"],
                    "origin": "portfolio",
                }
            ],
        },
        graph_run_id="g2",
    )
    assert len(p["kmbl_implementation_reference_cards"]) <= 4
    assert len(p["kmbl_inspiration_reference_cards"]) <= 3
    assert len(p["kmbl_planner_observed_reference_cards"]) <= 5
    sub = {
        "impl": p["kmbl_implementation_reference_cards"],
        "insp": p["kmbl_inspiration_reference_cards"],
        "obs": p["kmbl_planner_observed_reference_cards"],
    }
    n = reference_payload_json_size_estimate(sub)
    assert 0 < n < 25_000
    assert p["kmbl_reference_library_version"] == REFERENCE_LIBRARY_VERSION


def test_observed_reference_cards_distilled() -> None:
    crawl = {
        "recent_portfolio_summaries": [
            {
                "url": "https://brand.example/p",
                "summary": "Portfolio grid",
                "design_signals": ["grid"],
                "tone_keywords": ["bold"],
                "origin": "portfolio",
                "reference_sketch": {
                    "layout_notes": ["structure:grid"],
                    "motion_interaction_notes": ["motion:animation"],
                },
            }
        ]
    }
    cards = build_planner_observed_reference_cards(crawl, max_cards=3)
    assert len(cards) == 1
    assert cards[0]["source_type"] == "planner_observed"
    assert cards[0]["source_url"] == "https://brand.example/p"
    assert cards[0].get("reference_sketch")


def test_reference_sketch_from_wrapper_uses_top_level_sketch() -> None:
    data = {
        "reference_sketch": {
            "page_focus": "Hello | world",
            "taste_notes": ["tone:minimal"],
            "layout_notes": ["structure:grid"],
            "motion_interaction_notes": [],
        }
    }
    sk = build_reference_sketch_from_wrapper(data)
    assert sk["page_focus"].startswith("Hello")


def test_validate_role_input_accepts_reference_card_fields() -> None:
    out = validate_role_input(
        "planner",
        {
            "thread_id": "t1",
            "kmbl_implementation_reference_cards": [{"id": "x", "title": "y"}],
            "kmbl_reference_library_version": 1,
        },
    )
    assert out["kmbl_reference_library_version"] == 1
    gen = validate_role_input(
        "generator",
        {
            "thread_id": "t1",
            "build_spec": {},
            "kmbl_implementation_reference_cards": [],
            "kmbl_planner_observed_reference_cards": [],
        },
    )
    assert gen["kmbl_implementation_reference_cards"] == []


def test_graph_run_detail_includes_interactive_lane_operator_view() -> None:
    from uuid import uuid4

    from kmbl_orchestrator.domain import GraphRunRecord, ThreadRecord

    tid = uuid4()
    gid = uuid4()
    gen_id = uuid4()
    planner_id = uuid4()
    invocations = [
        RoleInvocationRecord(
            role_invocation_id=planner_id,
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key="x",
            input_payload_json={
                "kmbl_planner_observed_reference_cards": [
                    {"id": "planner_observed_x", "source_url": "https://a.test"}
                ],
            },
            status="completed",
            iteration_index=0,
            started_at="2026-04-01T10:00:00+00:00",
            ended_at="2026-04-01T10:01:00+00:00",
        ),
        RoleInvocationRecord(
            role_invocation_id=gen_id,
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            provider_config_key="x",
            input_payload_json={
                "kmbl_interactive_lane_context": {
                    "generator_library_policy": {
                        "flags": {
                            "gaussian_splat_lane_active": True,
                            "escalation_lane": "gaussian_splat_v1",
                        },
                    },
                    "execution_contract_signals": {
                        "allowed_libraries": ["three", "gsap", "gaussian-splats-3d"],
                        "escalation_lane": "gaussian_splat_v1",
                    },
                },
                "kmbl_library_compliance_hints": [
                    {"code": "gaussian_splat_lane_missing_primary_library", "severity": "warn", "detail": "x"}
                ],
                "kmbl_implementation_reference_cards": [{"id": "ref_gaussian_splats_3d"}],
                "kmbl_inspiration_reference_cards": [{"id": "ref_codrops"}],
                "kmbl_planner_observed_reference_cards": [],
                "kmbl_reference_selection_meta": {
                    "lane_bucket": "gaussian_splat",
                    "curated_library_version": 1,
                },
            },
            status="completed",
            iteration_index=0,
            started_at="2026-04-01T10:02:00+00:00",
            ended_at="2026-04-01T10:03:00+00:00",
        ),
    ]
    raw = build_graph_run_detail_read_model(
        thread=ThreadRecord(thread_id=tid, thread_kind="build", status="active"),
        gr=GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="completed",
            started_at="2026-04-01T10:00:00+00:00",
            ended_at="2026-04-01T10:05:00+00:00",
        ),
        invocations=invocations,
        staging_rows=[],
        publications=[],
        events=[],
        latest_checkpoint=None,
        has_interrupt_signal=False,
        bs=None,
        bc=None,
        ev=None,
    )
    view = raw["summary"].get("interactive_lane_operator_view")
    assert isinstance(view, dict)
    assert view.get("present") is True
    assert view.get("planner_invocation_reference_meta", {}).get("planner_observed_reference_count") == 1
    assert view.get("preview_pipeline_notes")
