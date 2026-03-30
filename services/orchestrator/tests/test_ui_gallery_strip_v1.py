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


def test_normalize_ui_gallery_strip_drops_kmbl_image_gen_failure_stub_shape() -> None:
    """Metadata/failure stubs are dropped so persistence does not crash."""
    patch = {
        "ui_gallery_strip_v1": {
            "surface": "ui_gallery_strip_v1",
            "status": "empty",
            "reason": "no_valid_api_key",
            "requested_count": 4,
        },
        "keep": 1,
    }
    out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert "ui_gallery_strip_v1" not in out
    assert out.get("keep") == 1


def test_normalize_ui_gallery_strip_drops_kmbl_image_gen_success_metadata_stub_shape() -> None:
    """Success-path metadata stub (populated/model/size/...) is dropped."""
    patch = {
        "ui_gallery_strip_v1": {
            "surface": "ui_gallery_strip_v1",
            "status": "populated",
            "item_count": 4,
            "model": "dall-e-3",
            "size": "1024x1024",
            "quality": "standard",
        },
    }
    out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert "ui_gallery_strip_v1" not in out


def test_normalize_ui_gallery_strip_drops_invalid_items_extra_keys() -> None:
    patch = {
        "ui_gallery_strip_v1": {
            "headline": "H",
            "items": [{"label": "x", "evil": 1}],
        },
    }
    out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert "ui_gallery_strip_v1" not in out


def test_normalize_ui_gallery_strip_drops_invalid_item_bad_url() -> None:
    patch = {
        "ui_gallery_strip_v1": {
            "items": [{"label": "x", "href": "javascript:alert(1)"}],
        },
    }
    out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert "ui_gallery_strip_v1" not in out


def test_normalize_ui_gallery_strip_drops_non_object_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    patch = {"ui_gallery_strip_v1": []}
    with caplog.at_level(logging.WARNING):
        out = normalize_ui_gallery_strip_v1_in_patch(patch)
    assert "ui_gallery_strip_v1" not in out
    assert "invalid ui_gallery_strip_v1 dropped" in caplog.text


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


def test_normalize_generator_output_drops_invalid_metadata_strip_preserves_artifacts() -> None:
    """kmbl-image-gen metadata-only ui_gallery_strip_v1 must not block build_candidate."""
    tid = uuid4()
    gid = uuid4()
    inv = uuid4()
    bs = uuid4()
    raw = {
        "updated_state": {
            "ui_gallery_strip_v1": {
                "surface": "ui_gallery_strip_v1",
                "status": "populated",
                "item_count": 4,
                "model": "dall-e-3",
                "size": "1024x1024",
                "quality": "standard",
            },
        },
        "artifact_outputs": [
            {
                "role": "gallery_strip_image_v1",
                "key": "a",
                "url": "https://example.com/a.png",
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
    assert "ui_gallery_strip_v1" not in bc.working_state_patch_json
    assert len(bc.artifact_refs_json) == 1
    assert bc.artifact_refs_json[0]["role"] == "gallery_strip_image_v1"
    assert bc.artifact_refs_json[0]["key"] == "a"


def test_normalize_generator_output_kmbl_image_gen_honest_failure_shape() -> None:
    """kmbl-image-gen failure must use kmbl_image_generation, not invalid ui_gallery_strip_v1 stubs."""
    tid = uuid4()
    gid = uuid4()
    inv = uuid4()
    bs = uuid4()
    raw = {
        "proposed_changes": {"image_generation": "failed"},
        "artifact_outputs": [],
        "updated_state": {
            "kmbl_image_generation": {
                "status": "failed",
                "error_class": "openai_images_api",
                "message": "401 invalid_api_key",
                "http_status": 401,
                "provider_error": {
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                    "message": "Incorrect API key provided",
                },
            },
        },
        "sandbox_ref": None,
        "preview_url": None,
    }
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=inv,
        build_spec_id=bs,
    )
    assert bc.artifact_refs_json == []
    assert bc.working_state_patch_json.get("kmbl_image_generation", {}).get("status") == "failed"
    assert bc.working_state_patch_json.get("kmbl_image_generation", {}).get("http_status") == 401
    assert "ui_gallery_strip_v1" not in bc.working_state_patch_json
