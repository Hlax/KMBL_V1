"""Legacy orchestrator OpenAI Images boundary — disabled unless ``kmb_legacy_orchestrator_openai_images`` (tests)."""

from kmbl_orchestrator.image_provider.budget import GraphRunImageBudget
from kmbl_orchestrator.image_provider.contracts import ImageGenerationRequest, ImageGenerationResult
from kmbl_orchestrator.image_provider.openai_provider import OpenAIImageProvider
from kmbl_orchestrator.image_provider.protocol import ImageProvider
from kmbl_orchestrator.image_provider.service import (
    ImageGenerationService,
    get_graph_run_image_budget,
    get_image_generation_service,
    reset_image_generation_singletons_for_tests,
)

__all__ = [
    "GraphRunImageBudget",
    "ImageGenerationRequest",
    "ImageGenerationResult",
    "ImageGenerationService",
    "ImageProvider",
    "OpenAIImageProvider",
    "get_graph_run_image_budget",
    "get_image_generation_service",
    "reset_image_generation_singletons_for_tests",
]
