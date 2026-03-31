"""
Content provider for habitat text generation.

Provides text content generation via:
1. KiloClaw kmbl-generator agent (production)
2. Identity context extraction
3. Direct pass-through for provided content
"""

from kmbl_orchestrator.providers.content.service import (
    ContentService,
    HabitatContentRequest,
    HabitatContentResult,
    get_content_service,
)
from kmbl_orchestrator.providers.content.habitat_adapter import (
    generate_for_habitat,
    create_content_block,
)

__all__ = [
    "ContentService",
    "HabitatContentRequest",
    "HabitatContentResult",
    "get_content_service",
    "generate_for_habitat",
    "create_content_block",
]
