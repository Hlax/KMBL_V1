"""
Image service for habitat assembly.

Provides image generation via:
1. KiloClaw kmbl-image-gen agent (production)
2. Direct OpenAI API (legacy/testing)
3. External URL pass-through
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError
from kmbl_orchestrator.contracts.image_artifact_v1 import ImageArtifactV1

_log = logging.getLogger(__name__)


class HabitatImageRequest(BaseModel):
    """Request for image generation in a habitat context."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=2000)
    style: str = Field(default="digital-art", max_length=50)
    size: str = Field(default="1024x1024", max_length=20)
    placement: Literal["hero", "inline", "background", "card", "thumbnail"] = "inline"
    key: str = Field(min_length=1, max_length=64)
    alt: str | None = Field(default=None, max_length=500)
    
    graph_run_id: UUID | None = None
    thread_id: UUID | None = None
    identity_id: UUID | None = None


class HabitatImageResult(BaseModel):
    """Result of habitat image generation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "external", "placeholder", "failed"]
    artifact: ImageArtifactV1 | None = None
    error: str | None = None


class ImageService:
    """
    Unified image service for habitat assembly.

    Supports multiple generation modes:
    - kiloclaw: Route to kmbl-image-gen agent (production)
    - openai: Direct OpenAI API call (legacy/testing)
    - placeholder: Return placeholder for deferred generation
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def generate_for_habitat(
        self,
        request: HabitatImageRequest,
        mode: Literal["kiloclaw", "openai", "placeholder"] = "placeholder",
    ) -> HabitatImageResult:
        """
        Generate an image for habitat use.

        Args:
            request: Image generation request
            mode: Generation mode

        Returns:
            HabitatImageResult with artifact or error
        """
        if mode == "placeholder":
            return self._generate_placeholder(request)

        if mode == "openai":
            return self._generate_openai(request)

        if mode == "kiloclaw":
            return self._generate_kiloclaw(request)

        return HabitatImageResult(
            status="failed",
            error=f"Unknown generation mode: {mode}",
        )

    def _generate_placeholder(self, request: HabitatImageRequest) -> HabitatImageResult:
        """Generate a placeholder result for deferred generation."""
        return HabitatImageResult(
            status="placeholder",
            artifact=None,
            error=None,
        )

    def _generate_openai(self, request: HabitatImageRequest) -> HabitatImageResult:
        """
        Direct OpenAI image generation — disabled.

        This legacy path has been removed. Production image generation uses KiloClaw
        (kmbl-image-gen agent). The image_provider package has been deleted.
        Use mode='kiloclaw' or mode='placeholder' instead.
        """
        try:
            raise NotImplementedError(
                "Direct OpenAI image generation is disabled. "
                "Use KiloClaw (mode='kiloclaw') for image generation."
            )
        except Exception as exc:
            _log.warning("OpenAI image generation failed: %s", exc)
            return HabitatImageResult(status="failed", error=str(exc))

    def _generate_kiloclaw(self, request: HabitatImageRequest) -> HabitatImageResult:
        """
        Generate image via KiloClaw kmbl-image-gen agent.

        Uses the KiloClaw HTTP client to invoke the image generation agent.
        """
        try:
            from kmbl_orchestrator.providers.kiloclaw import get_kiloclaw_client
            from kmbl_orchestrator.providers.kiloclaw_protocol import (
                assert_kiloclaw_role_invocation_permitted,
            )

            client = get_kiloclaw_client(self._settings)
            try:
                assert_kiloclaw_role_invocation_permitted(
                    settings=self._settings,
                    client=client,
                )
            except KiloclawRoleInvocationForbiddenError as e:
                return HabitatImageResult(
                    status="failed",
                    error=f"transport_forbidden: {e} {e.operator_hint}".strip(),
                )
            config_key = self._settings.openclaw_generator_openai_image_config_key

            if not config_key:
                return HabitatImageResult(
                    status="failed",
                    error="OPENCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY not configured",
                )

            # Build payload for image generation agent
            payload = {
                "prompt": request.prompt,
                "style": request.style,
                "size": request.size,
                "key": request.key,
                "context": {
                    "placement": request.placement,
                    "alt": request.alt,
                },
            }
            
            if request.identity_id:
                payload["identity_id"] = str(request.identity_id)

            _log.info(
                "KiloClaw image generation: key=%s prompt=%s config=%s",
                request.key,
                request.prompt[:50] + "..." if len(request.prompt) > 50 else request.prompt,
                config_key,
            )

            # Invoke the image generation agent
            # Note: We use "generator" role_type since kmbl-image-gen is a generator variant
            result = client.invoke_role(
                role_type="generator",
                provider_config_key=config_key,
                payload=payload,
            )

            # Extract image URL from result
            # The image agent should return something like:
            # {"url": "https://...", "revised_prompt": "...", ...}
            image_url = result.get("url") or result.get("image_url")
            
            if not image_url:
                # Check for nested structure
                outputs = result.get("artifact_outputs", [])
                if outputs and isinstance(outputs, list):
                    for out in outputs:
                        if isinstance(out, dict) and out.get("url"):
                            image_url = out["url"]
                            break

            if not image_url:
                _log.warning(
                    "KiloClaw image generation returned no URL: keys=%s",
                    list(result.keys()) if isinstance(result, dict) else "not-dict",
                )
                return HabitatImageResult(
                    status="failed",
                    error="KiloClaw image agent returned no URL",
                )

            artifact = ImageArtifactV1(
                role="image_artifact_v1",
                key=request.key,
                url=image_url,
                alt=request.alt or request.prompt[:100],
                source="generated",
                generation_prompt=request.prompt,
                placement_hint=request.placement,
            )
            
            _log.info(
                "KiloClaw image generation success: key=%s url=%s",
                request.key,
                image_url[:80] + "..." if len(image_url) > 80 else image_url,
            )
            
            return HabitatImageResult(status="generated", artifact=artifact)

        except Exception as exc:
            _log.warning(
                "KiloClaw image generation failed: key=%s error=%s",
                request.key,
                exc,
            )
            return HabitatImageResult(status="failed", error=str(exc))

    def from_external_url(
        self,
        url: str,
        key: str,
        alt: str,
        placement: str = "inline",
    ) -> HabitatImageResult:
        """Create an image artifact from an external URL."""
        try:
            artifact = ImageArtifactV1(
                role="image_artifact_v1",
                key=key,
                url=url,
                alt=alt,
                source="external",
                placement_hint=placement,  # type: ignore
            )
            return HabitatImageResult(status="external", artifact=artifact)
        except Exception as exc:
            return HabitatImageResult(status="failed", error=str(exc))


def get_image_service(settings: Settings | None = None) -> ImageService:
    """Get a configured image service instance."""
    return ImageService(settings)
