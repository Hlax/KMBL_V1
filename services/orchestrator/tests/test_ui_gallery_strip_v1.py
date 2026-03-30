"""Bounded UI experiment: ui_gallery_strip_v1 contract + generator normalize."""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.contracts.ui_gallery_strip_v1 import (
    normalize_ui_gallery_strip_v1_in_patch,
)
from kmbl_orchestrator.normalize.generator import normalize_generator_output


def test_normalize_ui_gallery_strip_valid() -> None:
    patch = {
        "ui_gallery_strip_v1": {
            "headline": "  Demo  ",
            "items": [
                {
                    "label": "A",
                    "caption": "cap",
                    "image_url": "https://example.com/a.png",
                    "href": "https://example.com/a",
                },
            ],
        },
    }
    out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert out["ui_gallery_strip_v1"]["headline"] == "Demo"
    assert out["ui_gallery_strip_v1"]["items"][0]["label"] == "A"


def test_normalize_ui_gallery_strip_rejects_extra_keys() -> None:
    patch = {
        "ui_gallery_strip_v1": {
            "headline": "H",
            "items": [{"label": "x", "evil": 1}],
        },
    }
    with pytest.raises(ValueError):
        normalize_ui_gallery_strip_v1_in_patch(patch)


def test_normalize_ui_gallery_strip_rejects_bad_url() -> None:
    patch = {
        "ui_gallery_strip_v1": {
            "items": [{"label": "x", "href": "javascript:alert(1)"}],
        },
    }
    with pytest.raises(ValueError):
        normalize_ui_gallery_strip_v1_in_patch(patch)


def test_normalize_generator_output_coerces_strip() -> None:
    tid = uuid4()
    gid = uuid4()
    inv = uuid4()
    bs = uuid4()
    raw = {
        "updated_state": {
            "ui_gallery_strip_v1": {
                "headline": "Test",
                "items": [{"label": "One"}],
            },
        },
    }
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=inv,
        build_spec_id=bs,
    )
    assert bc.working_state_patch_json["ui_gallery_strip_v1"]["items"][0]["label"] == "One"


def test_generator_resolves_image_artifact_key() -> None:
    tid = uuid4()
    gid = uuid4()
    inv = uuid4()
    bs = uuid4()
    raw = {
        "updated_state": {
            "ui_gallery_strip_v1": {
                "items": [{"label": "Card", "image_artifact_key": "hero-a"}],
            },
        },
        "artifact_outputs": [
            {
                "role": "gallery_strip_image_v1",
                "key": "hero-a",
                "url": "https://example.com/full.png",
                "thumb_url": "https://example.com/thumb.png",
                "alt": "Hero",
                "source": "generated",
            },
        ],
    }
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=inv,
        build_spec_id=bs,
    )
    item = bc.working_state_patch_json["ui_gallery_strip_v1"]["items"][0]
    assert item["image_url"] == "https://example.com/full.png"
    assert item["image_thumb_url"] == "https://example.com/thumb.png"
    assert item["image_alt"] == "Hero"
    assert bc.artifact_refs_json[0]["role"] == "gallery_strip_image_v1"
    assert bc.artifact_refs_json[0]["key"] == "hero-a"


def test_normalize_generator_output_passes_through_without_key() -> None:
    tid = uuid4()
    gid = uuid4()
    inv = uuid4()
    bs = uuid4()
    raw = {"updated_state": {"other": 1}}
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=inv,
        build_spec_id=bs,
    )
    assert bc.working_state_patch_json == {"other": 1}
