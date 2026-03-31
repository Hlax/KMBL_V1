"""
Universal image artifact for habitat and general use.

Separate from gallery_strip_image_v1 which is specific to gallery strips.
This artifact can be used anywhere images are needed in habitats.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_log = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_URL_RE = re.compile(r"^https?://")


class ImageArtifactV1(BaseModel):
    """
    Universal image artifact for habitats and general use.

    Unlike gallery_strip_image_v1, this is not tied to gallery strips
    and can be used for hero images, backgrounds, inline images, etc.
    """

    model_config = ConfigDict(extra="ignore")

    role: Literal["image_artifact_v1"]
    key: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2000)
    alt: str = Field(min_length=1, max_length=500)
    width: int | None = Field(default=None, ge=1, le=10000)
    height: int | None = Field(default=None, ge=1, le=10000)
    source: Literal["generated", "external", "upload"]
    generation_prompt: str | None = Field(default=None, max_length=2000)
    placement_hint: Literal["hero", "inline", "background", "card", "thumbnail"] | None = None
    format: Literal["png", "jpg", "webp", "svg", "gif"] | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("key must be alphanumeric with underscores/hyphens, starting with letter")
        return v

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not _URL_RE.match(v):
            raise ValueError("url must start with http:// or https://")
        return v


def normalize_image_artifact(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate and normalize an image artifact dict.

    Returns normalized dict or None if validation fails.
    """
    if not isinstance(item, dict):
        return None
    if item.get("role") != "image_artifact_v1":
        return None

    try:
        model = ImageArtifactV1.model_validate(item)
        return model.model_dump(mode="json")
    except Exception as exc:
        _log.warning(
            "image_artifact_v1 validation failed for key=%s: %s",
            item.get("key", "<no key>"),
            exc,
        )
        return None


def normalize_image_artifact_outputs_list(seq: list[Any]) -> list[Any]:
    """
    Validate image_artifact_v1 dicts in a list; pass through other entries unchanged.

    Skips malformed rows with a warning. Deduplicates by key.
    """
    out: list[Any] = []
    seen_keys: set[str] = set()

    for item in seq:
        if isinstance(item, dict) and item.get("role") == "image_artifact_v1":
            normalized = normalize_image_artifact(item)
            if normalized is None:
                continue
            key = str(normalized["key"])
            if key in seen_keys:
                _log.warning("image_artifact_v1 duplicate key skipped: %s", key)
                continue
            seen_keys.add(key)
            out.append(normalized)
        else:
            out.append(item)

    return out
