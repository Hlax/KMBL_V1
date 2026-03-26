"""Persistence — Supabase (production) or in-memory (tests / no credentials)."""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunRecord,
    RoleInvocationRecord,
    ThreadRecord,
)


class Repository(Protocol):
    """System of record for runtime entities (docs/07)."""

    def ensure_thread(self, record: ThreadRecord) -> None: ...

    def update_thread_current_checkpoint(
        self, thread_id: UUID, checkpoint_id: UUID
    ) -> None:
        """Set thread.current_checkpoint_id (e.g. after post_role checkpoint)."""

    def save_graph_run(self, record: GraphRunRecord) -> None: ...
    def get_graph_run(self, graph_run_id: UUID) -> GraphRunRecord | None: ...
    def update_graph_run_status(
        self,
        graph_run_id: UUID,
        status: Literal["running", "paused", "completed", "failed"],
        ended_at: str | None,
    ) -> None: ...

    def save_checkpoint(self, record: CheckpointRecord) -> None: ...
    def save_role_invocation(self, record: RoleInvocationRecord) -> None: ...
    def save_build_spec(self, record: BuildSpecRecord) -> None: ...

    def get_build_spec(self, build_spec_id: UUID) -> BuildSpecRecord | None: ...
    def save_build_candidate(self, record: BuildCandidateRecord) -> None: ...
    def save_evaluation_report(self, record: EvaluationReportRecord) -> None: ...

    def attach_run_snapshot(self, graph_run_id: UUID, payload: dict[str, Any]) -> None:
        """Deprecated for DB path — post-run checkpoint holds state; kept for API compat."""

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None: ...


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

    def ensure_thread(self, record: ThreadRecord) -> None:
        key = str(record.thread_id)
        existing = self._threads.get(key)
        if existing is not None and record.current_checkpoint_id is None:
            record = record.model_copy(
                update={"current_checkpoint_id": existing.current_checkpoint_id}
            )
        self._threads[key] = record

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

    def save_evaluation_report(self, record: EvaluationReportRecord) -> None:
        self._evaluation_reports[str(record.evaluation_report_id)] = record

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
