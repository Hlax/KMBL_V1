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
