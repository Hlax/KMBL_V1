"""
Content block artifact for text content in habitats.

Used for AI-generated or provided text content that can be
rendered within habitat sections.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_log = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class ContentBlockV1(BaseModel):
    """
    Text content block for habitats.

    Can represent headings, paragraphs, lists, quotes, or code blocks.
    Content may be AI-generated, provided directly, or derived from identity.
    """

    model_config = ConfigDict(extra="ignore")

    role: Literal["content_block_v1"]
    key: str = Field(min_length=1, max_length=64)
    content_type: Literal["heading", "paragraph", "list", "quote", "code", "html"]
    content: str = Field(min_length=1, max_length=50000)
    tone: str | None = Field(default=None, max_length=50)
    source: Literal["generated", "provided", "identity"]
    language: str | None = Field(default=None, max_length=20)
    level: int | None = Field(default=None, ge=1, le=6)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("key must be alphanumeric with underscores/hyphens, starting with letter")
        return v


def normalize_content_block(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate and normalize a content block dict.

    Returns normalized dict or None if validation fails.
    """
    if not isinstance(item, dict):
        return None
    if item.get("role") != "content_block_v1":
        return None

    try:
        model = ContentBlockV1.model_validate(item)
        return model.model_dump(mode="json")
    except Exception as exc:
        _log.warning(
            "content_block_v1 validation failed for key=%s: %s",
            item.get("key", "<no key>"),
            exc,
        )
        return None


def normalize_content_block_outputs_list(seq: list[Any]) -> list[Any]:
    """
    Validate content_block_v1 dicts in a list; pass through other entries unchanged.

    Skips malformed rows with a warning. Deduplicates by key.
    """
    out: list[Any] = []
    seen_keys: set[str] = set()

    for item in seq:
        if isinstance(item, dict) and item.get("role") == "content_block_v1":
            normalized = normalize_content_block(item)
            if normalized is None:
                continue
            key = str(normalized["key"])
            if key in seen_keys:
                _log.warning("content_block_v1 duplicate key skipped: %s", key)
                continue
            seen_keys.add(key)
            out.append(normalized)
        else:
            out.append(item)

    return out
