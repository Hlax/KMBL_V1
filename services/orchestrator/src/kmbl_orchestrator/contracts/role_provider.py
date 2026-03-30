"""Stable graph → agent-runtime boundary (implementation: KiloClaw HTTP / CLI / stub)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from kmbl_orchestrator.contracts.role_outputs import RoleType


@runtime_checkable
class RoleProvider(Protocol):
    """
    KMBL LangGraph and `DefaultRoleInvoker` depend only on this shape.

    Transport details (OpenAI chat completions, headers, CLI subprocess) stay inside
    `providers.kiloclaw` implementations; callers use `invoke_role` only.
    """

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...
