"""Supabase-backed repository using supabase-py (Phase 1 tables)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from supabase import Client, create_client

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    ACTIVE_GRAPH_RUN_STATUSES,
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunEventRecord,
    GraphRunRecord,
    GraphRunStatus,
    IdentityCrossRunMemoryRecord,
    IdentityProfileRecord,
    IdentitySourceRecord,
    PublicationSnapshotRecord,
    RoleInvocationRecord,
    StagingCheckpointRecord,
    StagingSnapshotRecord,
    ThreadRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.persistence.exceptions import (
    ActiveGraphRunPerThreadConflictError,
    WriteSnapshotNotSupportedError,
)
from kmbl_orchestrator.persistence.atomic_payloads import (
    publication_snapshot_to_rpc_dict,
    staging_checkpoint_to_rpc_dict,
    staging_snapshot_to_rpc_dict,
    working_staging_to_rpc_dict,
)
from kmbl_orchestrator.persistence.supabase_deserializers import (
    _is_retryable_supabase_transport,
    _row_to_build_candidate,
    _row_to_build_spec,
    _row_to_checkpoint,
    _row_to_evaluation_report,
    _row_to_graph_run,
    _row_to_graph_run_event,
    _row_to_identity_cross_run_memory,
    _row_to_identity_profile,
    _row_to_identity_source,
    _row_to_publication_snapshot,
    _row_to_role_invocation,
    _row_to_staging_checkpoint,
    _row_to_staging_snapshot,
    _row_to_thread,
    _row_to_working_staging,
)
from kmbl_orchestrator.persistence.supabase_repository_loops import (
    SupabaseRepositoryAutonomousLoopMixin,
)

_log = logging.getLogger(__name__)


def _exception_chain_str(exc: BaseException) -> str:
    """Concatenate str() for exc and its __cause__ chain (PostgREST nests APIError)."""
    parts: list[str] = []
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        parts.append(str(cur))
        cur = cur.__cause__
    return "\n".join(parts)


def _is_active_graph_run_per_thread_unique_violation(exc: BaseException) -> bool:
    """Postgres 23505 on partial unique index graph_run_one_active_per_thread."""
    s = _exception_chain_str(exc)
    if "23505" not in s:
        return False
    return "graph_run_one_active_per_thread" in s


def _is_duplicate_graph_run_event_pkey(exc: BaseException) -> bool:
    """
    True when Postgres reports duplicate key on graph_run_event primary key.

    Append-only events use a client-generated UUID; if the HTTP client got a transport
    error after PostgREST committed, a retry must not loop on sequence_index — the PK
    conflict means the row is already present (idempotent success).
    """
    s = _exception_chain_str(exc)
    if "23505" not in s:
        return False
    return "graph_run_event_pkey" in s or (
        "graph_run_event_id" in s and "already exists" in s
    )


class SupabaseRepository(SupabaseRepositoryAutonomousLoopMixin):
    """Postgres via Supabase REST — service role only (server-side orchestrator)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self._client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
        # Thread-level mutex (single worker). Cross-process staging serialization uses
        # pg_advisory_xact_lock inside Postgres RPC functions.
        self._thread_locks: dict[str, threading.Lock] = {}
        self._thread_lock_guard = threading.Lock()
        self._thread_lock_holders: dict[str, str] = {}

    def _run(
        self,
        op: str,
        table: str,
        fn: Callable[[], Any],
        **ctx: Any,
    ) -> Any:
        last: BaseException | None = None
        for attempt in range(3):
            try:
                return fn()
            except Exception as e:
                last = e
                if attempt < 2 and _is_retryable_supabase_transport(e):
                    _log.warning(
                        "SupabaseRepository.%s retry attempt=%s table=%s err=%s",
                        op,
                        attempt + 1,
                        table,
                        type(e).__name__,
                    )
                    time.sleep(0.35 * (attempt + 1))
                    continue
                _log.exception(
                    "SupabaseRepository.%s table=%s context=%s",
                    op,
                    table,
                    ctx,
                )
                raise RuntimeError(
                    f"SupabaseRepository.{op}({table}) failed: {type(e).__name__}: {e}"
                ) from e
        assert last is not None
        raise RuntimeError(
            f"SupabaseRepository.{op}({table}) failed after retries: {type(last).__name__}: {last}"
        ) from last

    def ensure_thread(self, record: ThreadRecord) -> None:
        row: dict[str, Any] = {
            "thread_id": str(record.thread_id),
            "thread_kind": record.thread_kind,
            "status": record.status,
            "identity_id": str(record.identity_id) if record.identity_id else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._run(
            "ensure_thread",
            "thread",
            lambda: self._client.table("thread")
            .upsert(row, on_conflict="thread_id")
            .execute(),
            thread_id=str(record.thread_id),
        )

    def get_thread(self, thread_id: UUID) -> ThreadRecord | None:
        res = self._run(
            "get_thread",
            "thread",
            lambda: self._client.table("thread")
            .select("*")
            .eq("thread_id", str(thread_id))
            .limit(1)
            .execute(),
            thread_id=str(thread_id),
        )
        if not res.data:
            return None
        return _row_to_thread(res.data[0])

    def update_thread_current_checkpoint(
        self, thread_id: UUID, checkpoint_id: UUID
    ) -> None:
        self._run(
            "update_thread_current_checkpoint",
            "thread",
            lambda: self._client.table("thread")
            .update(
                {
                    "current_checkpoint_id": str(checkpoint_id),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("thread_id", str(thread_id))
            .execute(),
            thread_id=str(thread_id),
            checkpoint_id=str(checkpoint_id),
        )

    def save_graph_run(self, record: GraphRunRecord) -> None:
        row: dict[str, Any] = {
            "graph_run_id": str(record.graph_run_id),
            "thread_id": str(record.thread_id),
            "trigger_type": record.trigger_type,
            "status": record.status,
            "started_at": record.started_at,
            "identity_id": str(record.identity_id) if record.identity_id else None,
        }
        if record.ended_at is not None:
            row["ended_at"] = record.ended_at
        if record.interrupt_requested_at is not None:
            row["interrupt_requested_at"] = record.interrupt_requested_at
        try:
            self._run(
                "save_graph_run",
                "graph_run",
                lambda: self._client.table("graph_run")
                .upsert(row, on_conflict="graph_run_id")
                .execute(),
                graph_run_id=str(record.graph_run_id),
            )
        except Exception as e:
            if _is_active_graph_run_per_thread_unique_violation(e):
                raise ActiveGraphRunPerThreadConflictError(
                    "graph_run_one_active_per_thread"
                ) from e
            raise

    def get_graph_run(self, graph_run_id: UUID) -> GraphRunRecord | None:
        res = self._run(
            "get_graph_run",
            "graph_run",
            lambda: self._client.table("graph_run")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_graph_run(res.data[0])

    def get_active_graph_run_for_thread(self, thread_id: UUID) -> GraphRunRecord | None:
        st_list = list(ACTIVE_GRAPH_RUN_STATUSES)
        res = self._run(
            "get_active_graph_run_for_thread",
            "graph_run",
            lambda: self._client.table("graph_run")
            .select("*")
            .eq("thread_id", str(thread_id))
            .in_("status", st_list)
            .order("started_at", desc=True)
            .limit(1)
            .execute(),
            thread_id=str(thread_id),
        )
        if not res.data:
            return None
        return _row_to_graph_run(res.data[0])

    def request_graph_run_interrupt(self, graph_run_id: UUID) -> GraphRunRecord:
        gr = self.get_graph_run(graph_run_id)
        if gr is None:
            raise KeyError(str(graph_run_id))
        if gr.status in ("completed", "failed", "interrupted"):
            raise ValueError(f"terminal_status:{gr.status}")
        if gr.status == "paused":
            raise ValueError("paused")
        if gr.status == "interrupt_requested" and gr.interrupt_requested_at is not None:
            return gr
        now = datetime.now(timezone.utc).isoformat()
        patch: dict[str, Any] = {
            "status": "interrupt_requested",
            "interrupt_requested_at": now,
            "updated_at": now,
        }
        self._run(
            "request_graph_run_interrupt",
            "graph_run",
            lambda: self._client.table("graph_run")
            .update(patch)
            .eq("graph_run_id", str(graph_run_id))
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        out = self.get_graph_run(graph_run_id)
        if out is None:
            raise KeyError(str(graph_run_id))
        return out

    def list_graph_runs(
        self,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        identity_id: UUID | None = None,
        thread_id: UUID | None = None,
        limit: int = 50,
    ) -> list[GraphRunRecord]:
        lim = max(1, min(limit, 500))

        def _apply_status_trigger(b: Any) -> Any:
            if status is not None:
                b = b.eq("status", status)
            if trigger_type is not None:
                b = b.eq("trigger_type", trigger_type)
            return b

        if thread_id is not None:
            tid_s = str(thread_id)

            def _q_thread_scoped() -> Any:
                return _apply_status_trigger(
                    self._client.table("graph_run").select("*").eq("thread_id", tid_s)
                ).order("started_at", desc=True).limit(lim).execute()

            res = self._run(
                "list_graph_runs",
                "graph_run",
                _q_thread_scoped,
                thread_id=tid_s,
            )
            if not res.data:
                return []
            return [_row_to_graph_run(r) for r in res.data]

        if identity_id is not None:
            id_s = str(identity_id)
            tr = self._run(
                "list_graph_runs_thread_filter",
                "thread",
                lambda: self._client.table("thread")
                .select("thread_id")
                .eq("identity_id", id_s)
                .execute(),
                identity_id=id_s,
            )
            tids = [r["thread_id"] for r in tr.data] if tr.data else []
            rows_by_key: dict[str, dict[str, Any]] = {}

            def _apply_filters(b: Any) -> Any:
                if status is not None:
                    b = b.eq("status", status)
                if trigger_type is not None:
                    b = b.eq("trigger_type", trigger_type)
                return b

            if tids:

                def _q_thread() -> Any:
                    return _apply_filters(
                        self._client.table("graph_run")
                        .select("*")
                        .in_("thread_id", tids)
                    ).order("started_at", desc=True).limit(lim).execute()

                res = self._run(
                    "list_graph_runs",
                    "graph_run",
                    _q_thread,
                    identity_id=id_s,
                )
                if res.data:
                    for r in res.data:
                        rows_by_key[str(r["graph_run_id"])] = r

            def _q_direct() -> Any:
                return _apply_filters(
                    self._client.table("graph_run").select("*").eq("identity_id", id_s)
                ).order("started_at", desc=True).limit(lim).execute()

            res_d = self._run(
                "list_graph_runs",
                "graph_run",
                _q_direct,
                identity_id=id_s,
            )
            if res_d.data:
                for r in res_d.data:
                    rows_by_key[str(r["graph_run_id"])] = r

            if not rows_by_key:
                return []
            merged = sorted(
                rows_by_key.values(),
                key=lambda x: str(x.get("started_at") or ""),
                reverse=True,
            )[:lim]
            return [_row_to_graph_run(r) for r in merged]
        else:

            def _q2() -> Any:
                b = self._client.table("graph_run").select("*")
                if status is not None:
                    b = b.eq("status", status)
                if trigger_type is not None:
                    b = b.eq("trigger_type", trigger_type)
                return b.order("started_at", desc=True).limit(lim).execute()

            res = self._run("list_graph_runs", "graph_run", _q2)
        if not res.data:
            return []
        return [_row_to_graph_run(r) for r in res.data]

    def aggregate_role_invocation_stats_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int | None]]:
        if not graph_run_ids:
            return {}
        id_strs = [str(g) for g in graph_run_ids]
        res = self._run(
            "aggregate_role_invocation_stats_for_graph_runs",
            "role_invocation",
            lambda: self._client.table("role_invocation")
            .select("graph_run_id, iteration_index")
            .in_("graph_run_id", id_strs)
            .execute(),
            count=len(id_strs),
        )
        acc: dict[str, list[int]] = {}
        if res.data:
            for row in res.data:
                gid = row.get("graph_run_id")
                if not gid:
                    continue
                it = row.get("iteration_index")
                ii = int(it) if isinstance(it, (int, float)) else 0
                acc.setdefault(str(gid), []).append(ii)
        out: dict[UUID, tuple[int, int | None]] = {}
        for g in graph_run_ids:
            ixs = acc.get(str(g), [])
            if not ixs:
                out[g] = (0, None)
            else:
                out[g] = (len(ixs), max(ixs))
        return out

    def latest_staging_snapshot_ids_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, UUID | None]:
        if not graph_run_ids:
            return {}
        id_strs = [str(g) for g in graph_run_ids]
        res = self._run(
            "latest_staging_snapshot_ids_for_graph_runs",
            "staging_snapshot",
            lambda: self._client.table("staging_snapshot")
            .select("staging_snapshot_id, graph_run_id, created_at")
            .in_("graph_run_id", id_strs)
            .execute(),
            count=len(id_strs),
        )
        out: dict[UUID, UUID | None] = {g: None for g in graph_run_ids}
        if not res.data:
            return out
        by_gid: dict[str, list[tuple[str, str]]] = {}
        for row in res.data:
            gid = row.get("graph_run_id")
            sid = row.get("staging_snapshot_id")
            cat = row.get("created_at")
            if not gid or not sid:
                continue
            by_gid.setdefault(str(gid), []).append((str(sid), str(cat or "")))
        for g in graph_run_ids:
            rows = by_gid.get(str(g), [])
            if not rows:
                continue
            rows.sort(key=lambda x: x[1], reverse=True)
            out[g] = UUID(rows[0][0])
        return out

    def graph_run_ids_with_interrupt_orchestrator_error(
        self, graph_run_ids: list[UUID]
    ) -> set[UUID]:
        if not graph_run_ids:
            return set()
        id_strs = [str(g) for g in graph_run_ids]
        res = self._run(
            "graph_run_ids_with_interrupt_orchestrator_error",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .select("graph_run_id, state_json, created_at")
            .in_("graph_run_id", id_strs)
            .eq("checkpoint_kind", "interrupt")
            .execute(),
            count=len(id_strs),
        )
        out: set[UUID] = set()
        if not res.data:
            return out
        by_gid: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for row in res.data:
            gid = row.get("graph_run_id")
            sj = row.get("state_json")
            cat = row.get("created_at")
            if not gid:
                continue
            if not isinstance(sj, dict):
                sj = {}
            by_gid.setdefault(str(gid), []).append((str(cat or ""), sj))
        for g in graph_run_ids:
            rows = by_gid.get(str(g), [])
            if not rows:
                continue
            rows.sort(key=lambda x: x[0])
            last = rows[-1][1]
            err = last.get("orchestrator_error")
            if isinstance(err, dict):
                out.add(g)
        return out

    def update_graph_run_status(
        self,
        graph_run_id: UUID,
        status: GraphRunStatus,
        ended_at: str | None,
        *,
        clear_interrupt_requested: bool | None = None,
    ) -> None:
        clear = (
            clear_interrupt_requested
            if clear_interrupt_requested is not None
            else status in ("completed", "failed", "interrupted")
        )
        patch: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if ended_at is not None:
            patch["ended_at"] = ended_at
        if clear:
            patch["interrupt_requested_at"] = None
        self._run(
            "update_graph_run_status",
            "graph_run",
            lambda: self._client.table("graph_run")
            .update(patch)
            .eq("graph_run_id", str(graph_run_id))
            .execute(),
            graph_run_id=str(graph_run_id),
            status=status,
        )

    def mark_graph_run_resuming(self, graph_run_id: UUID) -> None:
        patch: dict[str, Any] = {
            "status": "running",
            "ended_at": None,
            "interrupt_requested_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._run(
            "mark_graph_run_resuming",
            "graph_run",
            lambda: self._client.table("graph_run")
            .update(patch)
            .eq("graph_run_id", str(graph_run_id))
            .execute(),
            graph_run_id=str(graph_run_id),
        )

    def save_checkpoint(self, record: CheckpointRecord) -> None:
        """
        Persist a checkpoint row.

        Uses upsert with ``ignore_duplicates`` on ``checkpoint_id`` so a retry after an
        ambiguous transport disconnect (first insert committed, client saw failure) does
        not raise duplicate-key ``23505`` on ``checkpoint_pkey``.
        """
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
        self._run(
            "save_checkpoint",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .upsert(
                row,
                on_conflict="checkpoint_id",
                ignore_duplicates=True,
            )
            .execute(),
            checkpoint_id=str(record.checkpoint_id),
            graph_run_id=str(record.graph_run_id),
            kind=record.checkpoint_kind,
        )

    def save_role_invocation(self, record: RoleInvocationRecord) -> None:
        """
        Persist a role_invocation row.

        Uses upsert with ``ignore_duplicates`` on ``role_invocation_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``role_invocation_pkey``.
        """
        row: dict[str, Any] = {
            "role_invocation_id": str(record.role_invocation_id),
            "graph_run_id": str(record.graph_run_id),
            "thread_id": str(record.thread_id),
            "role_type": record.role_type,
            "provider": record.provider,
            "provider_config_key": record.provider_config_key,
            "input_payload_json": record.input_payload_json,
            "routing_metadata_json": record.routing_metadata_json or {},
            "status": record.status,
            "iteration_index": record.iteration_index,
            "started_at": record.started_at,
        }
        if record.output_payload_json is not None:
            row["output_payload_json"] = record.output_payload_json
        if record.ended_at is not None:
            row["ended_at"] = record.ended_at
        self._run(
            "save_role_invocation",
            "role_invocation",
            lambda: self._client.table("role_invocation")
            .upsert(
                row,
                on_conflict="role_invocation_id",
                ignore_duplicates=True,
            )
            .execute(),
            role_invocation_id=str(record.role_invocation_id),
            graph_run_id=str(record.graph_run_id),
            role_type=record.role_type,
        )

    def save_build_spec(self, record: BuildSpecRecord) -> None:
        """
        Persist a build_spec row.

        Uses upsert with ``ignore_duplicates`` on ``build_spec_id`` so a retry after an
        ambiguous transport disconnect (first insert committed, client saw failure) does
        not raise duplicate-key ``23505`` on ``build_spec_pkey``.
        """
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
        self._run(
            "save_build_spec",
            "build_spec",
            lambda: self._client.table("build_spec")
            .upsert(
                row,
                on_conflict="build_spec_id",
                ignore_duplicates=True,
            )
            .execute(),
            build_spec_id=str(record.build_spec_id),
            graph_run_id=str(record.graph_run_id),
        )

    def get_build_spec(self, build_spec_id: UUID) -> BuildSpecRecord | None:
        res = self._run(
            "get_build_spec",
            "build_spec",
            lambda: self._client.table("build_spec")
            .select("*")
            .eq("build_spec_id", str(build_spec_id))
            .limit(1)
            .execute(),
            build_spec_id=str(build_spec_id),
        )
        if not res.data:
            return None
        return _row_to_build_spec(res.data[0])

    def save_build_candidate(self, record: BuildCandidateRecord) -> None:
        """
        Persist a build_candidate row.

        Uses upsert with ``ignore_duplicates`` on ``build_candidate_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``build_candidate_pkey``.
        """
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
        self._run(
            "save_build_candidate",
            "build_candidate",
            lambda: self._client.table("build_candidate")
            .upsert(
                row,
                on_conflict="build_candidate_id",
                ignore_duplicates=True,
            )
            .execute(),
            build_candidate_id=str(record.build_candidate_id),
            graph_run_id=str(record.graph_run_id),
        )

    def get_build_candidate(self, build_candidate_id: UUID) -> BuildCandidateRecord | None:
        res = self._run(
            "get_build_candidate",
            "build_candidate",
            lambda: self._client.table("build_candidate")
            .select("*")
            .eq("build_candidate_id", str(build_candidate_id))
            .limit(1)
            .execute(),
            build_candidate_id=str(build_candidate_id),
        )
        if not res.data:
            return None
        return _row_to_build_candidate(res.data[0])

    def save_evaluation_report(self, record: EvaluationReportRecord) -> None:
        """
        Persist an evaluation_report row.

        Uses upsert with ``ignore_duplicates`` on ``evaluation_report_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``evaluation_report_pkey``.
        """
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
            "summary": record.summary,
            # Alignment scoring — written only when present so existing rows with NULL columns
            # are left untouched on upsert (ignore_duplicates=True handles retry safety).
            "alignment_score": record.alignment_score,
            "alignment_signals_json": record.alignment_signals_json or {},
        }
        self._run(
            "save_evaluation_report",
            "evaluation_report",
            lambda: self._client.table("evaluation_report")
            .upsert(
                row,
                on_conflict="evaluation_report_id",
                ignore_duplicates=True,
            )
            .execute(),
            evaluation_report_id=str(record.evaluation_report_id),
            graph_run_id=str(record.graph_run_id),
        )

    def get_evaluation_report(
        self, evaluation_report_id: UUID
    ) -> EvaluationReportRecord | None:
        res = self._run(
            "get_evaluation_report",
            "evaluation_report",
            lambda: self._client.table("evaluation_report")
            .select("*")
            .eq("evaluation_report_id", str(evaluation_report_id))
            .limit(1)
            .execute(),
            evaluation_report_id=str(evaluation_report_id),
        )
        if not res.data:
            return None
        return _row_to_evaluation_report(res.data[0])

    def attach_run_snapshot(self, graph_run_id: UUID, payload: dict[str, Any]) -> None:
        """Post-run graph state is stored via save_checkpoint(post_role); no separate table in v1."""

    def get_run_snapshot(self, graph_run_id: UUID) -> dict[str, Any] | None:
        res = self._run(
            "get_run_snapshot",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .select("state_json")
            .eq("graph_run_id", str(graph_run_id))
            .eq("checkpoint_kind", "post_role")
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return res.data[0].get("state_json")

    def get_run_snapshots_for_graph_runs(
        self, graph_run_ids: list[UUID]
    ) -> dict[UUID, dict[str, Any] | None]:
        """One round-trip: latest ``post_role`` ``state_json`` per graph_run (list read model)."""
        if not graph_run_ids:
            return {}
        id_strs = [str(g) for g in graph_run_ids]
        res = self._run(
            "get_run_snapshots_for_graph_runs",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .select("graph_run_id, state_json, created_at")
            .in_("graph_run_id", id_strs)
            .eq("checkpoint_kind", "post_role")
            .execute(),
            count=len(id_strs),
        )
        out: dict[UUID, dict[str, Any] | None] = {g: None for g in graph_run_ids}
        if not res.data:
            return out
        by_gid: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for row in res.data:
            gid = row.get("graph_run_id")
            sj = row.get("state_json")
            cat = row.get("created_at")
            if not gid:
                continue
            if not isinstance(sj, dict):
                sj = {}
            by_gid.setdefault(str(gid), []).append((str(cat or ""), sj))
        for g in graph_run_ids:
            rows = by_gid.get(str(g), [])
            if not rows:
                continue
            rows.sort(key=lambda x: x[0])
            out[g] = rows[-1][1]
        return out

    def get_latest_failed_role_invocation_for_graph_run(
        self, graph_run_id: UUID
    ) -> RoleInvocationRecord | None:
        res = self._run(
            "get_latest_failed_role_invocation_for_graph_run",
            "role_invocation",
            lambda: self._client.table("role_invocation")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .eq("status", "failed")
            .order("started_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_role_invocation(res.data[0])

    def get_latest_interrupt_orchestrator_error(
        self, graph_run_id: UUID
    ) -> dict[str, Any] | None:
        res = self._run(
            "get_latest_interrupt_orchestrator_error",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .select("state_json")
            .eq("graph_run_id", str(graph_run_id))
            .eq("checkpoint_kind", "interrupt")
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        sj = res.data[0].get("state_json")
        if not isinstance(sj, dict):
            return None
        err = sj.get("orchestrator_error")
        return err if isinstance(err, dict) else None

    def get_latest_build_spec_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildSpecRecord | None:
        res = self._run(
            "get_latest_build_spec_for_graph_run",
            "build_spec",
            lambda: self._client.table("build_spec")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_build_spec(res.data[0])

    def get_latest_build_candidate_for_graph_run(
        self, graph_run_id: UUID
    ) -> BuildCandidateRecord | None:
        res = self._run(
            "get_latest_build_candidate_for_graph_run",
            "build_candidate",
            lambda: self._client.table("build_candidate")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_build_candidate(res.data[0])

    def get_latest_evaluation_report_for_graph_run(
        self, graph_run_id: UUID
    ) -> EvaluationReportRecord | None:
        res = self._run(
            "get_latest_evaluation_report_for_graph_run",
            "evaluation_report",
            lambda: self._client.table("evaluation_report")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_evaluation_report(res.data[0])

    def list_evaluation_reports_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 50
    ) -> list[EvaluationReportRecord]:
        res = self._run(
            "list_evaluation_reports_for_graph_run",
            "evaluation_report",
            lambda: self._client.table("evaluation_report")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=False)
            .limit(limit)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_evaluation_report(row) for row in res.data]

    def _next_graph_run_event_sequence_index(self, graph_run_id: UUID) -> int | None:
        """
        Next ``sequence_index`` for ``graph_run_event`` when the table has that column
        and a unique (graph_run_id, sequence_index) constraint. Returns None if the column
        is missing (older schemas).
        """
        try:
            res = self._run(
                "_next_graph_run_event_sequence_index",
                "graph_run_event",
                lambda: self._client.table("graph_run_event")
                .select("sequence_index")
                .eq("graph_run_id", str(graph_run_id))
                .order("sequence_index", desc=True)
                .limit(1)
                .execute(),
                graph_run_id=str(graph_run_id),
            )
        except RuntimeError:
            return None
        if not res.data:
            return 0
        try:
            return int(res.data[0]["sequence_index"]) + 1
        except (KeyError, TypeError, ValueError):
            return None

    def save_graph_run_event(self, record: GraphRunEventRecord) -> None:
        """
        Persist an append-only timeline row.

        Supplies ``sequence_index`` when the DB enforces uniqueness on
        (graph_run_id, sequence_index); retries with an incremented index on race (23505).
        If ``sequence_index`` is not available, duplicate PK/unique errors are logged and ignored.
        """
        row: dict[str, Any] = {
            "graph_run_event_id": str(record.graph_run_event_id),
            "graph_run_id": str(record.graph_run_id),
            "event_type": record.event_type,
            "payload_json": record.payload_json,
            "created_at": record.created_at,
        }
        if record.thread_id is not None:
            row["thread_id"] = str(record.thread_id)

        seq = self._next_graph_run_event_sequence_index(record.graph_run_id)
        if seq is not None:
            row["sequence_index"] = seq

        max_bumps = 32
        for bump in range(max_bumps):
            try:
                self._run(
                    "save_graph_run_event",
                    "graph_run_event",
                    lambda r=row: self._client.table("graph_run_event")
                    .insert(r)
                    .execute(),
                    graph_run_event_id=str(record.graph_run_event_id),
                    graph_run_id=str(record.graph_run_id),
                )
                return
            except RuntimeError as e:
                if "23505" not in _exception_chain_str(e):
                    raise
                if _is_duplicate_graph_run_event_pkey(e):
                    _log.info(
                        "save_graph_run_event duplicate PK — treating as success "
                        "(likely prior insert committed after transport error) "
                        "graph_run_event_id=%s",
                        record.graph_run_event_id,
                    )
                    return
                if seq is None:
                    _log.warning(
                        "save_graph_run_event duplicate key ignored graph_run_event_id=%s",
                        record.graph_run_event_id,
                    )
                    return
                row["sequence_index"] = int(row.get("sequence_index", 0)) + 1
                if bump == max_bumps - 1:
                    _log.warning(
                        "save_graph_run_event gave up after %s sequence bumps graph_run_event_id=%s",
                        max_bumps,
                        record.graph_run_event_id,
                    )
                    return

    def list_graph_run_events(
        self, graph_run_id: UUID, *, limit: int = 200
    ) -> list[GraphRunEventRecord]:
        res = self._run(
            "list_graph_run_events",
            "graph_run_event",
            lambda: self._client.table("graph_run_event")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=False)
            .limit(limit)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_graph_run_event(r) for r in res.data]

    def list_role_invocations_for_graph_run(
        self, graph_run_id: UUID
    ) -> list[RoleInvocationRecord]:
        res = self._run(
            "list_role_invocations_for_graph_run",
            "role_invocation",
            lambda: self._client.table("role_invocation")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("started_at", desc=False)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_role_invocation(r) for r in res.data]

    def list_staging_snapshots_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[StagingSnapshotRecord]:
        lim = max(1, min(limit, 500))
        res = self._run(
            "list_staging_snapshots_for_graph_run",
            "staging_snapshot",
            lambda: self._client.table("staging_snapshot")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=True)
            .limit(lim)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_staging_snapshot(r) for r in res.data]

    def list_publications_for_graph_run(
        self, graph_run_id: UUID, *, limit: int = 20
    ) -> list[PublicationSnapshotRecord]:
        lim = max(1, min(limit, 500))
        res = self._run(
            "list_publications_for_graph_run",
            "publication_snapshot",
            lambda: self._client.table("publication_snapshot")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("published_at", desc=True)
            .limit(lim)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_publication_snapshot(r) for r in res.data]

    def get_latest_checkpoint_for_graph_run(
        self, graph_run_id: UUID
    ) -> CheckpointRecord | None:
        res = self._run(
            "get_latest_checkpoint_for_graph_run",
            "checkpoint",
            lambda: self._client.table("checkpoint")
            .select("*")
            .eq("graph_run_id", str(graph_run_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return None
        return _row_to_checkpoint(res.data[0])

    def list_stale_running_graph_run_ids(self, older_than_seconds: int) -> list[UUID]:
        if older_than_seconds <= 0:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
        res = self._run(
            "list_stale_running_graph_run_ids",
            "graph_run",
            lambda: self._client.table("graph_run")
            .select("graph_run_id")
            .in_("status", ["running", "starting", "interrupt_requested"])
            .lt("started_at", cutoff)
            .execute(),
            cutoff=cutoff,
        )
        if not res.data:
            return []
        return [UUID(r["graph_run_id"]) for r in res.data]

    def save_staging_snapshot(self, record: StagingSnapshotRecord) -> None:
        """
        Persist a staging_snapshot row.

        Uses upsert with ``ignore_duplicates`` on ``staging_snapshot_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``staging_snapshot_pkey``.
        """
        row: dict[str, Any] = {
            "staging_snapshot_id": str(record.staging_snapshot_id),
            "thread_id": str(record.thread_id),
            "build_candidate_id": str(record.build_candidate_id),
            "snapshot_payload_json": record.snapshot_payload_json,
            "status": record.status,
            "created_at": record.created_at,
        }
        if record.graph_run_id is not None:
            row["graph_run_id"] = str(record.graph_run_id)
        if record.identity_id is not None:
            row["identity_id"] = str(record.identity_id)
        if record.prior_staging_snapshot_id is not None:
            row["prior_staging_snapshot_id"] = str(record.prior_staging_snapshot_id)
        if record.preview_url is not None:
            row["preview_url"] = record.preview_url
        if record.approved_by is not None:
            row["approved_by"] = record.approved_by
        if record.approved_at is not None:
            row["approved_at"] = record.approved_at
        if record.rejected_by is not None:
            row["rejected_by"] = record.rejected_by
        if record.rejected_at is not None:
            row["rejected_at"] = record.rejected_at
        if record.rejection_reason is not None:
            row["rejection_reason"] = record.rejection_reason
        row["marked_for_review"] = record.marked_for_review
        if record.mark_reason is not None:
            row["mark_reason"] = record.mark_reason
        row["review_tags"] = list(record.review_tags)
        self._run(
            "save_staging_snapshot",
            "staging_snapshot",
            lambda: self._client.table("staging_snapshot")
            .upsert(
                row,
                on_conflict="staging_snapshot_id",
                ignore_duplicates=True,
            )
            .execute(),
            staging_snapshot_id=str(record.staging_snapshot_id),
            thread_id=str(record.thread_id),
        )

    def get_staging_snapshot(
        self, staging_snapshot_id: UUID
    ) -> StagingSnapshotRecord | None:
        res = self._run(
            "get_staging_snapshot",
            "staging_snapshot",
            lambda: self._client.table("staging_snapshot")
            .select("*")
            .eq("staging_snapshot_id", str(staging_snapshot_id))
            .limit(1)
            .execute(),
            staging_snapshot_id=str(staging_snapshot_id),
        )
        if not res.data:
            return None
        return _row_to_staging_snapshot(res.data[0])

    def list_staging_snapshots(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
        identity_id: UUID | None = None,
    ) -> list[StagingSnapshotRecord]:
        lim = max(1, min(limit, 500))

        def _query() -> Any:
            q = self._client.table("staging_snapshot").select("*")
            if status is not None:
                q = q.eq("status", status)
            if identity_id is not None:
                q = q.eq("identity_id", str(identity_id))
            return q.order("created_at", desc=True).limit(lim).execute()

        res = self._run(
            "list_staging_snapshots",
            "staging_snapshot",
            _query,
            limit=lim,
            status=status,
            identity_id=str(identity_id) if identity_id else None,
        )
        if not res.data:
            return []
        return [_row_to_staging_snapshot(r) for r in res.data]

    def list_staging_snapshots_for_thread(
        self,
        thread_id: UUID,
        *,
        limit: int = 10,
    ) -> list[StagingSnapshotRecord]:
        lim = max(1, min(limit, 100))

        def _query() -> Any:
            return (
                self._client.table("staging_snapshot")
                .select("*")
                .eq("thread_id", str(thread_id))
                .order("created_at", desc=True)
                .limit(lim)
                .execute()
            )

        res = self._run(
            "list_staging_snapshots_for_thread",
            "staging_snapshot",
            _query,
            thread_id=str(thread_id),
            limit=lim,
        )
        if not res.data:
            return []
        return [_row_to_staging_snapshot(r) for r in res.data]

    def update_staging_snapshot_status(
        self,
        staging_snapshot_id: UUID,
        status: str,
        *,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
    ) -> StagingSnapshotRecord | None:
        from kmbl_orchestrator.staging.status_transition import build_staging_status_audit_patch

        patch = build_staging_status_audit_patch(
            status,
            approved_by=approved_by,
            rejected_by=rejected_by,
            rejection_reason=rejection_reason,
        )

        def _query() -> Any:
            # postgrest-py: `update()` returns SyncFilterRequestBuilder — chain `.eq().execute()`;
            # `.select()` exists on select builders only. Representation is returned by default.
            return (
                self._client.table("staging_snapshot")
                .update(patch)
                .eq("staging_snapshot_id", str(staging_snapshot_id))
                .execute()
            )

        res = self._run(
            "update_staging_snapshot_status",
            "staging_snapshot",
            _query,
            staging_snapshot_id=str(staging_snapshot_id),
            status=status,
        )
        if not res.data:
            return None
        return _row_to_staging_snapshot(res.data[0])

    def rate_staging_snapshot(
        self,
        staging_snapshot_id: UUID,
        rating: int,
        feedback: str | None = None,
    ) -> StagingSnapshotRecord | None:
        from datetime import datetime, timezone

        patch: dict[str, Any] = {
            "user_rating": rating,
            "rated_at": datetime.now(timezone.utc).isoformat(),
        }
        if feedback is not None:
            patch["user_feedback"] = feedback

        def _query() -> Any:
            return (
                self._client.table("staging_snapshot")
                .update(patch)
                .eq("staging_snapshot_id", str(staging_snapshot_id))
                .execute()
            )

        res = self._run(
            "rate_staging_snapshot",
            "staging_snapshot",
            _query,
            staging_snapshot_id=str(staging_snapshot_id),
            rating=rating,
        )
        if not res.data:
            return None
        return _row_to_staging_snapshot(res.data[0])

    def save_publication_snapshot(self, record: PublicationSnapshotRecord) -> None:
        """
        Persist a publication_snapshot row.

        Uses upsert with ``ignore_duplicates`` on ``publication_snapshot_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``publication_snapshot_pkey``.
        """
        row: dict[str, Any] = {
            "publication_snapshot_id": str(record.publication_snapshot_id),
            "source_staging_snapshot_id": str(record.source_staging_snapshot_id),
            "payload_json": record.payload_json,
            "visibility": record.visibility,
            "published_at": record.published_at,
        }
        if record.thread_id is not None:
            row["thread_id"] = str(record.thread_id)
        if record.graph_run_id is not None:
            row["graph_run_id"] = str(record.graph_run_id)
        if record.identity_id is not None:
            row["identity_id"] = str(record.identity_id)
        if record.published_by is not None:
            row["published_by"] = record.published_by
        if record.parent_publication_snapshot_id is not None:
            row["parent_publication_snapshot_id"] = str(
                record.parent_publication_snapshot_id
            )
        self._run(
            "save_publication_snapshot",
            "publication_snapshot",
            lambda: self._client.table("publication_snapshot")
            .upsert(
                row,
                on_conflict="publication_snapshot_id",
                ignore_duplicates=True,
            )
            .execute(),
            publication_snapshot_id=str(record.publication_snapshot_id),
        )

    def get_publication_snapshot(
        self, publication_snapshot_id: UUID
    ) -> PublicationSnapshotRecord | None:
        res = self._run(
            "get_publication_snapshot",
            "publication_snapshot",
            lambda: self._client.table("publication_snapshot")
            .select("*")
            .eq("publication_snapshot_id", str(publication_snapshot_id))
            .limit(1)
            .execute(),
            publication_snapshot_id=str(publication_snapshot_id),
        )
        if not res.data:
            return None
        return _row_to_publication_snapshot(res.data[0])

    def list_publication_snapshots(
        self,
        *,
        limit: int = 20,
        identity_id: UUID | None = None,
        visibility: str | None = None,
    ) -> list[PublicationSnapshotRecord]:
        lim = max(1, min(limit, 500))

        def _query() -> Any:
            q = self._client.table("publication_snapshot").select("*")
            if identity_id is not None:
                q = q.eq("identity_id", str(identity_id))
            if visibility is not None:
                q = q.eq("visibility", visibility)
            return q.order("published_at", desc=True).limit(lim).execute()

        res = self._run(
            "list_publication_snapshots",
            "publication_snapshot",
            _query,
            limit=lim,
            identity_id=str(identity_id) if identity_id else None,
            visibility=visibility,
        )
        if not res.data:
            return []
        return [_row_to_publication_snapshot(r) for r in res.data]

    def list_publications_for_staging(
        self, staging_snapshot_id: UUID
    ) -> list[PublicationSnapshotRecord]:
        """All publication rows for this staging id, newest ``published_at`` first."""

        def _query() -> Any:
            return (
                self._client.table("publication_snapshot")
                .select("*")
                .eq("source_staging_snapshot_id", str(staging_snapshot_id))
                .order("published_at", desc=True)
                .execute()
            )

        res = self._run(
            "list_publications_for_staging",
            "publication_snapshot",
            _query,
            staging_snapshot_id=str(staging_snapshot_id),
        )
        if not res.data:
            return []
        return [_row_to_publication_snapshot(r) for r in res.data]

    def publication_counts_for_staging_snapshot_ids(
        self, staging_snapshot_ids: list[UUID]
    ) -> dict[UUID, int]:
        if not staging_snapshot_ids:
            return {}
        id_strs = [str(x) for x in staging_snapshot_ids]
        res = self._run(
            "publication_counts_for_staging_snapshot_ids",
            "publication_snapshot",
            lambda: self._client.table("publication_snapshot")
            .select("source_staging_snapshot_id")
            .in_("source_staging_snapshot_id", id_strs)
            .execute(),
            count=len(id_strs),
        )
        if not res.data:
            return {s: 0 for s in staging_snapshot_ids}
        counts: dict[str, int] = {}
        for row in res.data:
            sid = row.get("source_staging_snapshot_id")
            if sid:
                ks = str(sid)
                counts[ks] = counts.get(ks, 0) + 1
        return {s: counts.get(str(s), 0) for s in staging_snapshot_ids}

    def get_latest_publication_snapshot(
        self, *, identity_id: UUID | None = None
    ) -> PublicationSnapshotRecord | None:
        rows = self.list_publication_snapshots(limit=1, identity_id=identity_id)
        return rows[0] if rows else None

    def create_identity_source(self, record: IdentitySourceRecord) -> None:
        """
        Persist an identity_source row.

        Uses upsert with ``ignore_duplicates`` on ``identity_source_id`` so a retry after an
        ambiguous transport disconnect does not raise duplicate-key ``23505`` on
        ``identity_source_pkey``.
        """
        row: dict[str, Any] = {
            "identity_source_id": str(record.identity_source_id),
            "identity_id": str(record.identity_id),
            "source_type": record.source_type,
            "source_uri": record.source_uri,
            "raw_text": record.raw_text,
            "metadata_json": record.metadata_json,
            "created_at": record.created_at,
        }
        self._run(
            "create_identity_source",
            "identity_source",
            lambda: self._client.table("identity_source")
            .upsert(
                row,
                on_conflict="identity_source_id",
                ignore_duplicates=True,
            )
            .execute(),
            identity_source_id=str(record.identity_source_id),
        )

    def list_identity_sources(self, identity_id: UUID) -> list[IdentitySourceRecord]:
        res = self._run(
            "list_identity_sources",
            "identity_source",
            lambda: self._client.table("identity_source")
            .select("*")
            .eq("identity_id", str(identity_id))
            .order("created_at", desc=True)
            .execute(),
            identity_id=str(identity_id),
        )
        if not res.data:
            return []
        return [_row_to_identity_source(r) for r in res.data]

    def get_identity_profile(self, identity_id: UUID) -> IdentityProfileRecord | None:
        res = self._run(
            "get_identity_profile",
            "identity_profile",
            lambda: self._client.table("identity_profile")
            .select("*")
            .eq("identity_id", str(identity_id))
            .limit(1)
            .execute(),
            identity_id=str(identity_id),
        )
        if not res.data:
            return None
        return _row_to_identity_profile(res.data[0])

    def upsert_identity_profile(self, record: IdentityProfileRecord) -> None:
        row: dict[str, Any] = {
            "identity_id": str(record.identity_id),
            "profile_summary": record.profile_summary,
            "facets_json": record.facets_json,
            "open_questions_json": record.open_questions_json,
            "updated_at": record.updated_at,
        }
        self._run(
            "upsert_identity_profile",
            "identity_profile",
            lambda: self._client.table("identity_profile")
            .upsert(row, on_conflict="identity_id")
            .execute(),
            identity_id=str(record.identity_id),
        )

    def get_identity_cross_run_memory(
        self,
        identity_id: UUID,
        category: str,
        memory_key: str,
    ) -> IdentityCrossRunMemoryRecord | None:
        res = self._run(
            "get_identity_cross_run_memory",
            "identity_cross_run_memory",
            lambda: self._client.table("identity_cross_run_memory")
            .select("*")
            .eq("identity_id", str(identity_id))
            .eq("category", category)
            .eq("memory_key", memory_key)
            .limit(1)
            .execute(),
            identity_id=str(identity_id),
        )
        if not res.data:
            return None
        return _row_to_identity_cross_run_memory(res.data[0])

    def list_identity_cross_run_memory(
        self,
        identity_id: UUID,
        *,
        category: str | None = None,
        limit: int = 200,
    ) -> list[IdentityCrossRunMemoryRecord]:
        q = self._client.table("identity_cross_run_memory").select("*").eq(
            "identity_id", str(identity_id)
        )
        if category is not None:
            q = q.eq("category", category)
        res = self._run(
            "list_identity_cross_run_memory",
            "identity_cross_run_memory",
            lambda: q.order("updated_at", desc=True).limit(limit).execute(),
            identity_id=str(identity_id),
        )
        if not res.data:
            return []
        return [_row_to_identity_cross_run_memory(r) for r in res.data]

    def list_identity_cross_run_memory_by_source_run(
        self, graph_run_id: UUID
    ) -> list[IdentityCrossRunMemoryRecord]:
        res = self._run(
            "list_identity_cross_run_memory_by_source_run",
            "identity_cross_run_memory",
            lambda: self._client.table("identity_cross_run_memory")
            .select("*")
            .eq("source_graph_run_id", str(graph_run_id))
            .order("updated_at", desc=True)
            .execute(),
            graph_run_id=str(graph_run_id),
        )
        if not res.data:
            return []
        return [_row_to_identity_cross_run_memory(r) for r in res.data]

    def upsert_identity_cross_run_memory(self, record: IdentityCrossRunMemoryRecord) -> None:
        existing = self.get_identity_cross_run_memory(
            record.identity_id, record.category, record.memory_key
        )
        row: dict[str, Any] = {
            "identity_cross_run_memory_id": str(record.identity_cross_run_memory_id),
            "identity_id": str(record.identity_id),
            "category": record.category,
            "memory_key": record.memory_key,
            "payload_json": record.payload_json,
            "strength": record.strength,
            "provenance": record.provenance,
            "updated_at": record.updated_at,
        }
        if record.source_graph_run_id is not None:
            row["source_graph_run_id"] = str(record.source_graph_run_id)
        else:
            row["source_graph_run_id"] = None
        if record.operator_signal is not None:
            row["operator_signal"] = record.operator_signal
        else:
            row["operator_signal"] = None
        if existing is None:
            row["created_at"] = record.created_at
            self._run(
                "insert_identity_cross_run_memory",
                "identity_cross_run_memory",
                lambda: self._client.table("identity_cross_run_memory")
                .insert(row)
                .execute(),
                identity_id=str(record.identity_id),
            )
        else:
            row["identity_cross_run_memory_id"] = str(existing.identity_cross_run_memory_id)
            row["created_at"] = existing.created_at
            self._run(
                "update_identity_cross_run_memory",
                "identity_cross_run_memory",
                lambda: self._client.table("identity_cross_run_memory")
                .update(row)
                .eq("identity_cross_run_memory_id", str(existing.identity_cross_run_memory_id))
                .execute(),
                identity_id=str(record.identity_id),
            )

    # ---- Working staging ----

    def _call_rpc(self, rpc_name: str, params: dict[str, Any]) -> None:
        """Invoke a Supabase/PostgREST ``rpc`` (Postgres function in a single transaction)."""

        def _fn() -> Any:
            return self._client.rpc(rpc_name, params).execute()

        self._run(f"rpc:{rpc_name}", "rpc", _fn, rpc=rpc_name)

    def atomic_persist_staging_node_writes(
        self,
        *,
        checkpoints: list[StagingCheckpointRecord],
        working_staging: WorkingStagingRecord,
        staging_snapshot: StagingSnapshotRecord | None,
    ) -> None:
        cp_json = [staging_checkpoint_to_rpc_dict(c) for c in checkpoints]
        ws_json = working_staging_to_rpc_dict(working_staging)
        snap_json: Any
        if staging_snapshot is None:
            snap_json = None
        else:
            snap_json = staging_snapshot_to_rpc_dict(staging_snapshot)
        self._call_rpc(
            "kmbl_atomic_staging_node_persist",
            {
                "p_thread_id": str(working_staging.thread_id),
                "p_checkpoints": cp_json,
                "p_working_staging": ws_json,
                "p_staging_snapshot": snap_json,
            },
        )

    def atomic_commit_working_staging_approval(
        self,
        *,
        checkpoint: StagingCheckpointRecord,
        publication: PublicationSnapshotRecord,
        working_staging: WorkingStagingRecord,
    ) -> None:
        self._call_rpc(
            "kmbl_atomic_working_staging_approve",
            {
                "p_thread_id": str(working_staging.thread_id),
                "p_checkpoint": staging_checkpoint_to_rpc_dict(checkpoint),
                "p_publication": publication_snapshot_to_rpc_dict(publication),
                "p_working_staging": working_staging_to_rpc_dict(working_staging),
            },
        )

    def get_working_staging_for_thread(
        self, thread_id: UUID
    ) -> WorkingStagingRecord | None:
        res = self._run(
            "get_working_staging_for_thread",
            "working_staging",
            lambda: self._client.table("working_staging")
            .select("*")
            .eq("thread_id", str(thread_id))
            .limit(1)
            .execute(),
            thread_id=str(thread_id),
        )
        if not res.data:
            return None
        return _row_to_working_staging(res.data[0])

    def save_working_staging(self, record: WorkingStagingRecord) -> None:
        """Upsert working_staging under a thread-scoped DB advisory lock (single RPC transaction)."""
        self._call_rpc(
            "kmbl_atomic_upsert_working_staging",
            {
                "p_thread_id": str(record.thread_id),
                "p_working_staging": working_staging_to_rpc_dict(record),
            },
        )

    def save_staging_checkpoint(self, record: StagingCheckpointRecord) -> None:
        row: dict[str, Any] = {
            "staging_checkpoint_id": str(record.staging_checkpoint_id),
            "working_staging_id": str(record.working_staging_id),
            "thread_id": str(record.thread_id),
            "payload_snapshot_json": record.payload_snapshot_json,
            "revision_at_checkpoint": record.revision_at_checkpoint,
            "trigger": record.trigger,
            "created_at": record.created_at,
        }
        if record.source_graph_run_id is not None:
            row["source_graph_run_id"] = str(record.source_graph_run_id)
        if record.reason_category is not None:
            row["reason_category"] = record.reason_category
        if record.reason_explanation is not None:
            row["reason_explanation"] = record.reason_explanation
        self._run(
            "save_staging_checkpoint",
            "staging_checkpoint",
            lambda: self._client.table("staging_checkpoint")
            .upsert(
                row,
                on_conflict="staging_checkpoint_id",
                ignore_duplicates=True,
            )
            .execute(),
            staging_checkpoint_id=str(record.staging_checkpoint_id),
        )

    def get_staging_checkpoint(
        self, staging_checkpoint_id: UUID
    ) -> StagingCheckpointRecord | None:
        res = self._run(
            "get_staging_checkpoint",
            "staging_checkpoint",
            lambda: self._client.table("staging_checkpoint")
            .select("*")
            .eq("staging_checkpoint_id", str(staging_checkpoint_id))
            .limit(1)
            .execute(),
            staging_checkpoint_id=str(staging_checkpoint_id),
        )
        if not res.data:
            return None
        return _row_to_staging_checkpoint(res.data[0])

    def list_staging_checkpoints(
        self, working_staging_id: UUID, *, limit: int = 50
    ) -> list[StagingCheckpointRecord]:
        lim = max(1, min(limit, 500))
        res = self._run(
            "list_staging_checkpoints",
            "staging_checkpoint",
            lambda: self._client.table("staging_checkpoint")
            .select("*")
            .eq("working_staging_id", str(working_staging_id))
            .order("created_at", desc=True)
            .limit(lim)
            .execute(),
            working_staging_id=str(working_staging_id),
        )
        if not res.data:
            return []
        return [_row_to_staging_checkpoint(r) for r in res.data]

    # --- Thread locking (process-local) & explicit RPC atomicity ---

    @contextmanager
    def in_memory_write_snapshot(self) -> Iterator[None]:
        """**Unsupported.** PostgREST cannot roll back a sequence of repository calls.

        Callers must use ``atomic_persist_staging_node_writes``,
        ``atomic_commit_working_staging_approval``, or ``save_working_staging`` (RPC)
        for thread-scoped atomic writes.
        """
        raise WriteSnapshotNotSupportedError()
        yield  # pragma: no cover

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


