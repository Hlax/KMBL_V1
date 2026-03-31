"""
Habitat adapter for image generation.

Provides convenience functions for generating images within habitat assembly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from kmbl_orchestrator.contracts.image_artifact_v1 import ImageArtifactV1
from kmbl_orchestrator.providers.image.service import (
    HabitatImageRequest,
    HabitatImageResult,
    ImageService,
)


def generate_for_habitat(
    section_config: dict[str, Any],
    section_key: str,
    *,
    graph_run_id: UUID | None = None,
    thread_id: UUID | None = None,
    identity_id: UUID | None = None,
    service: ImageService | None = None,
) -> HabitatImageResult:
    """
    Generate an image for a habitat section from its config.

    Args:
        section_config: The config dict from a generated_image section
        section_key: The section's unique key
        graph_run_id: Optional graph run context
        thread_id: Optional thread context
        identity_id: Optional identity context
        service: Optional image service instance

    Returns:
        HabitatImageResult with artifact or placeholder
    """
    service = service or ImageService()

    prompt = section_config.get("prompt", "")
    if not prompt:
        return HabitatImageResult(
            status="failed",
            error="No prompt provided for image generation",
        )

    request = HabitatImageRequest(
        prompt=prompt,
        style=section_config.get("style", "digital-art"),
        size=section_config.get("size", "1024x1024"),
        placement=section_config.get("placement", "inline"),
        key=section_key,
        alt=section_config.get("alt"),
        graph_run_id=graph_run_id,
        thread_id=thread_id,
        identity_id=identity_id,
    )

    return service.generate_for_habitat(request, mode="placeholder")


def create_external_image_artifact(
    url: str,
    key: str,
    alt: str,
    placement: str = "inline",
    width: int | None = None,
    height: int | None = None,
) -> ImageArtifactV1:
    """
    Create an image artifact from an external URL.

    Args:
        url: External image URL
        key: Unique key for the artifact
        alt: Alt text for accessibility
        placement: Placement hint for rendering
        width: Optional width in pixels
        height: Optional height in pixels

    Returns:
        ImageArtifactV1 instance
    """
    return ImageArtifactV1(
        role="image_artifact_v1",
        key=key,
        url=url,
        alt=alt,
        source="external",
        placement_hint=placement,  # type: ignore
        width=width,
        height=height,
    )
