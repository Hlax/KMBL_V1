"""Normalized failure taxonomy for role + orchestrator surfaces (read-model safe)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

ErrorKind = Literal[
    "role_invocation",
    "contract_validation",
    "provider_error",
    "persistence_error",
    "graph_error",
    "orchestrator_stale_run",
    "sandbox_error",
    "staging_integrity",
]

# Back-compat: older interrupt rows used persist_or_graph
LegacyPersistKind = Literal["persist_or_graph"]

STALE_RUN_MESSAGE = (
    "Run exceeded stale-running threshold without terminal completion"
)


def normalized_failure(
    *,
    error_kind: ErrorKind | LegacyPersistKind,
    message: str,
    error_type: str | None = None,
    failure_phase: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single envelope for role_invocation.output_payload_json and orchestrator_error blobs."""
    out: dict[str, Any] = {
        "status": "failed",
        "error_kind": error_kind,
        "message": message,
    }
    if error_type is not None:
        out["error_type"] = error_type
    if failure_phase is not None:
        out["failure_phase"] = failure_phase
    if details:
        out["details"] = details
    return out


def staging_integrity_failure(
    *,
    reason: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalized envelope for interrupt checkpoints when staging final checks fail."""
    out: dict[str, Any] = {
        "status": "failed",
        "error_kind": "staging_integrity",
        "message": message,
        "error_type": "staging_integrity",
        "reason": reason,
    }
    if details:
        out["details"] = details
    return out


def contract_validation_failure(
    *,
    phase: str,
    message: str,
    pydantic_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return normalized_failure(
        error_kind="contract_validation",
        message=message,
        error_type="contract_validation",
        failure_phase=phase,
        details={"pydantic_errors": pydantic_errors} if pydantic_errors else None,
    )


def pydantic_validation_error_to_contract_failure(
    phase: str, exc: ValidationError
) -> dict[str, Any]:
    return contract_validation_failure(
        phase=phase,
        message="Payload failed contract validation",
        pydantic_errors=exc.errors(),
    )


def error_kind_from_detail(detail: dict[str, Any] | None) -> str | None:
    if not detail:
        return None
    ek = detail.get("error_kind")
    return str(ek) if isinstance(ek, str) else None


def legacy_persist_or_graph_to_graph_error(message: str) -> dict[str, Any]:
    """Map old persist_or_graph interrupt blobs to graph_error for display."""
    return normalized_failure(
        error_kind="graph_error",
        message=message,
        error_type="graph_error",
        details={"legacy_error_kind": "persist_or_graph"},
    )
