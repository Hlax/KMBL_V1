"""
Content service for habitat text generation.

Provides text content generation via:
1. KiloClaw kmbl-generator agent (production)
2. Identity context extraction
3. Placeholder for deferred generation
"""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.content_block_v1 import ContentBlockV1

_log = logging.getLogger(__name__)


class HabitatContentRequest(BaseModel):
    """Request for content generation in a habitat context."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=1000)
    tone: str = Field(default="professional", max_length=50)
    length: str = Field(default="1-2 paragraphs", max_length=50)
    content_type: Literal["heading", "paragraph", "list", "quote", "code", "html"] = "paragraph"
    key: str = Field(min_length=1, max_length=64)
    
    identity_context: bool = False
    identity_profile: dict[str, Any] | None = None
    
    graph_run_id: UUID | None = None
    thread_id: UUID | None = None


class HabitatContentResult(BaseModel):
    """Result of habitat content generation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "identity", "provided", "placeholder", "failed"]
    block: ContentBlockV1 | None = None
    error: str | None = None


class ContentService:
    """
    Unified content service for habitat assembly.

    Supports multiple generation modes:
    - kiloclaw: Route to kmbl-generator agent (production)
    - identity: Extract from identity context
    - placeholder: Return placeholder for deferred generation
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def generate_for_habitat(
        self,
        request: HabitatContentRequest,
        mode: Literal["kiloclaw", "identity", "placeholder"] = "placeholder",
    ) -> HabitatContentResult:
        """
        Generate content for habitat use.

        Args:
            request: Content generation request
            mode: Generation mode

        Returns:
            HabitatContentResult with block or error
        """
        if mode == "placeholder":
            return self._generate_placeholder(request)

        if mode == "identity":
            return self._generate_from_identity(request)

        if mode == "kiloclaw":
            return self._generate_kiloclaw(request)

        return HabitatContentResult(
            status="failed",
            error=f"Unknown generation mode: {mode}",
        )

    def _generate_placeholder(self, request: HabitatContentRequest) -> HabitatContentResult:
        """Generate a placeholder result for deferred generation."""
        return HabitatContentResult(
            status="placeholder",
            block=None,
            error=None,
        )

    def _generate_from_identity(self, request: HabitatContentRequest) -> HabitatContentResult:
        """
        Generate content from identity context.

        Extracts relevant content based on the intent and identity profile.
        """
        if not request.identity_profile:
            return HabitatContentResult(
                status="failed",
                error="Identity profile required for identity mode",
            )

        profile = request.identity_profile
        intent_lower = request.intent.lower()

        content = ""

        if "bio" in intent_lower or "about" in intent_lower:
            content = profile.get("profile_summary", "")
            if not content:
                short_bio = profile.get("facets_json", {}).get("short_bio", "")
                if short_bio:
                    content = short_bio

        elif "name" in intent_lower or "heading" in intent_lower:
            content = profile.get("display_name", "") or profile.get("profile_summary", "").split(" — ")[0]

        elif "skills" in intent_lower or "keywords" in intent_lower:
            facets = profile.get("facets_json", {})
            keywords = facets.get("tone_keywords", []) + facets.get("aesthetic_keywords", [])
            if keywords:
                content = ", ".join(keywords[:10])

        if not content:
            content = profile.get("profile_summary", "Content based on identity")

        try:
            block = ContentBlockV1(
                role="content_block_v1",
                key=request.key,
                content_type=request.content_type,
                content=content,
                tone=request.tone,
                source="identity",
            )
            return HabitatContentResult(status="identity", block=block)
        except Exception as exc:
            return HabitatContentResult(status="failed", error=str(exc))

    def _generate_kiloclaw(self, request: HabitatContentRequest) -> HabitatContentResult:
        """
        Generate content via KiloClaw kmbl-generator agent.

        This is the production path but requires async context and
        KiloClaw connectivity.
        """
        _log.info(
            "KiloClaw content generation requested for key=%s (not yet implemented in sync context)",
            request.key,
        )
        return HabitatContentResult(
            status="placeholder",
            error="KiloClaw content generation requires async context - using placeholder",
        )

    def from_provided_content(
        self,
        content: str,
        key: str,
        content_type: str = "paragraph",
        tone: str | None = None,
    ) -> HabitatContentResult:
        """Create a content block from directly provided content."""
        try:
            block = ContentBlockV1(
                role="content_block_v1",
                key=key,
                content_type=content_type,  # type: ignore
                content=content,
                tone=tone,
                source="provided",
            )
            return HabitatContentResult(status="provided", block=block)
        except Exception as exc:
            return HabitatContentResult(status="failed", error=str(exc))


def get_content_service(settings: Settings | None = None) -> ContentService:
    """Get a configured content service instance."""
    return ContentService(settings)
