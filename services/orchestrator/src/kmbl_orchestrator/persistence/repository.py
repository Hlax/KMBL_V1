"""Persistence — Supabase (production) or in-memory (tests / no credentials)."""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from uuid import UUID

_log = logging.getLogger(__name__)

from kmbl_orchestrator.domain import (
    AutonomousLoopRecord,
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunEventRecord,
    GraphRunRecord,
    IdentityProfileRecord,
    IdentitySourceRecord,
    PublicationSnapshotRecord,
    RoleInvocationRecord,
    StagingCheckpointRecord,
    StagingSnapshotRecord,
    ThreadRecord,
    WorkingStagingRecord,
)


class Repository(Protocol):
    """System of record for runtime entities (docs/07)."""

    def ensure_thread(self, record: ThreadRecord) -> None: ...

    def get_thread(self, thread_id: UUID) -> ThreadRecord | None: ...

    def update_thread_current_checkpoint(
        self, thread_id: UUID, checkpoint_id: UUID
    ) -> None:
        """Set thread.current_checkpoint_id (e.g. after post_role checkpoint)."""

    def save_graph_run(self, record: GraphRunRecord) -> None: ...
    def get_graph_run(self, graph_run_id: UUID) -> GraphRunRecord | None: ...

    def list_graph_runs(
        self,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        identity_id: UUID | None = None,
        limit: int = 50,
    ) -> list[GraphRunRecord]:
        """Newest ``started_at`` first. Optional filters; ``identity_id`` via ``thread`` rows."""

    def aggregate_role_invocation_stats_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int | None]]:
        """``(count, max_iteration_index)`` per id; ``(0, None)`` when no invocations."""

    def latest_staging_snapshot_ids_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, UUID | None]:
        """Newest staging row per graph_run (by ``created_at``); value None if none."""

    def graph_run_ids_with_interrupt_orchestrator_error(
        self, graph_run_ids: list[UUID]
    ) -> set[UUID]:
        """Ids where latest interrupt checkpoint has ``state_json.orchestrator_error`` dict."""

    def update_graph_run_status(
        self,
        graph_run_id: UUID,
        status: Literal["running", "paused", "completed", "failed"],
        ended_at: str | None,
    ) -> None: ...

    def mark_graph_run_resuming(self, graph_run_id: UUID) -> None:
        """Set ``status`` to ``running`` and clear ``ended_at`` (operator resume / Pass K)."""

    def save_checkpoint(self, record: CheckpointRecord) -> None: ...
    def save_role_invocation(self, record: RoleInvocationRecord) -> None: ...
    def save_build_spec(self, record: BuildSpecRecord) -> None: ...

    def get_build_spec(self, build_spec_id: UUID) -> BuildSpecRecord | None: ...
    def save_build_candidate(self, record: BuildCandidateRecord) -> None: ...
    def get_build_candidate(self, build_candidate_id: UUID) -> BuildCandidateRecord | None: ...
    def save_evaluation_report(self, record: EvaluationReportRecord) -> None: ...
    def get_evaluation_report(
        self, evaluation_report_id: UUID
    ) -> EvaluationReportRecord | None: ...

    def get_latest_build_spec_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildSpecRecord | None: ...

    def get_latest_build_candidate_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildCandidateRecord | None: ...

    def get_latest_evaluation_report_for_graph_run(
        self, graph_run_id: UUID
    ) -> EvaluationReportRecord | None: ...

    def list_evaluation_reports_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 50
    ) -> list[EvaluationReportRecord]:
        """Evaluation rows for this graph run, oldest ``created_at`` first (iteration order)."""

    def get_latest_failed_role_invocation_for_graph_run(
        self, graph_run_id: UUID
    ) -> RoleInvocationRecord | None:
        """Most recent failed role row for this graph_run (KiloClaw / contract errors)."""

    def get_latest_interrupt_orchestrator_error(
        self, graph_run_id: UUID
    ) -> dict[str, Any] | None:
        """Payload from the newest interrupt checkpoint's ``state_json.orchestrator_error``."""

    def attach_run_snapshot(self, graph_run_id: UUID, payload: dict[str, Any]) -> None:
        """Deprecated for DB path — post-run checkpoint holds state; kept for API compat."""

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None: ...

    def save_graph_run_event(self, record: GraphRunEventRecord) -> None: ...

    def list_graph_run_events(
        self, graph_run_id: UUID, *, limit: int = 200
    ) -> list[GraphRunEventRecord]: ...

    def list_role_invocations_for_graph_run(
        self, graph_run_id: UUID
    ) -> list[RoleInvocationRecord]:
        """Oldest ``started_at`` first (execution order)."""

    def list_staging_snapshots_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[StagingSnapshotRecord]:
        """Newest ``created_at`` first."""

    def list_publications_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[PublicationSnapshotRecord]:
        """Newest ``published_at`` first; rows with matching ``graph_run_id`` only."""

    def get_latest_checkpoint_for_graph_run(
        self, graph_run_id: UUID
    ) -> CheckpointRecord | None:
        """Most recent checkpoint for this run (any kind)."""

    def list_stale_running_graph_run_ids(self, older_than_seconds: int) -> list[UUID]:
        """graph_run.status == running and started_at older than threshold (best-effort)."""

    def save_staging_snapshot(self, record: StagingSnapshotRecord) -> None: ...

    def get_staging_snapshot(
        self, staging_snapshot_id: UUID
    ) -> StagingSnapshotRecord | None: ...

    def list_staging_snapshots(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
        identity_id: UUID | None = None,
    ) -> list[StagingSnapshotRecord]:
        """Persisted rows only, newest ``created_at`` first."""
        ...

    def list_staging_snapshots_for_thread(
        self,
        thread_id: UUID,
        *,
        limit: int = 10,
    ) -> list[StagingSnapshotRecord]:
        """List staging snapshots for a specific thread, newest first."""
        ...

    def update_staging_snapshot_status(
        self,
        staging_snapshot_id: UUID,
        status: str,
        *,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> StagingSnapshotRecord | None:
        """Update ``staging_snapshot.status`` and matching audit columns (approve / reject / unapprove)."""

    def rate_staging_snapshot(
        self,
        staging_snapshot_id: UUID,
        rating: int,
        feedback: str | None = None,
    ) -> StagingSnapshotRecord | None:
        """Set user_rating (1-5), user_feedback, and rated_at on a staging snapshot."""

    # --- Autonomous Loop ---

    def save_autonomous_loop(self, record: "AutonomousLoopRecord") -> None: ...

    def get_autonomous_loop(self, loop_id: UUID) -> "AutonomousLoopRecord | None": ...

    def get_autonomous_loop_for_identity(self, identity_id: UUID) -> "AutonomousLoopRecord | None":
        """Get active loop for an identity (status not completed/failed)."""
        ...

    def list_autonomous_loops(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list["AutonomousLoopRecord"]: ...

    def get_next_pending_loop(self) -> "AutonomousLoopRecord | None":
        """Next loop with ``status`` in (pending, running), lock expired or unset — cron driver."""
        ...

    def try_acquire_loop_lock(
        self,
        loop_id: UUID,
        locked_by: str,
        lock_timeout_seconds: int = 300,
    ) -> bool:
        """Try to acquire lock on a loop. Returns True if acquired."""
        ...

    def release_loop_lock(self, loop_id: UUID) -> None:
        """Release lock on a loop."""
        ...

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
    ) -> "AutonomousLoopRecord | None": ...

    def save_publication_snapshot(self, record: PublicationSnapshotRecord) -> None: ...

    def get_publication_snapshot(
        self, publication_snapshot_id: UUID
    ) -> PublicationSnapshotRecord | None: ...

    def list_publication_snapshots(
        self,
        *,
        limit: int = 20,
        identity_id: UUID | None = None,
        visibility: str | None = None,
    ) -> list[PublicationSnapshotRecord]:
        """Newest ``published_at`` first."""

    def list_publications_for_staging(
        self, staging_snapshot_id: UUID
    ) -> list[PublicationSnapshotRecord]:
        """All publication rows for this staging id, newest ``published_at`` first."""

    def publication_counts_for_staging_snapshot_ids(
        self, staging_snapshot_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Count of ``publication_snapshot`` rows per ``source_staging_snapshot_id``."""

    def get_latest_publication_snapshot(
        self, *, identity_id: UUID | None = None
    ) -> PublicationSnapshotRecord | None:
        """Most recent published row, optionally scoped to ``identity_id``."""

    def create_identity_source(self, record: IdentitySourceRecord) -> None: ...

    def list_identity_sources(self, identity_id: UUID) -> list[IdentitySourceRecord]:
        """Newest ``created_at`` first."""

    def get_identity_profile(self, identity_id: UUID) -> IdentityProfileRecord | None: ...

    def upsert_identity_profile(self, record: IdentityProfileRecord) -> None: ...

    # --- Working staging ---

    def get_working_staging_for_thread(
        self, thread_id: UUID
    ) -> WorkingStagingRecord | None:
        """Return the current working staging record for this thread, or None."""

    def save_working_staging(self, record: WorkingStagingRecord) -> None:
        """Insert or fully replace a working staging record (keyed by working_staging_id)."""

    def save_staging_checkpoint(self, record: StagingCheckpointRecord) -> None: ...

    def get_staging_checkpoint(
        self, staging_checkpoint_id: UUID
    ) -> StagingCheckpointRecord | None: ...

    def list_staging_checkpoints(
        self, working_staging_id: UUID, *, limit: int = 50
    ) -> list[StagingCheckpointRecord]:
        """Newest ``created_at`` first."""

    # --- Transaction & Thread Locking ---

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Context manager for atomic multi-write operations.

        All writes within the context are committed together or rolled back.
        Implementations may provide best-effort atomicity depending on backend
        constraints (e.g. PostgREST has no true SQL transactions).
        """
        yield  # default: no-op passthrough

    @contextmanager
    def thread_lock(self, thread_id: UUID, timeout_seconds: int = 300) -> Iterator[None]:
        """Advisory lock for thread-level concurrency control.

        Prevents concurrent graph runs on the same thread.  Acquires on entry,
        releases on exit (including on exception).
        """
        acquired = self.try_acquire_thread_lock(
            thread_id, locked_by="thread_lock_ctx", timeout_seconds=timeout_seconds,
        )
        if not acquired:
            raise TimeoutError(
                f"Could not acquire thread lock for {thread_id} "
                f"within {timeout_seconds}s"
            )
        try:
            yield
        finally:
            self.release_thread_lock(thread_id)

    def try_acquire_thread_lock(
        self, thread_id: UUID, locked_by: str, timeout_seconds: int = 300,
    ) -> bool:
        """Try to acquire an advisory lock on a thread. Returns True if acquired."""
        return True  # default: always succeeds (no-op)

    def release_thread_lock(self, thread_id: UUID) -> None:
        """Release advisory lock on a thread."""


class InMemoryRepository:
    """Development / unit tests — no external DB."""

    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._graph_runs: dict[str, GraphRunRecord] = {}
        self._checkpoints: list[CheckpointRecord] = []
        self._role_invocations: list[RoleInvocationRecord] = []
        self._build_specs: dict[str, BuildSpecRecord] = {}
        self._build_candidates: dict[str, BuildCandidateRecord] = {}
        self._evaluation_reports: dict[str, EvaluationReportRecord] = {}
        self._run_snapshots: dict[str, dict[str, Any]] = {}
        self._graph_run_events: list[GraphRunEventRecord] = []
        self._staging_snapshots: dict[str, StagingSnapshotRecord] = {}
        self._working_stagings: dict[str, WorkingStagingRecord] = {}
        self._staging_checkpoints: dict[str, StagingCheckpointRecord] = {}
        self._publications: dict[str, PublicationSnapshotRecord] = {}
        self._identity_sources: list[IdentitySourceRecord] = []
        self._identity_profiles: dict[str, IdentityProfileRecord] = {}
        self._autonomous_loops: dict[str, AutonomousLoopRecord] = {}
        # Thread-level advisory locks
        self._thread_locks: dict[str, threading.Lock] = {}
        self._thread_lock_guard = threading.Lock()
        self._thread_lock_holders: dict[str, str] = {}

    def ensure_thread(self, record: ThreadRecord) -> None:
        key = str(record.thread_id)
        existing = self._threads.get(key)
        if existing is not None and record.current_checkpoint_id is None:
            record = record.model_copy(
                update={"current_checkpoint_id": existing.current_checkpoint_id}
            )
        self._threads[key] = record

    def get_thread(self, thread_id: UUID) -> ThreadRecord | None:
        return self._threads.get(str(thread_id))

    def update_thread_current_checkpoint(
        self, thread_id: UUID, checkpoint_id: UUID
    ) -> None:
        key = str(thread_id)
        t = self._threads.get(key)
        if t is None:
            return
        self._threads[key] = t.model_copy(
            update={"current_checkpoint_id": checkpoint_id}
        )

    def save_graph_run(self, record: GraphRunRecord) -> None:
        self._graph_runs[str(record.graph_run_id)] = record

    def get_graph_run(self, graph_run_id: UUID) -> GraphRunRecord | None:
        return self._graph_runs.get(str(graph_run_id))

    def list_graph_runs(
        self,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        identity_id: UUID | None = None,
        limit: int = 50,
    ) -> list[GraphRunRecord]:
        rows = list(self._graph_runs.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if trigger_type is not None:
            rows = [r for r in rows if r.trigger_type == trigger_type]
        if identity_id is not None:
            allowed = {
                str(t.thread_id)
                for t in self._threads.values()
                if t.identity_id == identity_id
            }
            rows = [
                r
                for r in rows
                if str(r.thread_id) in allowed or r.identity_id == identity_id
            ]
        rows.sort(key=lambda r: r.started_at, reverse=True)
        return rows[: max(0, limit)]

    def aggregate_role_invocation_stats_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int | None]]:
        if not graph_run_ids:
            return {}
        want = {str(g) for g in graph_run_ids}
        acc: dict[str, list[RoleInvocationRecord]] = {}
        for r in self._role_invocations:
            gs = str(r.graph_run_id)
            if gs in want:
                acc.setdefault(gs, []).append(r)
        out: dict[UUID, tuple[int, int | None]] = {}
        for g in graph_run_ids:
            rows = acc.get(str(g), [])
            if not rows:
                out[g] = (0, None)
            else:
                out[g] = (len(rows), max(x.iteration_index for x in rows))
        return out

    def latest_staging_snapshot_ids_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, UUID | None]:
        if not graph_run_ids:
            return {}
        want = {str(g) for g in graph_run_ids}
        out: dict[UUID, UUID | None] = {g: None for g in graph_run_ids}
        by_gid: dict[str, list[StagingSnapshotRecord]] = {}
        for s in self._staging_snapshots.values():
            if s.graph_run_id is None:
                continue
            gs = str(s.graph_run_id)
            if gs in want:
                by_gid.setdefault(gs, []).append(s)
        for g in graph_run_ids:
            rows = by_gid.get(str(g), [])
            if not rows:
                continue
            rows.sort(key=lambda x: x.created_at, reverse=True)
            out[g] = rows[0].staging_snapshot_id
        return out

    def graph_run_ids_with_interrupt_orchestrator_error(
        self, graph_run_ids: list[UUID]
    ) -> set[UUID]:
        if not graph_run_ids:
            return set()
        want = {str(g) for g in graph_run_ids}
        by_gid: dict[str, list[CheckpointRecord]] = {}
        for c in self._checkpoints:
            if c.checkpoint_kind != "interrupt":
                continue
            gs = str(c.graph_run_id)
            if gs not in want:
                continue
            by_gid.setdefault(gs, []).append(c)
        out: set[UUID] = set()
        for g in graph_run_ids:
            rows = by_gid.get(str(g), [])
            if not rows:
                continue
            rows.sort(key=lambda c: c.created_at)
            last = rows[-1].state_json
            err = last.get("orchestrator_error") if isinstance(last, dict) else None
            if isinstance(err, dict):
                out.add(g)
        return out

    def update_graph_run_status(
        self,
        graph_run_id: UUID,
        status: Literal["running", "paused", "completed", "failed"],
        ended_at: str | None,
    ) -> None:
        r = self._graph_runs.get(str(graph_run_id))
        if r is None:
            return
        self._graph_runs[str(graph_run_id)] = r.model_copy(
            update={"status": status, "ended_at": ended_at}
        )

    def mark_graph_run_resuming(self, graph_run_id: UUID) -> None:
        r = self._graph_runs.get(str(graph_run_id))
        if r is None:
            return
        self._graph_runs[str(graph_run_id)] = r.model_copy(
            update={"status": "running", "ended_at": None}
        )

    def save_checkpoint(self, record: CheckpointRecord) -> None:
        self._checkpoints.append(record)

    def save_role_invocation(self, record: RoleInvocationRecord) -> None:
        self._role_invocations.append(record)

    def save_build_spec(self, record: BuildSpecRecord) -> None:
        self._build_specs[str(record.build_spec_id)] = record

    def get_build_spec(self, build_spec_id: UUID) -> BuildSpecRecord | None:
        return self._build_specs.get(str(build_spec_id))

    def save_build_candidate(self, record: BuildCandidateRecord) -> None:
        self._build_candidates[str(record.build_candidate_id)] = record

    def get_build_candidate(self, build_candidate_id: UUID) -> BuildCandidateRecord | None:
        return self._build_candidates.get(str(build_candidate_id))

    def save_evaluation_report(self, record: EvaluationReportRecord) -> None:
        self._evaluation_reports[str(record.evaluation_report_id)] = record

    def get_evaluation_report(
        self, evaluation_report_id: UUID
    ) -> EvaluationReportRecord | None:
        return self._evaluation_reports.get(str(evaluation_report_id))

    def get_latest_build_spec_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildSpecRecord | None:
        matches = [
            b for b in self._build_specs.values() if b.graph_run_id == graph_run_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda b: b.created_at)

    def get_latest_build_candidate_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildCandidateRecord | None:
        matches = [
            c for c in self._build_candidates.values() if c.graph_run_id == graph_run_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda c: c.created_at)

    def get_latest_evaluation_report_for_graph_run(
        self, graph_run_id: UUID
    ) -> EvaluationReportRecord | None:
        matches = [
            e for e in self._evaluation_reports.values() if e.graph_run_id == graph_run_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e.created_at)

    def list_evaluation_reports_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 50
    ) -> list[EvaluationReportRecord]:
        rows = [
            e for e in self._evaluation_reports.values() if e.graph_run_id == graph_run_id
        ]
        rows.sort(key=lambda e: e.created_at)
        return rows[:limit] if limit else rows

    def get_latest_failed_role_invocation_for_graph_run(
        self, graph_run_id: UUID
    ) -> RoleInvocationRecord | None:
        failed = [
            r
            for r in self._role_invocations
            if r.graph_run_id == graph_run_id and r.status == "failed"
        ]
        if not failed:
            return None
        return max(failed, key=lambda r: r.started_at)

    def get_latest_interrupt_orchestrator_error(
        self, graph_run_id: UUID
    ) -> dict[str, Any] | None:
        rows = [
            c
            for c in self._checkpoints
            if c.graph_run_id == graph_run_id and c.checkpoint_kind == "interrupt"
        ]
        if not rows:
            return None
        rows.sort(key=lambda c: c.created_at)
        last = rows[-1].state_json
        err = last.get("orchestrator_error") if isinstance(last, dict) else None
        return err if isinstance(err, dict) else None

    def attach_run_snapshot(self, graph_run_id: UUID, payload: dict[str, Any]) -> None:
        self._run_snapshots[str(graph_run_id)] = payload

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None:
        gid = str(graph_run_id)
        if gid in self._run_snapshots:
            return self._run_snapshots[gid]
        post = [
            c
            for c in self._checkpoints
            if str(c.graph_run_id) == gid and c.checkpoint_kind == "post_role"
        ]
        if not post:
            return None
        post.sort(key=lambda c: c.created_at)
        return post[-1].state_json

    def save_graph_run_event(self, record: GraphRunEventRecord) -> None:
        self._graph_run_events.append(record)

    def list_graph_run_events(
        self, graph_run_id: UUID, *, limit: int = 200
    ) -> list[GraphRunEventRecord]:
        gid = str(graph_run_id)
        rows = [e for e in self._graph_run_events if str(e.graph_run_id) == gid]
        rows.sort(key=lambda e: e.created_at)
        return rows[-limit:] if limit else rows

    def list_role_invocations_for_graph_run(
        self, graph_run_id: UUID
    ) -> list[RoleInvocationRecord]:
        gid = str(graph_run_id)
        rows = [r for r in self._role_invocations if str(r.graph_run_id) == gid]
        rows.sort(key=lambda r: r.started_at)
        return rows

    def list_staging_snapshots_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[StagingSnapshotRecord]:
        gid = str(graph_run_id)
        rows = [
            r
            for r in self._staging_snapshots.values()
            if r.graph_run_id is not None and str(r.graph_run_id) == gid
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[: max(0, limit)]

    def list_publications_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[PublicationSnapshotRecord]:
        gid = str(graph_run_id)
        rows = [
            r
            for r in self._publications.values()
            if r.graph_run_id is not None and str(r.graph_run_id) == gid
        ]
        rows.sort(key=lambda r: r.published_at, reverse=True)
        return rows[: max(0, limit)]

    def get_latest_checkpoint_for_graph_run(
        self, graph_run_id: UUID
    ) -> CheckpointRecord | None:
        gid = str(graph_run_id)
        rows = [c for c in self._checkpoints if str(c.graph_run_id) == gid]
        if not rows:
            return None
        rows.sort(key=lambda c: c.created_at, reverse=True)
        return rows[0]

    def list_stale_running_graph_run_ids(self, older_than_seconds: int) -> list[UUID]:
        if older_than_seconds <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        out: list[UUID] = []
        for gr in self._graph_runs.values():
            if gr.status != "running":
                continue
            try:
                started = datetime.fromisoformat(
                    gr.started_at.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if started < cutoff:
                out.append(gr.graph_run_id)
        return out

    def save_staging_snapshot(self, record: StagingSnapshotRecord) -> None:
        self._staging_snapshots[str(record.staging_snapshot_id)] = record

    def get_staging_snapshot(
        self, staging_snapshot_id: UUID
    ) -> StagingSnapshotRecord | None:
        return self._staging_snapshots.get(str(staging_snapshot_id))

    def list_staging_snapshots(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
        identity_id: UUID | None = None,
    ) -> list[StagingSnapshotRecord]:
        rows = list(self._staging_snapshots.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        if identity_id is not None:
            rows = [r for r in rows if r.identity_id == identity_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[: max(0, limit)]

    def list_staging_snapshots_for_thread(
        self,
        thread_id: UUID,
        *,
        limit: int = 10,
    ) -> list[StagingSnapshotRecord]:
        rows = [r for r in self._staging_snapshots.values() if r.thread_id == thread_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[: max(0, limit)]

    def update_staging_snapshot_status(
        self,
        staging_snapshot_id: UUID,
        status: str,
        *,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> StagingSnapshotRecord | None:
        from kmbl_orchestrator.staging.status_transition import apply_staging_status_transition

        key = str(staging_snapshot_id)
        cur = self._staging_snapshots.get(key)
        if cur is None:
            return None
        updated = apply_staging_status_transition(
            cur,
            status,
            approved_by=approved_by,
            rejected_by=rejected_by,
            rejection_reason=rejection_reason,
        )
        self._staging_snapshots[key] = updated
        return updated

    def rate_staging_snapshot(
        self,
        staging_snapshot_id: UUID,
        rating: int,
        feedback: str | None = None,
    ) -> StagingSnapshotRecord | None:
        from datetime import datetime, timezone

        key = str(staging_snapshot_id)
        cur = self._staging_snapshots.get(key)
        if cur is None:
            return None
        updated = StagingSnapshotRecord(
            **{
                **cur.model_dump(),
                "user_rating": rating,
                "user_feedback": feedback,
                "rated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._staging_snapshots[key] = updated
        return updated

    # --- Autonomous Loop (in-memory) ---

    def save_autonomous_loop(self, record: AutonomousLoopRecord) -> None:
        self._autonomous_loops[str(record.loop_id)] = record

    def get_autonomous_loop(self, loop_id: UUID) -> AutonomousLoopRecord | None:
        return self._autonomous_loops.get(str(loop_id))

    def get_autonomous_loop_for_identity(self, identity_id: UUID) -> AutonomousLoopRecord | None:
        for loop in self._autonomous_loops.values():
            if loop.identity_id == identity_id and loop.status not in ("completed", "failed"):
                return loop
        return None

    def list_autonomous_loops(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[AutonomousLoopRecord]:
        rows = list(self._autonomous_loops.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[: max(0, limit)]

    def get_next_pending_loop(self) -> AutonomousLoopRecord | None:
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        lock_timeout = timedelta(seconds=300)
        for loop in sorted(self._autonomous_loops.values(), key=lambda r: r.created_at):
            if loop.status not in ("pending", "running"):
                continue
            if loop.locked_at:
                locked_time = datetime.fromisoformat(loop.locked_at.replace("Z", "+00:00"))
                if now - locked_time < lock_timeout:
                    continue
            return loop
        return None

    def try_acquire_loop_lock(
        self,
        loop_id: UUID,
        locked_by: str,
        lock_timeout_seconds: int = 300,
    ) -> bool:
        from datetime import datetime, timezone, timedelta

        key = str(loop_id)
        loop = self._autonomous_loops.get(key)
        if loop is None:
            return False
        now = datetime.now(timezone.utc)
        if loop.locked_at:
            locked_time = datetime.fromisoformat(loop.locked_at.replace("Z", "+00:00"))
            if now - locked_time < timedelta(seconds=lock_timeout_seconds):
                return False
        updated = AutonomousLoopRecord(
            **{
                **loop.model_dump(),
                "locked_at": now.isoformat(),
                "locked_by": locked_by,
                "updated_at": now.isoformat(),
            }
        )
        self._autonomous_loops[key] = updated
        return True

    def release_loop_lock(self, loop_id: UUID) -> None:
        from datetime import datetime, timezone

        key = str(loop_id)
        loop = self._autonomous_loops.get(key)
        if loop is None:
            return
        updated = AutonomousLoopRecord(
            **{
                **loop.model_dump(),
                "locked_at": None,
                "locked_by": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._autonomous_loops[key] = updated

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

        key = str(loop_id)
        loop = self._autonomous_loops.get(key)
        if loop is None:
            return None
        updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if status is not None:
            updates["status"] = status
            if status == "completed":
                updates["completed_at"] = datetime.now(timezone.utc).isoformat()
        if phase is not None:
            updates["phase"] = phase
        if iteration_count is not None:
            updates["iteration_count"] = iteration_count
        if current_thread_id is not None:
            updates["current_thread_id"] = current_thread_id
        if current_graph_run_id is not None:
            updates["current_graph_run_id"] = current_graph_run_id
        if last_staging_snapshot_id is not None:
            updates["last_staging_snapshot_id"] = last_staging_snapshot_id
        if last_evaluator_status is not None:
            updates["last_evaluator_status"] = last_evaluator_status
        if last_evaluator_score is not None:
            updates["last_evaluator_score"] = last_evaluator_score
        if last_alignment_score is not None:
            updates["last_alignment_score"] = last_alignment_score
        if exploration_directions is not None:
            updates["exploration_directions"] = exploration_directions
        if completed_directions is not None:
            updates["completed_directions"] = completed_directions
        if proposed_staging_id is not None:
            updates["proposed_staging_id"] = proposed_staging_id
            updates["proposed_at"] = datetime.now(timezone.utc).isoformat()
        if total_staging_count is not None:
            updates["total_staging_count"] = total_staging_count
        if best_rating is not None:
            updates["best_rating"] = best_rating
        if reset_loop_error:
            updates["last_error"] = None
            updates["consecutive_graph_failures"] = 0
        if last_error is not None:
            updates["last_error"] = last_error
        if consecutive_graph_failures is not None:
            updates["consecutive_graph_failures"] = consecutive_graph_failures
        updated = AutonomousLoopRecord(**{**loop.model_dump(), **updates})
        self._autonomous_loops[key] = updated
        return updated

    def save_publication_snapshot(self, record: PublicationSnapshotRecord) -> None:
        self._publications[str(record.publication_snapshot_id)] = record

    def get_publication_snapshot(
        self, publication_snapshot_id: UUID
    ) -> PublicationSnapshotRecord | None:
        return self._publications.get(str(publication_snapshot_id))

    def list_publication_snapshots(
        self,
        *,
        limit: int = 20,
        identity_id: UUID | None = None,
        visibility: str | None = None,
    ) -> list[PublicationSnapshotRecord]:
        rows = list(self._publications.values())
        if identity_id is not None:
            rows = [r for r in rows if r.identity_id == identity_id]
        if visibility is not None:
            rows = [r for r in rows if r.visibility == visibility]
        rows.sort(key=lambda r: r.published_at, reverse=True)
        return rows[: max(0, limit)]

    def list_publications_for_staging(
        self, staging_snapshot_id: UUID
    ) -> list[PublicationSnapshotRecord]:
        sid = str(staging_snapshot_id)
        rows = [
            r
            for r in self._publications.values()
            if str(r.source_staging_snapshot_id) == sid
        ]
        rows.sort(key=lambda r: r.published_at, reverse=True)
        return rows

    def publication_counts_for_staging_snapshot_ids(
        self, staging_snapshot_ids: list[UUID]
    ) -> dict[UUID, int]:
        if not staging_snapshot_ids:
            return {}
        want = {str(s) for s in staging_snapshot_ids}
        counts: dict[str, int] = {}
        for r in self._publications.values():
            sid = str(r.source_staging_snapshot_id)
            if sid in want:
                counts[sid] = counts.get(sid, 0) + 1
        return {s: counts.get(str(s), 0) for s in staging_snapshot_ids}

    def get_latest_publication_snapshot(
        self, *, identity_id: UUID | None = None
    ) -> PublicationSnapshotRecord | None:
        rows = list(self._publications.values())
        if identity_id is not None:
            rows = [r for r in rows if r.identity_id == identity_id]
        if not rows:
            return None
        rows.sort(key=lambda r: r.published_at, reverse=True)
        return rows[0]

    def create_identity_source(self, record: IdentitySourceRecord) -> None:
        self._identity_sources.append(record)

    def list_identity_sources(self, identity_id: UUID) -> list[IdentitySourceRecord]:
        rows = [r for r in self._identity_sources if r.identity_id == identity_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

    def get_identity_profile(self, identity_id: UUID) -> IdentityProfileRecord | None:
        return self._identity_profiles.get(str(identity_id))

    def upsert_identity_profile(self, record: IdentityProfileRecord) -> None:
        self._identity_profiles[str(record.identity_id)] = record

    # ---- Working staging ----

    def get_working_staging_for_thread(
        self, thread_id: UUID
    ) -> WorkingStagingRecord | None:
        for ws in self._working_stagings.values():
            if ws.thread_id == thread_id:
                return ws
        return None

    def save_working_staging(self, record: WorkingStagingRecord) -> None:
        self._working_stagings[str(record.working_staging_id)] = record

    def save_staging_checkpoint(self, record: StagingCheckpointRecord) -> None:
        self._staging_checkpoints[str(record.staging_checkpoint_id)] = record

    def get_staging_checkpoint(
        self, staging_checkpoint_id: UUID
    ) -> StagingCheckpointRecord | None:
        return self._staging_checkpoints.get(str(staging_checkpoint_id))

    def list_staging_checkpoints(
        self, working_staging_id: UUID, *, limit: int = 50
    ) -> list[StagingCheckpointRecord]:
        wsid = str(working_staging_id)
        rows = [
            r for r in self._staging_checkpoints.values()
            if str(r.working_staging_id) == wsid
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    # --- Transaction & Thread Locking ---

    _SNAPSHOT_ATTRS = (
        "_threads", "_graph_runs", "_checkpoints", "_role_invocations",
        "_build_specs", "_build_candidates", "_evaluation_reports",
        "_run_snapshots", "_graph_run_events", "_staging_snapshots",
        "_working_stagings", "_staging_checkpoints", "_publications",
        "_identity_sources", "_identity_profiles", "_autonomous_loops",
    )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Snapshot/rollback: all writes within the block succeed or are reverted."""
        snapshot: dict[str, Any] = {}
        for attr in self._SNAPSHOT_ATTRS:
            val = getattr(self, attr)
            snapshot[attr] = copy.copy(val)
        try:
            yield
        except BaseException:
            for attr, val in snapshot.items():
                setattr(self, attr, val)
            raise

    def _get_thread_lock(self, thread_id: UUID) -> threading.Lock:
        key = str(thread_id)
        with self._thread_lock_guard:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            return self._thread_locks[key]

    @contextmanager
    def thread_lock(self, thread_id: UUID, timeout_seconds: int = 300) -> Iterator[None]:
        acquired = self.try_acquire_thread_lock(
            thread_id, locked_by="thread_lock_ctx", timeout_seconds=timeout_seconds,
        )
        if not acquired:
            raise TimeoutError(
                f"Could not acquire thread lock for {thread_id} "
                f"within {timeout_seconds}s"
            )
        try:
            yield
        finally:
            self.release_thread_lock(thread_id)

    def try_acquire_thread_lock(
        self, thread_id: UUID, locked_by: str, timeout_seconds: int = 300,
    ) -> bool:
        lock = self._get_thread_lock(thread_id)
        acquired = lock.acquire(timeout=timeout_seconds)
        if acquired:
            self._thread_lock_holders[str(thread_id)] = locked_by
        return acquired

    def release_thread_lock(self, thread_id: UUID) -> None:
        key = str(thread_id)
        with self._thread_lock_guard:
            self._thread_lock_holders.pop(key, None)
            lock = self._thread_locks.get(key)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass  # already released
