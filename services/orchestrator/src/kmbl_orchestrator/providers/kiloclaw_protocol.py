"""KiloClaw protocol, error types, and factory.

Shared between all transports (HTTP, CLI, stub).
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

from kmbl_orchestrator.config import Settings, get_settings

RoleType = Literal["planner", "generator", "evaluator"]

_log = logging.getLogger(__name__)


# docs/12_API_AND_SERVICE_LAYER.md §9 — normalized provider failure envelope
def provider_failure(
    message: str,
    *,
    error_kind: str = "provider_error",
    error_type: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    et = error_type if error_type is not None else error_kind
    out: dict[str, Any] = {
        "status": "failed",
        "error_kind": error_kind,
        "error_type": et,
        "message": message,
    }
    if details:
        out["details"] = details
    return out


class KiloClawInvocationError(Exception):
    """Raised when KiloClaw returns an error or an unusable payload (before invoker marks role_invocation)."""

    def __init__(self, message: str, *, normalized: dict[str, Any]) -> None:
        super().__init__(message)
        self.normalized = normalized


class KiloClawClient(Protocol):
    """Invokes a hosted role configuration in KiloClaw."""

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Returns structured role output (not transport framing)."""
        ...


def get_kiloclaw_client(settings: Settings | None = None) -> "KiloClawClient":
    """
    Select transport:

    - ``auto`` (default): ``http`` if ``KILOCLAW_API_KEY`` is set, else ``stub``.
    - ``stub``: deterministic loop.
    - ``http``: gateway chat completions (default path ``/v1/chat/completions``).
    - ``openclaw_cli``: local ``openclaw agent --json`` (co-located with the orchestrator).
    """
    # Deferred imports to avoid circular dependency
    from kmbl_orchestrator.providers.kiloclaw_http import KiloClawHttpClient
    from kmbl_orchestrator.providers.kiloclaw_cli import OpenClawCliClient
    from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

    s = settings or get_settings()
    t = (s.kiloclaw_transport or "auto").strip().lower()
    if t == "stub":
        return KiloClawStubClient(settings=s)
    if t == "openclaw_cli":
        return OpenClawCliClient(settings=s)
    if t == "http":
        return KiloClawHttpClient(settings=s)
    if t in ("auto", ""):
        if (s.kiloclaw_api_key or "").strip():
            return KiloClawHttpClient(settings=s)
        return KiloClawStubClient(settings=s)
    raise ValueError(f"unknown KILOCLAW_TRANSPORT: {s.kiloclaw_transport}")
