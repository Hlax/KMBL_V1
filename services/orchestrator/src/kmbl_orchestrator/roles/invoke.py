"""Role invocation interface — KMBL → KiloClaw boundary (docs/06, docs/12 §6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from pydantic import ValidationError

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.role_inputs import validate_role_input
from kmbl_orchestrator.contracts.role_provider import RoleProvider
from kmbl_orchestrator.domain import RoleInvocationRecord
from kmbl_orchestrator.providers.kiloclaw import (
    KiloClawInvocationError,
    get_kiloclaw_client,
)


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
        routing_metadata: dict[str, Any] | None = None,
    ) -> tuple[RoleInvocationRecord, dict[str, Any]]:
        """Persist role_invocation boundaries and return normalized output dict."""
        ...


class DefaultRoleInvoker:
    """Wires KiloClaw client; records invocation metadata for persistence upstream."""

    def __init__(
        self,
        client: RoleProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        s = settings or get_settings()
        self._client: RoleProvider = client or get_kiloclaw_client(s)

    def invoke(
        self,
        *,
        graph_run_id: UUID,
        thread_id: UUID,
        role_type: str,
        provider_config_key: str,
        input_payload: dict[str, Any],
        iteration_index: int,
        routing_metadata: dict[str, Any] | None = None,
    ) -> tuple[RoleInvocationRecord, dict[str, Any]]:
        rid = uuid4()
        if role_type not in ("planner", "generator", "evaluator"):
            raise ValueError(f"invalid role_type: {role_type}")
        rt = cast(Literal["planner", "generator", "evaluator"], role_type)
        rm = dict(routing_metadata) if routing_metadata else {}
        invocation = RoleInvocationRecord(
            role_invocation_id=rid,
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            role_type=rt,
            provider="kiloclaw",
            provider_config_key=provider_config_key,
            input_payload_json=input_payload,
            output_payload_json=None,
            routing_metadata_json=rm,
            status="running",
            iteration_index=iteration_index,
        )

        try:
            outbound = validate_role_input(rt, input_payload)
        except ValidationError as e:
            ended = datetime.now(timezone.utc).isoformat()
            detail = contract_validation_failure(
                phase=rt,
                message="Role request payload failed contract validation",
                pydantic_errors=e.errors(),
            )
            failed = invocation.model_copy(
                update={
                    "input_payload_json": input_payload,
                    "output_payload_json": detail,
                    "status": "failed",
                    "ended_at": ended,
                }
            )
            return failed, detail

        try:
            raw_out = self._client.invoke_role(rt, provider_config_key, outbound)
        except KiloClawInvocationError as e:
            ended = datetime.now(timezone.utc).isoformat()
            failed = invocation.model_copy(
                update={
                    "output_payload_json": e.normalized,
                    "status": "failed",
                    "ended_at": ended,
                }
            )
            return failed, e.normalized
        ended = datetime.now(timezone.utc).isoformat()
        done = invocation.model_copy(
            update={
                "output_payload_json": raw_out,
                "status": "completed",
                "ended_at": ended,
            }
        )
        return done, raw_out
