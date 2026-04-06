"""Iteration compaction for generator payloads."""

from __future__ import annotations

from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
    apply_iteration_compaction,
    build_spec_digest,
)


def test_apply_iteration_compaction_reduces_chars() -> None:
    payload = {
        "build_spec": {"type": "interactive_frontend_app_v1", "title": "x"},
        "event_input": {
            "kmbl_session_staging": {"thread_id": "t"},
            "crawl_context": {"visited_count": 3, "recent_page_summaries": [{"url": "https://a"}]},
        },
        "structured_identity": {"themes": ["a", "b"], "tone": "calm", "visual_tendencies": ["x"]},
        "kmbl_interactive_lane_context": {
            "lane": "interactive_frontend_app_v1",
            "experience_mode": "flat_standard",
            "heavy_webgl_product_mode_requested": False,
            "generator_library_policy": {"x": 1},
            "preview_pipeline": {"summary": "s"},
            "strengths": ["long"] * 20,
        },
        "kmbl_implementation_reference_cards": [{"id": 1}],
        "kmbl_inspiration_reference_cards": [{"id": 2}],
        "kmbl_planner_observed_reference_cards": [{"id": 3}],
    }
    saved = apply_iteration_compaction(payload, iteration=1)
    assert saved > 0
    assert payload["kmbl_locked_build_spec_digest"] == build_spec_digest(
        {"type": "interactive_frontend_app_v1", "title": "x"}
    )
    assert payload["event_input"].get("crawl_context_compact") is not None
    assert payload["structured_identity"].get("_kmbl_compacted") is True
    assert payload["kmbl_implementation_reference_cards"] == []
