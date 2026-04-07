from __future__ import annotations

from kmbl_orchestrator.contracts.canvas_contract_v1 import (
    derive_canvas_contract,
    derive_mixed_lane_contract,
)
from kmbl_orchestrator.runtime.cool_generation_lane import apply_cool_generation_lane_presets


def test_derive_mixed_lane_contract_for_photography_identity() -> None:
    lane_mix = derive_mixed_lane_contract(
        {"image_refs": ["https://cdn.example.com/a.jpg"]},
        {"content_types": ["photography"], "themes": ["cinematic"]},
        {"experience_mode": "immersive_identity_experience"},
    )
    assert lane_mix.primary_lane == "immersive_canvas"
    assert isinstance(lane_mix.lane_choice_rationale, str)
    assert lane_mix.lane_choice_rationale
    assert isinstance(lane_mix.lane_proposal_scores, list)
    assert lane_mix.lane_proposal_scores


def test_derive_canvas_contract_has_media_and_zone_hints() -> None:
    lane_mix = derive_mixed_lane_contract(
        {"image_refs": ["https://cdn.example.com/a.jpg"]},
        {"content_types": ["writing"]},
        {"site_archetype": "story"},
    )
    canvas = derive_canvas_contract(
        {"image_refs": ["https://cdn.example.com/a.jpg"]},
        {"content_types": ["writing"]},
        {"site_archetype": "story"},
        lane_mix,
    )
    assert canvas.zone_model in ("scroll_chapters", "hero_index", "multi_zone")
    assert "image" in canvas.media_modes


def test_cool_lane_presets_inject_canvas_and_lane_mix_contracts() -> None:
    bs, meta = apply_cool_generation_lane_presets(
        {
            "type": "interactive_frontend_app_v1",
            "title": "x",
            "steps": [],
            "experience_mode": "immersive_identity_experience",
            "execution_contract": {"lane": "cool_generation_v1"},
        },
        {"cool_generation_lane": True},
        {
            "image_refs": ["https://cdn.example.com/a.jpg"],
            "headings_sample": ["Selected Work", "About Me", "Contact"],
        },
        {"content_types": ["photography"], "themes": ["cinematic"]},
    )
    ec = bs.get("execution_contract") or {}
    assert "geometry_system" in ec
    assert "canvas_system" in ec
    assert "lane_mix" in ec
    assert "source_transformation_policy" in ec
    assert meta.get("canvas_contract_applied") is True
    assert meta.get("lane_mix_applied") is True
