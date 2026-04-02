"""Orchestrator-level exceptions (graph + API boundary)."""

from __future__ import annotations

from typing import Any
from uuid import UUID


class RoleInvocationFailed(Exception):
    """Raised when a KiloClaw role returns a transport/validation failure after persisting role_invocation."""

    def __init__(
        self,
        *,
        phase: str,
        graph_run_id: UUID,
        thread_id: UUID,
        detail: dict[str, Any],
    ) -> None:
        self.phase = phase
        self.graph_run_id = graph_run_id
        self.thread_id = thread_id
        self.detail = detail
        super().__init__(f"role invocation failed in {phase}: {detail.get('message', detail)}")


class StagingIntegrityFailed(Exception):
    """
    Final staging checks failed after evaluator pass (e.g. preview URL rules).

    Not a KiloClaw role failure — ``error_kind`` is always ``staging_integrity``;
    ``reason`` distinguishes preview vs. other staging gates.
    """

    def __init__(
        self,
        *,
        graph_run_id: UUID,
        thread_id: UUID,
        reason: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.graph_run_id = graph_run_id
        self.thread_id = thread_id
        self.reason = reason
        self.message = message
        self.detail = dict(detail) if detail else {}
        super().__init__(message)


class RunInterrupted(Exception):
    """Cooperative cancel: operator requested interrupt; graph exits at the next boundary."""

    def __init__(self, *, graph_run_id: UUID, thread_id: UUID) -> None:
        self.graph_run_id = graph_run_id
        self.thread_id = thread_id
        super().__init__("run interrupt requested")


class KiloclawRoleInvocationForbiddenError(Exception):
    """Hard stop: role invocation cannot proceed under current transport policy (e.g. stub in production)."""

    def __init__(self, message: str, *, operator_hint: str = "") -> None:
        self.operator_hint = operator_hint
        super().__init__(message)
