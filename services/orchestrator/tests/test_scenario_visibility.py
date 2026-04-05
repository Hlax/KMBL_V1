"""scenario_visibility helpers (gallery strip inspection)."""

from __future__ import annotations

from kmbl_orchestrator.runtime.scenario_visibility import (
    gallery_strip_visibility_from_staging_payload,
    scenario_badge_from_tag,
    scenario_tag_from_run_state,
)


def test_scenario_tag_from_run_state() -> None:
    assert scenario_tag_from_run_state(None) is None
    assert scenario_tag_from_run_state({}) is None
    assert (
        scenario_tag_from_run_state({"event_input": {"scenario": "kmbl_seeded_gallery_strip_v1"}})
        == "kmbl_seeded_gallery_strip_v1"
    )


def test_scenario_badge() -> None:
    assert scenario_badge_from_tag("kmbl_identity_url_bundle_v1") == "identity_url_bundle"
    assert scenario_badge_from_tag("kmbl_identity_url_static_v1") == "identity_url_static"
    assert scenario_badge_from_tag("kmbl_seeded_gallery_strip_v1") == "gallery_strip"
    assert (
        scenario_badge_from_tag("kmbl_seeded_gallery_strip_varied_v1") == "gallery_varied"
    )
    assert (
        scenario_badge_from_tag("kmbl_kiloclaw_image_only_test_v1") == "kiloclaw_image_test"
    )
    assert scenario_badge_from_tag("kmbl_seeded_local_v1") == "local_seed"
    assert scenario_badge_from_tag("other") == "other"


def test_gallery_visibility_from_payload() -> None:
    p = {
        "version": 1,
        "metadata": {
            "working_state_patch": {
                "ui_gallery_strip_v1": {
                    "items": [
                        {"label": "A", "image_artifact_key": "k1"},
                        {"label": "B"},
                    ],
                },
            },
        },
        "artifacts": {
            "artifact_refs": [
                {"role": "gallery_strip_image_v1", "key": "k1", "url": "https://x.com/a.png"},
                {"role": "other", "x": 1},
            ],
        },
    }
    gv = gallery_strip_visibility_from_staging_payload(p)
    assert gv["has_gallery_strip"] is True
    assert gv["gallery_strip_item_count"] == 2
    assert gv["gallery_image_artifact_count"] == 1
    assert gv["total_artifact_refs"] == 2
    assert gv["gallery_items_with_artifact_key"] == 1
