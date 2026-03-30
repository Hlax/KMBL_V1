"""Normalize failure fields for GET /orchestrator/runs/{id}."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from kmbl_orchestrator.contracts.normalized_errors import (
    error_kind_from_detail,
    legacy_persist_or_graph_to_graph_error,
)
from kmbl_orchestrator.persistence.repository import Repository

FailurePhase = Literal["planner", "generator", "evaluator"] | None

_VALID_KINDS = frozenset(
    {
        "role_invocation",
        "contract_validation",
        "provider_error",
        "persistence_error",
        "graph_error",
        "orchestrator_stale_run",
        "sandbox_error",
        "staging_integrity",
        "persist_or_graph",
    }
)

_FALLBACK_FAILED = "Run failed; no structured error details were recorded."


def build_run_failure_view(
    repo: Repository,
    graph_run_id: UUID,
    *,
    status: str,
) -> dict[str, Any]:
    """
    Return keys: failure_phase, failure, error_kind, error_message.

    Read-only with respect to graph_run state (uses repo queries only).
    """
    if status != "failed":
        return {
            "failure_phase": None,
            "failure": None,
            "error_kind": None,
            "error_message": None,
        }

    inv = repo.get_latest_failed_role_invocation_for_graph_run(graph_run_id)
    if inv is not None and inv.output_payload_json is not None:
        failure = dict(inv.output_payload_json)
        failure_phase: FailurePhase = inv.role_type
        ek = error_kind_from_detail(failure)
        if ek in _VALID_KINDS:
            error_kind: str | None = ek
        else:
            error_kind = "role_invocation"
        error_message = str(failure.get("message") or _FALLBACK_FAILED)
        return {
            "failure_phase": failure_phase,
            "failure": failure,
            "error_kind": error_kind,
            "error_message": error_message,
        }

    err_blob = repo.get_latest_interrupt_orchestrator_error(graph_run_id)
    if err_blob:
        ek_raw = err_blob.get("error_kind")
        if ek_raw == "persist_or_graph":
            gm = str(err_blob.get("error_message") or _FALLBACK_FAILED)
            failure = legacy_persist_or_graph_to_graph_error(gm)
            return {
                "failure_phase": None,
                "failure": failure,
                "error_kind": "graph_error",
                "error_message": gm,
            }

        if ek_raw in _VALID_KINDS:
            error_kind = str(ek_raw)
        else:
            error_kind = "graph_error"
        error_message = str(err_blob.get("error_message") or _FALLBACK_FAILED)

        fp = err_blob.get("failure_phase")
        failure_phase = (
            fp if isinstance(fp, str) and fp in ("planner", "generator", "evaluator") else None
        )

        fb = err_blob.get("failure")
        if isinstance(fb, dict):
            failure = dict(fb)
        else:
            failure = {
                "status": "failed",
                "error_kind": error_kind,
                "message": error_message,
            }
        return {
            "failure_phase": failure_phase,
            "failure": failure,
            "error_kind": error_kind,
            "error_message": error_message,
        }

    return {
        "failure_phase": None,
        "failure": None,
        "error_kind": "graph_error",
        "error_message": _FALLBACK_FAILED,
    }
