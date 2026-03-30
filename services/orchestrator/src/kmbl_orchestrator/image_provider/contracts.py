"""Typed internal contract for KMBL-owned image generation (server-side boundary)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ImageGenerationRequest(BaseModel):
    """Structured request — does not include raw provider blobs."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)
    size: str | None = Field(default=None, max_length=32)
    quality: str | None = Field(default=None, max_length=16)
    style: str | None = Field(default=None, max_length=32)
    graph_run_id: UUID
    thread_id: UUID
    identity_id: UUID | None = None
    variation_seed: str | None = Field(default=None, max_length=128)
    run_nonce: str | None = Field(default=None, max_length=128)
    artifact_key: str | None = Field(
        default=None,
        max_length=64,
        description="Target gallery_strip_image_v1 key when set.",
    )

    @field_validator("prompt", mode="before")
    @classmethod
    def strip_prompt(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class ImageGenerationResult(BaseModel):
    """Outcome + optional normalized gallery row — never includes API secrets."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "fallback", "skipped"]
    provider: str = Field(max_length=64)
    provider_model: str | None = Field(default=None, max_length=128)
    gallery_artifact: dict[str, Any] | None = Field(
        default=None,
        description="Normalized gallery_strip_image_v1 dict when status is generated.",
    )
    fallback_reason: str | None = Field(default=None, max_length=500)
    usage: dict[str, Any] | None = Field(
        default=None,
        description="Provider usage metadata when available (no secrets).",
    )


__all__ = ["ImageGenerationRequest", "ImageGenerationResult"]
