"""Role invocation interface — KMBL → KiloClaw boundary (docs/06, docs/12 §6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.domain import RoleInvocationRecord
from kmbl_orchestrator.providers.kiloclaw import KiloClawClient, KiloClawStubClient


class RoleInvoker(Protocol):
    def invoke(
        self,
        *,
        graph_run_id: UUID,
        thread_id: UUID,
        role_type: str,
        provider_config_key: str,
        input_payload: dict[str, Any],
        iteration_index: int,
    ) -> tuple[RoleInvocationRecord, dict[str, Any]]:
        """Persist role_invocation boundaries and return normalized output dict."""
        ...


class DefaultRoleInvoker:
    """Wires KiloClaw client; records invocation metadata for persistence upstream."""

    def __init__(
        self,
        client: KiloClawClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._client = client or KiloClawStubClient(settings=settings or get_settings())
        self._settings = settings or get_settings()

    def invoke(
        self,
        *,
        graph_run_id: UUID,
        thread_id: UUID,
        role_type: str,
        provider_config_key: str,
        input_payload: dict[str, Any],
        iteration_index: int,
    ) -> tuple[RoleInvocationRecord, dict[str, Any]]:
        rid = uuid4()
        if role_type not in ("planner", "generator", "evaluator"):
            raise ValueError(f"invalid role_type: {role_type}")
        rt = cast(Literal["planner", "generator", "evaluator"], role_type)
        invocation = RoleInvocationRecord(
            role_invocation_id=rid,
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            role_type=rt,
            provider="kiloclaw",
            provider_config_key=provider_config_key,
            input_payload_json=input_payload,
            output_payload_json=None,
            status="running",
            iteration_index=iteration_index,
        )

        raw_out = self._client.invoke_role(rt, input_payload)
        ended = datetime.now(timezone.utc).isoformat()
        done = invocation.model_copy(
            update={
                "output_payload_json": raw_out,
                "status": "completed",
                "ended_at": ended,
            }
        )
        return done, raw_out
