"""Supabase-backed repository using supabase-py (Phase 1 tables)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

from supabase import Client, create_client

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunRecord,
    RoleInvocationRecord,
    ThreadRecord,
)
def _ts_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_graph_run(row: dict[str, Any]) -> GraphRunRecord:
    return GraphRunRecord(
        graph_run_id=UUID(row["graph_run_id"]),
        thread_id=UUID(row["thread_id"]),
        trigger_type=cast(
            Literal["prompt", "resume", "schedule", "system"], row["trigger_type"]
        ),
        status=cast(
            Literal["running", "paused", "completed", "failed"], row["status"]
        ),
        started_at=_ts_to_iso(row["started_at"]) or "",
        ended_at=_ts_to_iso(row.get("ended_at")),
    )


def _row_to_build_spec(row: dict[str, Any]) -> BuildSpecRecord:
    return BuildSpecRecord(
        build_spec_id=UUID(row["build_spec_id"]),
        thread_id=UUID(row["thread_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        planner_invocation_id=UUID(row["planner_invocation_id"]),
        spec_json=row.get("spec_json") or {},
        constraints_json=row.get("constraints_json") or {},
        success_criteria_json=row.get("success_criteria_json") or [],
        evaluation_targets_json=row.get("evaluation_targets_json") or [],
        status=cast(
            Literal["active", "superseded", "accepted"], row.get("status", "active")
        ),
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


class SupabaseRepository:
    """Postgres via Supabase REST — service role only (server-side orchestrator)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self._client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    def ensure_thread(self, record: ThreadRecord) -> None:
        row: dict[str, Any] = {
            "thread_id": str(record.thread_id),
            "thread_kind": record.thread_kind,
            "status": record.status,
            "identity_id": str(record.identity_id) if record.identity_id else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._client.table("thread").upsert(row, on_conflict="thread_id").execute()

    def update_thread_current_checkpoint(
        self, thread_id: UUID, checkpoint_id: UUID
    ) -> None:
        (
            self._client.table("thread")
            .update(
                {
                    "current_checkpoint_id": str(checkpoint_id),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("thread_id", str(thread_id))
            .execute()
        )

    def save_graph_run(self, record: GraphRunRecord) -> None:
        row: dict[str, Any] = {
            "graph_run_id": str(record.graph_run_id),
            "thread_id": str(record.thread_id),
            "trigger_type": record.trigger_type,
            "status": record.status,
            "started_at": record.started_at,
        }
        if record.ended_at is not None:
            row["ended_at"] = record.ended_at
        self._client.table("graph_run").upsert(row, on_conflict="graph_run_id").execute()

    def get_graph_run(self, graph_run_id: UUID) -> GraphRunRecord | None:
        res = (
            self._client.table("graph_run")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_graph_run(res.data[0])

    def update_graph_run_status(
        self,
        graph_run_id: UUID,
        status: Literal["running", "paused", "completed", "failed"],
        ended_at: str | None,
    ) -> None:
        patch: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if ended_at is not None:
            patch["ended_at"] = ended_at
        (
            self._client.table("graph_run")
            .update(patch)
            .eq("graph_run_id", str(graph_run_id))
            .execute()
        )

    def save_checkpoint(self, record: CheckpointRecord) -> None:
        row: dict[str, Any] = {
            "checkpoint_id": str(record.checkpoint_id),
            "thread_id": str(record.thread_id),
            "graph_run_id": str(record.graph_run_id),
            "checkpoint_kind": record.checkpoint_kind,
            "state_json": record.state_json,
            "created_at": record.created_at,
        }
        if record.context_compaction_json is not None:
            row["context_compaction_json"] = record.context_compaction_json
        self._client.table("checkpoint").insert(row).execute()

    def save_role_invocation(self, record: RoleInvocationRecord) -> None:
        row: dict[str, Any] = {
            "role_invocation_id": str(record.role_invocation_id),
            "graph_run_id": str(record.graph_run_id),
            "thread_id": str(record.thread_id),
            "role_type": record.role_type,
            "provider": record.provider,
            "provider_config_key": record.provider_config_key,
            "input_payload_json": record.input_payload_json,
            "status": record.status,
            "iteration_index": record.iteration_index,
            "started_at": record.started_at,
        }
        if record.output_payload_json is not None:
            row["output_payload_json"] = record.output_payload_json
        if record.ended_at is not None:
            row["ended_at"] = record.ended_at
        self._client.table("role_invocation").insert(row).execute()

    def save_build_spec(self, record: BuildSpecRecord) -> None:
        # normalized columns are product truth; raw_payload_json for KiloClaw trace (optional)
        row: dict[str, Any] = {
            "build_spec_id": str(record.build_spec_id),
            "thread_id": str(record.thread_id),
            "graph_run_id": str(record.graph_run_id),
            "planner_invocation_id": str(record.planner_invocation_id),
            "spec_json": record.spec_json,
            "constraints_json": record.constraints_json,
            "success_criteria_json": record.success_criteria_json,
            "evaluation_targets_json": record.evaluation_targets_json,
            "status": record.status,
            "created_at": record.created_at,
            "raw_payload_json": record.raw_payload_json,
        }
        self._client.table("build_spec").insert(row).execute()

    def get_build_spec(self, build_spec_id: UUID) -> BuildSpecRecord | None:
        res = (
            self._client.table("build_spec")
            .select("*")
            .eq("build_spec_id", str(build_spec_id))
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return _row_to_build_spec(res.data[0])

    def save_build_candidate(self, record: BuildCandidateRecord) -> None:
        # raw_payload_json optional — wire when KiloClaw returns live payloads
        row: dict[str, Any] = {
            "build_candidate_id": str(record.build_candidate_id),
            "thread_id": str(record.thread_id),
            "graph_run_id": str(record.graph_run_id),
            "generator_invocation_id": str(record.generator_invocation_id),
            "build_spec_id": str(record.build_spec_id),
            "candidate_kind": record.candidate_kind,
            "working_state_patch_json": record.working_state_patch_json,
            "artifact_refs_json": record.artifact_refs_json,
            "status": record.status,
            "created_at": record.created_at,
            "raw_payload_json": record.raw_payload_json,
        }
        if record.sandbox_ref is not None:
            row["sandbox_ref"] = record.sandbox_ref
        if record.preview_url is not None:
            row["preview_url"] = record.preview_url
        self._client.table("build_candidate").insert(row).execute()

    def save_evaluation_report(self, record: EvaluationReportRecord) -> None:
        # raw_payload_json optional — debug/trace only; logic uses issues/metrics/status
        row: dict[str, Any] = {
            "evaluation_report_id": str(record.evaluation_report_id),
            "thread_id": str(record.thread_id),
            "graph_run_id": str(record.graph_run_id),
            "evaluator_invocation_id": str(record.evaluator_invocation_id),
            "build_candidate_id": str(record.build_candidate_id),
            "status": record.status,
            "issues_json": record.issues_json,
            "metrics_json": record.metrics_json,
            "artifacts_json": record.artifacts_json,
            "created_at": record.created_at,
            "raw_payload_json": record.raw_payload_json,
        }
        if record.summary is not None:
            row["summary"] = record.summary
        self._client.table("evaluation_report").insert(row).execute()

    def attach_run_snapshot(self, graph_run_id: UUID, payload: dict[str, Any]) -> None:
        """Post-run graph state is stored via save_checkpoint(post_role); no separate table in v1."""

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None:
        res = (
            self._client.table("checkpoint")
            .select("state_json")
            .eq("graph_run_id", str(graph_run_id))
            .eq("checkpoint_kind", "post_role")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0].get("state_json")
