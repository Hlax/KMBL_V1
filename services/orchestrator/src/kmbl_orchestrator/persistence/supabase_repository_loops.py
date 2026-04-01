"""Autonomous loop table operations — mixin for :class:`SupabaseRepository`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from kmbl_orchestrator.domain import AutonomousLoopRecord
from kmbl_orchestrator.persistence.supabase_deserializers import _row_to_autonomous_loop


class SupabaseRepositoryAutonomousLoopMixin:
    """``autonomous_loop`` CRUD and locking — expects ``_run`` and ``_client`` on the concrete class."""

    _run: Any
    _client: Any

    def save_autonomous_loop(self, record: AutonomousLoopRecord) -> None:
        row = {
            "loop_id": str(record.loop_id),
            "identity_id": str(record.identity_id),
            "identity_url": record.identity_url,
            "status": record.status,
            "phase": record.phase,
            "iteration_count": record.iteration_count,
            "max_iterations": record.max_iterations,
            "current_thread_id": str(record.current_thread_id) if record.current_thread_id else None,
            "current_graph_run_id": str(record.current_graph_run_id) if record.current_graph_run_id else None,
            "last_staging_snapshot_id": str(record.last_staging_snapshot_id) if record.last_staging_snapshot_id else None,
            "last_evaluator_status": record.last_evaluator_status,
            "last_evaluator_score": record.last_evaluator_score,
            "exploration_directions": record.exploration_directions,
            "completed_directions": record.completed_directions,
            "auto_publish_threshold": record.auto_publish_threshold,
            "proposed_staging_id": str(record.proposed_staging_id) if record.proposed_staging_id else None,
            "proposed_at": record.proposed_at,
            "locked_at": record.locked_at,
            "locked_by": record.locked_by,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "completed_at": record.completed_at,
            "total_staging_count": record.total_staging_count,
            "total_publication_count": record.total_publication_count,
            "best_rating": record.best_rating,
            "last_error": record.last_error,
            "consecutive_graph_failures": record.consecutive_graph_failures,
        }

        def _query() -> Any:
            return self._client.table("autonomous_loop").upsert(row, on_conflict="loop_id").execute()

        self._run("save_autonomous_loop", "autonomous_loop", _query, loop_id=str(record.loop_id))

    def get_autonomous_loop(self, loop_id: UUID) -> AutonomousLoopRecord | None:
        def _query() -> Any:
            return self._client.table("autonomous_loop").select("*").eq("loop_id", str(loop_id)).limit(1).execute()

        res = self._run("get_autonomous_loop", "autonomous_loop", _query, loop_id=str(loop_id))
        if not res.data:
            return None
        return _row_to_autonomous_loop(res.data[0])

    def get_autonomous_loop_for_identity(self, identity_id: UUID) -> AutonomousLoopRecord | None:
        def _query() -> Any:
            return (
                self._client.table("autonomous_loop")
                .select("*")
                .eq("identity_id", str(identity_id))
                .not_.in_("status", ["completed", "failed"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        res = self._run("get_autonomous_loop_for_identity", "autonomous_loop", _query, identity_id=str(identity_id))
        if not res.data:
            return None
        return _row_to_autonomous_loop(res.data[0])

    def list_autonomous_loops(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[AutonomousLoopRecord]:
        lim = max(1, min(limit, 100))

        def _query() -> Any:
            q = self._client.table("autonomous_loop").select("*")
            if status is not None:
                q = q.eq("status", status)
            return q.order("created_at", desc=True).limit(lim).execute()

        res = self._run("list_autonomous_loops", "autonomous_loop", _query, status=status, limit=lim)
        if not res.data:
            return []
        return [_row_to_autonomous_loop(r) for r in res.data]

    def get_next_pending_loop(self) -> AutonomousLoopRecord | None:
        from datetime import datetime, timedelta, timezone

        lock_timeout = timedelta(seconds=300)
        cutoff = (datetime.now(timezone.utc) - lock_timeout).isoformat()

        def _query() -> Any:
            return (
                self._client.table("autonomous_loop")
                .select("*")
                .in_("status", ["pending", "running"])
                .or_(f"locked_at.is.null,locked_at.lt.{cutoff}")
                .order("created_at")
                .limit(1)
                .execute()
            )

        res = self._run("get_next_pending_loop", "autonomous_loop", _query)
        if not res.data:
            return None
        return _row_to_autonomous_loop(res.data[0])

    def try_acquire_loop_lock(
        self,
        loop_id: UUID,
        locked_by: str,
        lock_timeout_seconds: int = 300,
    ) -> bool:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=lock_timeout_seconds)).isoformat()

        def _query() -> Any:
            return (
                self._client.table("autonomous_loop")
                .update({"locked_at": now.isoformat(), "locked_by": locked_by, "updated_at": now.isoformat()})
                .eq("loop_id", str(loop_id))
                .or_(f"locked_at.is.null,locked_at.lt.{cutoff}")
                .execute()
            )

        res = self._run("try_acquire_loop_lock", "autonomous_loop", _query, loop_id=str(loop_id))
        return bool(res.data)

    def release_loop_lock(self, loop_id: UUID) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        def _query() -> Any:
            return (
                self._client.table("autonomous_loop")
                .update({"locked_at": None, "locked_by": None, "updated_at": now})
                .eq("loop_id", str(loop_id))
                .execute()
            )

        self._run("release_loop_lock", "autonomous_loop", _query, loop_id=str(loop_id))

    def update_loop_state(
        self,
        loop_id: UUID,
        *,
        status: str | None = None,
        phase: str | None = None,
        iteration_count: int | None = None,
        current_thread_id: UUID | None = None,
        current_graph_run_id: UUID | None = None,
        last_staging_snapshot_id: UUID | None = None,
        last_evaluator_status: str | None = None,
        last_evaluator_score: float | None = None,
        last_alignment_score: float | None = None,
        exploration_directions: list | None = None,
        completed_directions: list | None = None,
        proposed_staging_id: UUID | None = None,
        total_staging_count: int | None = None,
        best_rating: int | None = None,
        last_error: str | None = None,
        consecutive_graph_failures: int | None = None,
        reset_loop_error: bool = False,
    ) -> AutonomousLoopRecord | None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        patch: dict[str, Any] = {"updated_at": now}

        if status is not None:
            patch["status"] = status
            if status == "completed":
                patch["completed_at"] = now
        if phase is not None:
            patch["phase"] = phase
        if iteration_count is not None:
            patch["iteration_count"] = iteration_count
        if current_thread_id is not None:
            patch["current_thread_id"] = str(current_thread_id)
        if current_graph_run_id is not None:
            patch["current_graph_run_id"] = str(current_graph_run_id)
        if last_staging_snapshot_id is not None:
            patch["last_staging_snapshot_id"] = str(last_staging_snapshot_id)
        if last_evaluator_status is not None:
            patch["last_evaluator_status"] = last_evaluator_status
        if last_evaluator_score is not None:
            patch["last_evaluator_score"] = last_evaluator_score
        if last_alignment_score is not None:
            patch["last_alignment_score"] = last_alignment_score
        if exploration_directions is not None:
            patch["exploration_directions"] = exploration_directions
        if completed_directions is not None:
            patch["completed_directions"] = completed_directions
        if proposed_staging_id is not None:
            patch["proposed_staging_id"] = str(proposed_staging_id)
            patch["proposed_at"] = now
        if total_staging_count is not None:
            patch["total_staging_count"] = total_staging_count
        if best_rating is not None:
            patch["best_rating"] = best_rating
        if reset_loop_error:
            patch["last_error"] = None
            patch["consecutive_graph_failures"] = 0
        if last_error is not None:
            patch["last_error"] = last_error
        if consecutive_graph_failures is not None:
            patch["consecutive_graph_failures"] = consecutive_graph_failures

        def _query() -> Any:
            return self._client.table("autonomous_loop").update(patch).eq("loop_id", str(loop_id)).execute()

        res = self._run("update_loop_state", "autonomous_loop", _query, loop_id=str(loop_id))
        if not res.data:
            return None
        return _row_to_autonomous_loop(res.data[0])
