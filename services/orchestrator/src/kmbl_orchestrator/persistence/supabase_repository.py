"""Supabase-backed repository using supabase-py (Phase 1 tables)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast
from uuid import UUID

import httpx
import httpcore
from supabase import Client, create_client

from kmbl_orchestrator.config import Settings
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

_log = logging.getLogger(__name__)


def _is_retryable_supabase_transport(exc: BaseException) -> bool:
    """Best-effort: retry idempotent reads/writes on transient client transport failures.

    PostgREST over HTTP/2 can raise RemoteProtocolError (e.g. ``Server disconnected``);
    map both httpx and httpcore variants so ``_run``'s retry loop can recover.
    """
    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpcore.RemoteProtocolError,
        ),
    ):
        return True
    return False


def _ts_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_graph_run(row: dict[str, Any]) -> GraphRunRecord:
    iid = row.get("identity_id")
    return GraphRunRecord(
        graph_run_id=UUID(row["graph_run_id"]),
        thread_id=UUID(row["thread_id"]),
        identity_id=UUID(iid) if iid else None,
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
    raw = row.get("raw_payload_json")
    return BuildSpecRecord(
        build_spec_id=UUID(row["build_spec_id"]),
        thread_id=UUID(row["thread_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        planner_invocation_id=UUID(row["planner_invocation_id"]),
        spec_json=row.get("spec_json") or {},
        constraints_json=row.get("constraints_json") or {},
        success_criteria_json=row.get("success_criteria_json") or [],
        evaluation_targets_json=row.get("evaluation_targets_json") or [],
        raw_payload_json=raw if isinstance(raw, dict) else None,
        status=cast(
            Literal["active", "superseded", "accepted"], row.get("status", "active")
        ),
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_build_candidate(row: dict[str, Any]) -> BuildCandidateRecord:
    return BuildCandidateRecord(
        build_candidate_id=UUID(row["build_candidate_id"]),
        thread_id=UUID(row["thread_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        generator_invocation_id=UUID(row["generator_invocation_id"]),
        build_spec_id=UUID(row["build_spec_id"]),
        candidate_kind=cast(
            Literal["habitat", "content", "full_app"], row["candidate_kind"]
        ),
        working_state_patch_json=row.get("working_state_patch_json") or {},
        artifact_refs_json=row.get("artifact_refs_json") or [],
        raw_payload_json=row.get("raw_payload_json")
        if isinstance(row.get("raw_payload_json"), dict)
        else None,
        sandbox_ref=row.get("sandbox_ref"),
        preview_url=row.get("preview_url"),
        status=cast(
            Literal[
                "generated",
                "applied",
                "under_review",
                "superseded",
                "accepted",
            ],
            row.get("status", "generated"),
        ),
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_evaluation_report(row: dict[str, Any]) -> EvaluationReportRecord:
    sm = row.get("summary")
    summary = "" if sm is None else str(sm)
    return EvaluationReportRecord(
        evaluation_report_id=UUID(row["evaluation_report_id"]),
        thread_id=UUID(row["thread_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        evaluator_invocation_id=UUID(row["evaluator_invocation_id"]),
        build_candidate_id=UUID(row["build_candidate_id"]),
        status=cast(
            Literal["pass", "partial", "fail", "blocked"], row["status"]
        ),
        summary=summary,
        issues_json=row.get("issues_json") or [],
        metrics_json=row.get("metrics_json") or {},
        artifacts_json=row.get("artifacts_json") or [],
        raw_payload_json=row.get("raw_payload_json")
        if isinstance(row.get("raw_payload_json"), dict)
        else None,
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_thread(row: dict[str, Any]) -> ThreadRecord:
    iid = row.get("identity_id")
    cp = row.get("current_checkpoint_id")
    return ThreadRecord(
        thread_id=UUID(row["thread_id"]),
        identity_id=UUID(iid) if iid else None,
        thread_kind=str(row.get("thread_kind", "build")),
        status=str(row.get("status", "active")),
        current_checkpoint_id=UUID(cp) if cp else None,
    )


def _row_to_staging_snapshot(row: dict[str, Any]) -> StagingSnapshotRecord:
    iid = row.get("identity_id")
    gid = row.get("graph_run_id")
    psid = row.get("prior_staging_snapshot_id")
    sp = row.get("snapshot_payload_json")
    return StagingSnapshotRecord(
        staging_snapshot_id=UUID(row["staging_snapshot_id"]),
        thread_id=UUID(row["thread_id"]),
        build_candidate_id=UUID(row["build_candidate_id"]),
        graph_run_id=UUID(gid) if gid else None,
        identity_id=UUID(iid) if iid else None,
        prior_staging_snapshot_id=UUID(psid) if psid else None,
        snapshot_payload_json=sp if isinstance(sp, dict) else {},
        preview_url=row.get("preview_url"),
        status=str(row.get("status", "review_ready")),
        created_at=_ts_to_iso(row.get("created_at")) or "",
        approved_by=row.get("approved_by"),
        approved_at=_ts_to_iso(row.get("approved_at")),
        rejected_by=row.get("rejected_by"),
        rejected_at=_ts_to_iso(row.get("rejected_at")),
        rejection_reason=row.get("rejection_reason"),
        user_rating=row.get("user_rating"),
        user_feedback=row.get("user_feedback"),
        rated_at=_ts_to_iso(row.get("rated_at")),
        marked_for_review=row.get("marked_for_review", False),
        mark_reason=row.get("mark_reason"),
        review_tags=row.get("review_tags") or [],
    )


def _row_to_autonomous_loop(row: dict[str, Any]) -> AutonomousLoopRecord:
    def _uuid_or_none(val: Any) -> UUID | None:
        return UUID(val) if val else None

    raw_phase = row.get("phase", "identity_fetch") or "identity_fetch"
    if raw_phase in ("planning", "generating", "evaluating"):
        raw_phase = "graph_cycle"
    _valid_phases = frozenset({"identity_fetch", "graph_cycle", "proposing", "idle"})
    if raw_phase not in _valid_phases:
        raw_phase = "graph_cycle"

    return AutonomousLoopRecord(
        loop_id=UUID(row["loop_id"]),
        identity_id=UUID(row["identity_id"]),
        identity_url=row["identity_url"],
        status=row.get("status", "pending"),
        phase=raw_phase,
        iteration_count=row.get("iteration_count", 0),
        max_iterations=row.get("max_iterations", 50),
        current_thread_id=_uuid_or_none(row.get("current_thread_id")),
        current_graph_run_id=_uuid_or_none(row.get("current_graph_run_id")),
        last_staging_snapshot_id=_uuid_or_none(row.get("last_staging_snapshot_id")),
        last_evaluator_status=row.get("last_evaluator_status"),
        last_evaluator_score=row.get("last_evaluator_score"),
        exploration_directions=row.get("exploration_directions") or [],
        completed_directions=row.get("completed_directions") or [],
        auto_publish_threshold=row.get("auto_publish_threshold", 0.85),
        proposed_staging_id=_uuid_or_none(row.get("proposed_staging_id")),
        proposed_at=_ts_to_iso(row.get("proposed_at")),
        locked_at=_ts_to_iso(row.get("locked_at")),
        locked_by=row.get("locked_by"),
        created_at=_ts_to_iso(row.get("created_at")) or "",
        updated_at=_ts_to_iso(row.get("updated_at")) or "",
        completed_at=_ts_to_iso(row.get("completed_at")),
        total_staging_count=row.get("total_staging_count", 0),
        total_publication_count=row.get("total_publication_count", 0),
        best_rating=row.get("best_rating"),
        last_error=row.get("last_error"),
        consecutive_graph_failures=int(row.get("consecutive_graph_failures") or 0),
    )


def _row_to_publication_snapshot(row: dict[str, Any]) -> PublicationSnapshotRecord:
    tid = row.get("thread_id")
    gid = row.get("graph_run_id")
    iid = row.get("identity_id")
    pid = row.get("parent_publication_snapshot_id")
    pj = row.get("payload_json")
    vis = row.get("visibility", "private")
    return PublicationSnapshotRecord(
        publication_snapshot_id=UUID(row["publication_snapshot_id"]),
        source_staging_snapshot_id=UUID(row["source_staging_snapshot_id"]),
        thread_id=UUID(tid) if tid else None,
        graph_run_id=UUID(gid) if gid else None,
        identity_id=UUID(iid) if iid else None,
        payload_json=pj if isinstance(pj, dict) else {},
        visibility=cast(Literal["private", "public"], vis),
        published_by=row.get("published_by"),
        parent_publication_snapshot_id=UUID(pid) if pid else None,
        published_at=_ts_to_iso(row.get("published_at")) or "",
    )


def _row_to_graph_run_event(row: dict[str, Any]) -> GraphRunEventRecord:
    return GraphRunEventRecord(
        graph_run_event_id=UUID(row["graph_run_event_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        event_type=str(row["event_type"]),
        payload_json=row.get("payload_json") or {},
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_checkpoint(row: dict[str, Any]) -> CheckpointRecord:
    cc = row.get("context_compaction_json")
    raw_kind = str(row.get("checkpoint_kind", "manual"))
    allowed = ("pre_role", "post_role", "post_step", "interrupt", "manual")
    ck = cast(
        Literal["pre_role", "post_role", "post_step", "interrupt", "manual"],
        raw_kind if raw_kind in allowed else "manual",
    )
    sj = row.get("state_json")
    return CheckpointRecord(
        checkpoint_id=UUID(row["checkpoint_id"]),
        thread_id=UUID(row["thread_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        checkpoint_kind=ck,
        state_json=sj if isinstance(sj, dict) else {},
        context_compaction_json=cc if isinstance(cc, dict) else None,
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_role_invocation(row: dict[str, Any]) -> RoleInvocationRecord:
    out = row.get("output_payload_json")
    rm = row.get("routing_metadata_json")
    return RoleInvocationRecord(
        role_invocation_id=UUID(row["role_invocation_id"]),
        graph_run_id=UUID(row["graph_run_id"]),
        thread_id=UUID(row["thread_id"]),
        role_type=cast(Literal["planner", "generator", "evaluator"], row["role_type"]),
        provider=cast(Literal["kiloclaw"], row.get("provider", "kiloclaw")),
        provider_config_key=str(row.get("provider_config_key", "")),
        input_payload_json=row.get("input_payload_json") or {},
        output_payload_json=out if isinstance(out, dict) else None,
        routing_metadata_json=rm if isinstance(rm, dict) else {},
        status=cast(
            Literal["queued", "running", "completed", "failed"], row["status"]
        ),
        iteration_index=int(row.get("iteration_index", 0)),
        started_at=_ts_to_iso(row.get("started_at")) or "",
        ended_at=_ts_to_iso(row.get("ended_at")),
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
        self._run(
            "save_graph_run",
            "graph_run",
            lambda: self._client.table("graph_run")
            .upsert(row, on_conflict="graph_run_id")
            .execute(),
            graph_run_id=str(record.graph_run_id),
        )

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

    def list_graph_runs(
        self,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        identity_id: UUID | None = None,
        limit: int = 50,
    ) -> list[GraphRunRecord]:
        lim = max(1, min(limit, 500))
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
        status: Literal["running", "paused", "completed", "failed"],
        ended_at: str | None,
    ) -> None:
        patch: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if ended_at is not None:
            patch["ended_at"] = ended_at
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
                if "23505" not in str(e):
                    raise
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
            .eq("status", "running")
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

    # --- Autonomous Loop ---

    def save_autonomous_loop(self, record: "AutonomousLoopRecord") -> None:
        from kmbl_orchestrator.domain import AutonomousLoopRecord

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

    def get_autonomous_loop(self, loop_id: UUID) -> "AutonomousLoopRecord | None":
        def _query() -> Any:
            return self._client.table("autonomous_loop").select("*").eq("loop_id", str(loop_id)).limit(1).execute()

        res = self._run("get_autonomous_loop", "autonomous_loop", _query, loop_id=str(loop_id))
        if not res.data:
            return None
        return _row_to_autonomous_loop(res.data[0])

    def get_autonomous_loop_for_identity(self, identity_id: UUID) -> "AutonomousLoopRecord | None":
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
    ) -> list["AutonomousLoopRecord"]:
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

    def get_next_pending_loop(self) -> "AutonomousLoopRecord | None":
        from datetime import datetime, timezone, timedelta

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
        from datetime import datetime, timezone, timedelta

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
        exploration_directions: list | None = None,
        completed_directions: list | None = None,
        proposed_staging_id: UUID | None = None,
        total_staging_count: int | None = None,
        best_rating: int | None = None,
        last_error: str | None = None,
        consecutive_graph_failures: int | None = None,
        reset_loop_error: bool = False,
    ) -> "AutonomousLoopRecord | None":
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

    # ---- Working staging ----

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
        row: dict[str, Any] = {
            "working_staging_id": str(record.working_staging_id),
            "thread_id": str(record.thread_id),
            "payload_json": record.payload_json,
            "last_update_mode": record.last_update_mode,
            "revision": record.revision,
            "status": record.status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "stagnation_count": record.stagnation_count,
            "last_evaluator_issue_count": record.last_evaluator_issue_count,
            "last_revision_summary_json": record.last_revision_summary_json,
        }
        if record.identity_id is not None:
            row["identity_id"] = str(record.identity_id)
        if record.last_update_graph_run_id is not None:
            row["last_update_graph_run_id"] = str(record.last_update_graph_run_id)
        if record.last_update_build_candidate_id is not None:
            row["last_update_build_candidate_id"] = str(record.last_update_build_candidate_id)
        if record.current_checkpoint_id is not None:
            row["current_checkpoint_id"] = str(record.current_checkpoint_id)
        if record.last_rebuild_revision is not None:
            row["last_rebuild_revision"] = record.last_rebuild_revision
        self._run(
            "save_working_staging",
            "working_staging",
            lambda: self._client.table("working_staging")
            .upsert(row, on_conflict="working_staging_id")
            .execute(),
            working_staging_id=str(record.working_staging_id),
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


def _row_to_identity_source(row: dict[str, Any]) -> IdentitySourceRecord:
    return IdentitySourceRecord(
        identity_source_id=UUID(row["identity_source_id"]),
        identity_id=UUID(row["identity_id"]),
        source_type=str(row["source_type"]),
        source_uri=row.get("source_uri"),
        raw_text=row.get("raw_text"),
        metadata_json=row.get("metadata_json") or {},
        created_at=_ts_to_iso(row.get("created_at")) or "",
    )


def _row_to_identity_profile(row: dict[str, Any]) -> IdentityProfileRecord:
    oq = row.get("open_questions_json")
    return IdentityProfileRecord(
        identity_id=UUID(row["identity_id"]),
        profile_summary=row.get("profile_summary"),
        facets_json=row.get("facets_json") if isinstance(row.get("facets_json"), dict) else {},
        open_questions_json=oq if isinstance(oq, list) else [],
        updated_at=_ts_to_iso(row.get("updated_at")) or "",
    )


def _row_to_working_staging(row: dict[str, Any]) -> WorkingStagingRecord:
    iid = row.get("identity_id")
    gid = row.get("last_update_graph_run_id")
    bcid = row.get("last_update_build_candidate_id")
    cpid = row.get("current_checkpoint_id")
    pj = row.get("payload_json")
    lrr = row.get("last_rebuild_revision")
    lrsj = row.get("last_revision_summary_json")
    return WorkingStagingRecord(
        working_staging_id=UUID(row["working_staging_id"]),
        thread_id=UUID(row["thread_id"]),
        identity_id=UUID(iid) if iid else None,
        payload_json=pj if isinstance(pj, dict) else {},
        last_update_mode=str(row.get("last_update_mode", "init")),  # type: ignore[arg-type]
        last_update_graph_run_id=UUID(gid) if gid else None,
        last_update_build_candidate_id=UUID(bcid) if bcid else None,
        current_checkpoint_id=UUID(cpid) if cpid else None,
        revision=int(row.get("revision", 0)),
        status=str(row.get("status", "draft")),  # type: ignore[arg-type]
        created_at=_ts_to_iso(row.get("created_at")) or "",
        updated_at=_ts_to_iso(row.get("updated_at")) or "",
        last_rebuild_revision=int(lrr) if lrr is not None else None,
        stagnation_count=int(row.get("stagnation_count", 0)),
        last_evaluator_issue_count=int(row.get("last_evaluator_issue_count", 0)),
        last_revision_summary_json=lrsj if isinstance(lrsj, dict) else {},
    )


def _row_to_staging_checkpoint(row: dict[str, Any]) -> StagingCheckpointRecord:
    gid = row.get("source_graph_run_id")
    pj = row.get("payload_snapshot_json")
    rc = row.get("reason_category")
    re = row.get("reason_explanation")
    return StagingCheckpointRecord(
        staging_checkpoint_id=UUID(row["staging_checkpoint_id"]),
        working_staging_id=UUID(row["working_staging_id"]),
        thread_id=UUID(row["thread_id"]),
        payload_snapshot_json=pj if isinstance(pj, dict) else {},
        revision_at_checkpoint=int(row.get("revision_at_checkpoint", 0)),
        trigger=str(row.get("trigger", "post_patch")),  # type: ignore[arg-type]
        source_graph_run_id=UUID(gid) if gid else None,
        created_at=_ts_to_iso(row.get("created_at")) or "",
        reason_category=rc if isinstance(rc, str) else None,
        reason_explanation=re if isinstance(re, str) else None,
    )
