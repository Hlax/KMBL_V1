"""Per-graph_run budget for server-side image generation (process-local counter)."""

from __future__ import annotations

from threading import Lock
from uuid import UUID


class GraphRunImageBudget:
    """
    Enforce a maximum number of generated images per ``graph_run_id`` in-process.

    Restarts reset counts — suitable for a first rollout; persist later if needed.
    """

    def __init__(self, max_per_run: int) -> None:
        self._max = max(0, int(max_per_run))
        self._counts: dict[UUID, int] = {}
        self._lock = Lock()

    @property
    def max_per_run(self) -> int:
        return self._max

    def try_consume(self, graph_run_id: UUID) -> bool:
        """Return True if a slot was reserved, False if budget exhausted or max is 0."""
        if self._max <= 0:
            return False
        with self._lock:
            n = self._counts.get(graph_run_id, 0)
            if n >= self._max:
                return False
            self._counts[graph_run_id] = n + 1
            return True

    def current(self, graph_run_id: UUID) -> int:
        with self._lock:
            return self._counts.get(graph_run_id, 0)

    def refund(self, graph_run_id: UUID) -> None:
        """Release one reserved slot after a failed generation attempt."""
        with self._lock:
            n = self._counts.get(graph_run_id, 0)
            if n > 0:
                self._counts[graph_run_id] = n - 1

    # Test hook
    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


__all__ = ["GraphRunImageBudget"]
