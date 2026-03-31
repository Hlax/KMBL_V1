"""gallery_strip_image_v1 artifact_outputs normalization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kmbl_orchestrator.contracts.gallery_image_artifact_v1 import (
    GalleryStripImageArtifactV1,
    normalize_gallery_artifact_outputs_list,
)


def test_normalize_gallery_artifact_valid() -> None:
    raw = [
        {
            "role": "gallery_strip_image_v1",
            "key": "a1",
            "url": "https://example.com/a.png",
            "thumb_url": "https://example.com/a-t.png",
            "alt": "A",
            "source": "generated",
        },
    ]
    out = normalize_gallery_artifact_outputs_list(raw)
    assert len(out) == 1
    assert out[0]["key"] == "a1"
    assert out[0]["url"] == "https://example.com/a.png"


def test_duplicate_key_skipped() -> None:
    raw = [
        {"role": "gallery_strip_image_v1", "key": "x", "url": "https://example.com/1.png"},
        {"role": "gallery_strip_image_v1", "key": "x", "url": "https://example.com/2.png"},
    ]
    out = normalize_gallery_artifact_outputs_list(raw)
    gallery = [r for r in out if isinstance(r, dict) and r.get("role") == "gallery_strip_image_v1"]
    assert len(gallery) == 1
    assert gallery[0]["url"] == "https://example.com/1.png"


def test_pass_through_non_gallery_artifacts() -> None:
    raw = ["https://example.com/loose.png", {"kind": "note", "text": "hi"}]
    out = normalize_gallery_artifact_outputs_list(raw)
    assert out == raw


def test_model_ignores_extra_keys() -> None:
    model = GalleryStripImageArtifactV1.model_validate(
        {
            "role": "gallery_strip_image_v1",
            "key": "k",
            "url": "https://example.com/z.png",
            "extra": 1,
        }
    )
    assert model.key == "k"
    dumped = model.model_dump(mode="json")
    assert "extra" not in dumped
