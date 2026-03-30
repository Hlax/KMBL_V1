"""
KMBL image generation façade: gating, budget, provider routing, gallery normalization.

Callers (e.g. future graph hooks) use :meth:`ImageGenerationService.generate` — never expose
API keys outside this process.
"""

from __future__ import annotations

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.image_provider.budget import GraphRunImageBudget
from kmbl_orchestrator.image_provider.contracts import ImageGenerationRequest, ImageGenerationResult
from kmbl_orchestrator.image_provider.openai_provider import OpenAIImageProvider
from kmbl_orchestrator.image_provider.protocol import ImageProvider


class ImageGenerationService:
    """Server-side entry point for structured image generation with safe fallbacks."""

    def __init__(
        self,
        *,
        settings: Settings,
        budget: GraphRunImageBudget,
        provider: ImageProvider | None = None,
    ) -> None:
        self._settings = settings
        self._budget = budget
        self._provider: ImageProvider = provider or OpenAIImageProvider(settings)

    def generate(self, req: ImageGenerationRequest) -> ImageGenerationResult:
        """
        Attempt generation when enabled and budget allows; otherwise return skipped/fallback.

        Does not raise for disabled config or provider errors — returns structured results.

        Production image pixels flow through KiloClaw ``kmbl-image-gen`` only; this path is legacy
        and stays off unless ``kmb_legacy_orchestrator_openai_images`` is enabled (tests).
        """
        if not getattr(self._settings, "kmb_legacy_orchestrator_openai_images", False):
            return ImageGenerationResult(
                status="skipped",
                provider="none",
                provider_model=None,
                gallery_artifact=None,
                fallback_reason="orchestrator_openai_images_disabled_use_kiloclaw_image_agent",
            )
        if not self._settings.kmb_image_generation_enabled:
            return ImageGenerationResult(
                status="skipped",
                provider="none",
                provider_model=None,
                gallery_artifact=None,
                fallback_reason="image_generation_disabled",
            )

        if not (self._settings.kmb_openai_image_api_key or "").strip():
            return ImageGenerationResult(
                status="skipped",
                provider="none",
                provider_model=None,
                gallery_artifact=None,
                fallback_reason="missing_openai_image_api_key",
            )

        if not self._budget.try_consume(req.graph_run_id):
            return ImageGenerationResult(
                status="fallback",
                provider="none",
                provider_model=None,
                gallery_artifact=None,
                fallback_reason="image_generation_budget_exhausted",
            )

        result = self._provider.generate(req)
        if result.status == "generated":
            return result

        # Refund budget slot on non-success so a failed attempt does not burn the cap.
        self._budget.refund(req.graph_run_id)
        return result


def _build_default_budget(settings: Settings) -> GraphRunImageBudget:
    return GraphRunImageBudget(settings.kmb_max_images_per_graph_run)


# Process-wide singletons for orchestrator use (tests may replace via explicit construction).
_default_budget: GraphRunImageBudget | None = None


def get_graph_run_image_budget(settings: Settings | None = None) -> GraphRunImageBudget:
    global _default_budget
    if _default_budget is None:
        _default_budget = _build_default_budget(settings or get_settings())
    return _default_budget


def get_image_generation_service(settings: Settings | None = None) -> ImageGenerationService:
    s = settings or get_settings()
    return ImageGenerationService(settings=s, budget=get_graph_run_image_budget(s))


def reset_image_generation_singletons_for_tests() -> None:
    """Clear process-wide budget singleton (pytest isolation)."""
    global _default_budget
    _default_budget = None


__all__ = [
    "ImageGenerationService",
    "get_image_generation_service",
    "get_graph_run_image_budget",
    "reset_image_generation_singletons_for_tests",
]
