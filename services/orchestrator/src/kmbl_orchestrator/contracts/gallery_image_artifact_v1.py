"""
First-class image artifacts for ``ui_gallery_strip_v1`` (bounded experiment).

Generator ``artifact_outputs`` may include entries with
``role: "gallery_strip_image_v1"``. Each entry is normalized, persisted on
``build_candidate.artifact_refs_json``, and referenced from strip items via
``image_artifact_key`` matching ``key``.

Static HTML/CSS/JS files use ``role: "static_frontend_file_v1"`` and are
normalized in :mod:`kmbl_orchestrator.contracts.static_frontend_artifact_v1`
after gallery rows (see :func:`normalize_combined_artifact_outputs_list`).

Other artifact shapes pass through unchanged (list position preserved).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _http_url_required(v: str) -> str:
    s = v.strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        raise ValueError("must be http(s) URL")
    return s


class GalleryStripImageArtifactV1(BaseModel):
    """Stable, reviewable gallery image ref — persisted in artifact_outputs."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["gallery_strip_image_v1"]
    key: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    thumb_url: str | None = Field(default=None, max_length=2048)
    alt: str | None = Field(default=None, max_length=500)
    source: Literal["generated", "external", "upload"] | None = None
    # Optional KMBL server-side provenance (image provider pass) — omitted for purely external rows.
    kmbl_generation_status: Literal["ok", "fallback", "skipped"] | None = None
    kmbl_provider: str | None = Field(default=None, max_length=64)
    kmbl_provider_model: str | None = Field(default=None, max_length=128)
    kmbl_fallback_reason: str | None = Field(default=None, max_length=500)

    @field_validator("key", mode="before")
    @classmethod
    def key_shape(cls, v: Any) -> Any:
        if not isinstance(v, str):
            raise ValueError("key must be a string")
        s = v.strip()
        if not _KEY_RE.match(s):
            raise ValueError(
                "key must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ (slug for cross-refs)"
            )
        return s

    @field_validator("url", "thumb_url", mode="before")
    @classmethod
    def url_http(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ValueError("must be string or null")
        return _http_url_required(v)


def normalize_gallery_artifact_outputs_list(raw: Any) -> list[Any]:
    """
    Validate ``gallery_strip_image_v1`` dicts; pass through other entries unchanged.

    Raises ``ValueError`` on duplicate keys or invalid gallery artifact rows.
    """
    if raw is None:
        return []
    seq: list[Any]
    if isinstance(raw, list):
        seq = list(raw)
    else:
        seq = [raw]
    out: list[Any] = []
    keys_seen: set[str] = set()
    for item in seq:
        if isinstance(item, dict) and item.get("role") == "gallery_strip_image_v1":
            model = GalleryStripImageArtifactV1.model_validate(item)
            dumped = model.model_dump(mode="json")
            k = str(dumped["key"])
            if k in keys_seen:
                raise ValueError(f"duplicate gallery_strip_image_v1 key: {k}")
            keys_seen.add(k)
            out.append(dumped)
        else:
            out.append(item)
    return out
