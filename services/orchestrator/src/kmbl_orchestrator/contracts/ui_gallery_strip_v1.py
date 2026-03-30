"""
Bounded UI experiment: gallery strip (control-plane surface).

Persisted via ``updated_state`` / ``proposed_changes`` → ``build_candidate.working_state_patch_json``
→ staging ``metadata.working_state_patch`` — key ``ui_gallery_strip_v1``.

No change to staging_snapshot payload schema version; nested under existing ``working_state_patch`` dict.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ITEM_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _http_url_ok(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    s = v.strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        raise ValueError("must be http(s) URL or empty")
    return s


class UIGalleryStripItemV1(BaseModel):
    """One card in the strip — labels only; no raw HTML."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    caption: str | None = Field(default=None, max_length=240)
    image_url: str | None = None
    image_thumb_url: str | None = None
    href: str | None = None
    image_alt: str | None = Field(default=None, max_length=500)
    image_artifact_key: str | None = Field(default=None, max_length=64)

    @field_validator("label", "caption", mode="before")
    @classmethod
    def strip_ws(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("image_artifact_key", mode="before")
    @classmethod
    def artifact_key_shape(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ValueError("image_artifact_key must be string or null")
        s = v.strip()
        if not _ITEM_KEY_RE.match(s):
            raise ValueError("image_artifact_key must be a slug matching artifact key")
        return s

    @field_validator("image_alt", mode="before")
    @classmethod
    def alt_strip(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            t = v.strip()
            return t if t else None
        return v

    @field_validator("image_url", "image_thumb_url", "href", mode="before")
    @classmethod
    def url_or_none(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ValueError("must be string or null")
        return _http_url_ok(v.strip())


class UIGalleryStripV1(BaseModel):
    """Deterministic gallery strip for operator review + optional homepage pin."""

    model_config = ConfigDict(extra="forbid")

    headline: str | None = Field(default=None, max_length=160)
    items: list[UIGalleryStripItemV1] = Field(min_length=1, max_length=6)

    @field_validator("headline", mode="before")
    @classmethod
    def headline_strip(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            t = v.strip()
            return t if t else None
        return v


def resolve_gallery_artifact_refs_in_patch(
    patch: dict[str, Any], normalized_artifacts: list[Any]
) -> dict[str, Any]:
    """
    If strip items reference ``image_artifact_key``, fill ``image_url`` / ``image_thumb_url`` /
    ``image_alt`` from matching ``gallery_strip_image_v1`` artifacts (artifact wins on URL).

    Call **before** :func:`normalize_ui_gallery_strip_v1_in_patch`. Raises ``ValueError`` if a
    key is missing from the artifact list.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for a in normalized_artifacts:
        if not isinstance(a, dict):
            continue
        if a.get("role") != "gallery_strip_image_v1":
            continue
        k = a.get("key")
        if isinstance(k, str) and k.strip():
            by_key[k.strip()] = a

    raw_strip = patch.get("ui_gallery_strip_v1")
    if not isinstance(raw_strip, dict):
        return patch
    items = raw_strip.get("items")
    if not isinstance(items, list):
        return patch

    new_items: list[Any] = []
    for it in items:
        if not isinstance(it, dict):
            new_items.append(it)
            continue
        d = dict(it)
        k = d.get("image_artifact_key")
        if isinstance(k, str) and k.strip():
            ks = k.strip()
            if ks not in by_key:
                raise ValueError(
                    f"ui_gallery_strip_v1 item references unknown image_artifact_key: {ks!r}"
                )
            art = by_key[ks]
            d["image_url"] = art["url"]
            tu = art.get("thumb_url")
            if tu:
                d["image_thumb_url"] = tu
            alt = art.get("alt")
            if isinstance(alt, str) and alt.strip():
                d["image_alt"] = alt.strip()
        new_items.append(d)

    return {
        **patch,
        "ui_gallery_strip_v1": {**raw_strip, "items": new_items},
    }


def normalize_ui_gallery_strip_v1_in_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """
    If ``patch`` contains ``ui_gallery_strip_v1``, validate and replace with normalized JSON.

    Raises ``ValueError`` on invalid shape (fail generator persistence).
    """
    raw = patch.get("ui_gallery_strip_v1")
    if raw is None:
        return patch
    if not isinstance(raw, (dict, list)):
        raise ValueError("ui_gallery_strip_v1 must be an object")
    # Allow LLM to send list at wrong level — reject clearly
    if isinstance(raw, list):
        raise ValueError("ui_gallery_strip_v1 must be an object with headline/items, not a list")
    model = UIGalleryStripV1.model_validate(raw)
    out = dict(patch)
    out["ui_gallery_strip_v1"] = model.model_dump(mode="json")
    return out
