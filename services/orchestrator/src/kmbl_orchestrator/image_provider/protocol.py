"""Narrow protocol for pluggable image backends (OpenAI first)."""

from __future__ import annotations

from typing import Protocol

from kmbl_orchestrator.image_provider.contracts import ImageGenerationRequest, ImageGenerationResult


class ImageProvider(Protocol):
    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """Return a structured result; must not raise for normal provider failures (use fallback)."""
        ...


__all__ = ["ImageProvider"]
