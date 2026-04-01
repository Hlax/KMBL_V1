"""KiloClaw / OpenClaw role execution — backward-compatible re-export shim.

Prefer importing from the concrete modules directly in new code:
- :mod:`kmbl_orchestrator.providers.kiloclaw_protocol` — protocol, errors, factory
- :mod:`kmbl_orchestrator.providers.kiloclaw_parsing` — response parsing
- :mod:`kmbl_orchestrator.providers.kiloclaw_http` — HTTP transport
- :mod:`kmbl_orchestrator.providers.kiloclaw_cli` — CLI transport
- :mod:`kmbl_orchestrator.providers.kiloclaw_stub` — stub transport
"""

from __future__ import annotations

from kmbl_orchestrator.providers.kiloclaw_cli import OpenClawCliClient
from kmbl_orchestrator.providers.kiloclaw_http import KiloClawHttpClient
from kmbl_orchestrator.providers.kiloclaw_parsing import extract_role_payload_from_openclaw_output
from kmbl_orchestrator.providers.kiloclaw_protocol import (
    KiloClawClient,
    KiloClawInvocationError,
    RoleType,
    get_kiloclaw_client,
    provider_failure,
)
from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

__all__ = [
    "KiloClawClient",
    "KiloClawHttpClient",
    "KiloClawInvocationError",
    "KiloClawStubClient",
    "OpenClawCliClient",
    "RoleType",
    "extract_role_payload_from_openclaw_output",
    "get_kiloclaw_client",
    "provider_failure",
]
