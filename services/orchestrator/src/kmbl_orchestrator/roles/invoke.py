"""Role invocation interface — KMBL → OpenClaw gateway boundary (docs/06, docs/12 §6)."""

from __future__ import annotations

import logging
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
    get_kiloclaw_client_with_trace,
)
from kmbl_orchestrator.providers.kiloclaw_protocol import assert_kiloclaw_role_invocation_permitted

_log = logging.getLogger(__name__)


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
    """Wires OpenClaw-compatible gateway client; records invocation metadata for persistence upstream."""

    def __init__(
        self,
        client: RoleProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        s = settings or get_settings()
        if client is not None:
            self._client = client
            self._transport_trace: dict[str, Any] = {
                "openclaw_transport_configured": "injected",
                "openclaw_transport_resolved": "injected",
                "openclaw_stub_mode": False,
                "openclaw_api_key_present": bool((s.openclaw_api_key or "").strip()),
                "openclaw_auto_resolution_note": None,
                "openclaw_openclaw_cli_path": None,
            }
        else:
            self._client, self._transport_trace = get_kiloclaw_client_with_trace(s)

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
        assert_kiloclaw_role_invocation_permitted(
            settings=get_settings(),
            client=self._client,
        )

        rid = uuid4()
        if role_type not in ("planner", "generator", "evaluator"):
            raise ValueError(f"invalid role_type: {role_type}")
        rt = cast(Literal["planner", "generator", "evaluator"], role_type)
        rm = dict(routing_metadata) if routing_metadata else {}
        merged_routing = {**rm, **self._transport_trace}
        invocation = RoleInvocationRecord(
            role_invocation_id=rid,
            graph_run_id=graph_run_id,
            thread_id=thread_id,
            role_type=rt,
            provider="openclaw",
            provider_config_key=provider_config_key,
            input_payload_json=input_payload,
            output_payload_json=None,
            routing_metadata_json=merged_routing,
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

        _log.info(
            "role_invoke role=%s transport=%s stub_mode=%s graph_run_id=%s",
            rt,
            self._transport_trace.get("openclaw_transport_resolved"),
            self._transport_trace.get("openclaw_stub_mode"),
            graph_run_id,
        )
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
