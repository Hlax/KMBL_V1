"""Placeholder persistence — swap for Supabase/Postgres per docs/07_DATA_MODEL_AND_STACK_MAP.md."""

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
)


class Repository(Protocol):
    """TODO: implement with supabase-py or SQLAlchemy + Supabase Postgres."""

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
        """Latest denormalized view for GET /orchestrator/runs/{id}."""
        ...

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None: ...


class InMemoryRepository:
    """Development-only store."""

    def __init__(self) -> None:
        self._graph_runs: dict[str, GraphRunRecord] = {}
        self._checkpoints: list[CheckpointRecord] = []
        self._role_invocations: list[RoleInvocationRecord] = []
        self._build_specs: dict[str, BuildSpecRecord] = {}
        self._build_candidates: dict[str, BuildCandidateRecord] = {}
        self._evaluation_reports: dict[str, EvaluationReportRecord] = {}
        self._run_snapshots: dict[str, dict[str, Any]] = {}

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
        return self._run_snapshots.get(str(graph_run_id))
