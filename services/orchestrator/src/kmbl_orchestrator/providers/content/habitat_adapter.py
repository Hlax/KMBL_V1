"""
Habitat adapter for content generation.

Provides convenience functions for generating content within habitat assembly.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from kmbl_orchestrator.contracts.content_block_v1 import ContentBlockV1
from kmbl_orchestrator.providers.content.service import (
    ContentService,
    HabitatContentRequest,
    HabitatContentResult,
)


def generate_for_habitat(
    section_config: dict[str, Any],
    section_key: str,
    *,
    identity_context: dict[str, Any] | None = None,
    graph_run_id: UUID | None = None,
    thread_id: UUID | None = None,
    service: ContentService | None = None,
) -> HabitatContentResult:
    """
    Generate content for a habitat section from its config.

    Args:
        section_config: The config dict from a generated_text section
        section_key: The section's unique key
        identity_context: Optional identity context for identity-based generation
        graph_run_id: Optional graph run context
        thread_id: Optional thread context
        service: Optional content service instance

    Returns:
        HabitatContentResult with block or placeholder
    """
    service = service or ContentService()

    intent = section_config.get("intent", "")
    if not intent:
        return HabitatContentResult(
            status="failed",
            error="No intent provided for content generation",
        )

    use_identity = section_config.get("identity_context", False)

    request = HabitatContentRequest(
        intent=intent,
        tone=section_config.get("tone", "professional"),
        length=section_config.get("length", "1-2 paragraphs"),
        content_type=section_config.get("content_type", "paragraph"),
        key=section_key,
        identity_context=use_identity,
        identity_profile=identity_context if use_identity else None,
        graph_run_id=graph_run_id,
        thread_id=thread_id,
    )

    if use_identity and identity_context:
        return service.generate_for_habitat(request, mode="identity")

    return service.generate_for_habitat(request, mode="placeholder")


def create_content_block(
    content: str,
    key: str,
    content_type: Literal["heading", "paragraph", "list", "quote", "code", "html"] = "paragraph",
    tone: str | None = None,
    source: Literal["generated", "provided", "identity"] = "provided",
    level: int | None = None,
    language: str | None = None,
) -> ContentBlockV1:
    """
    Create a content block directly.

    Args:
        content: The text content
        key: Unique key for the block
        content_type: Type of content
        tone: Optional tone description
        source: Content source
        level: Heading level (1-6) for heading type
        language: Code language for code type

    Returns:
        ContentBlockV1 instance
    """
    return ContentBlockV1(
        role="content_block_v1",
        key=key,
        content_type=content_type,
        content=content,
        tone=tone,
        source=source,
        level=level,
        language=language,
    )
