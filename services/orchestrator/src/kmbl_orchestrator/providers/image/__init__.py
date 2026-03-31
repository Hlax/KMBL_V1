"""
Image provider for habitat and general use.

Wraps the existing image_provider module with habitat-specific functionality.
"""

from kmbl_orchestrator.providers.image.service import ImageService, HabitatImageRequest
from kmbl_orchestrator.providers.image.habitat_adapter import generate_for_habitat

__all__ = [
    "ImageService",
    "HabitatImageRequest",
    "generate_for_habitat",
]
