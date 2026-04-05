"""Row-to-record deserializers for Supabase repository.

Shared conversion functions that map Supabase/PostgREST row dicts to domain records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

import httpx
import httpcore

from kmbl_orchestrator.domain import (
    AutonomousLoopRecord,
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
    MemoryCategory,
    PublicationSnapshotRecord,
    RoleInvocationRecord,
    StagingCheckpointRecord,
    StagingSnapshotRecord,
    ThreadRecord,
    WorkingStagingRecord,
)


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
    tt = row["trigger_type"]
    return GraphRunRecord(
        graph_run_id=UUID(row["graph_run_id"]),
        thread_id=UUID(row["thread_id"]),
        identity_id=UUID(iid) if iid else None,
        trigger_type=cast(
            Literal[
                "prompt",
                "resume",
                "schedule",
                "system",
                "autonomous_loop",
            ],
            tt,
        ),
        status=cast(GraphRunStatus, row["status"]),
        started_at=_ts_to_iso(row["started_at"]) or "",
        ended_at=_ts_to_iso(row.get("ended_at")),
        interrupt_requested_at=_ts_to_iso(row.get("interrupt_requested_at")),
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
    raw_alignment = row.get("alignment_score")
    alignment_score: float | None = None
    if raw_alignment is not None:
        try:
            alignment_score = float(raw_alignment)
        except (TypeError, ValueError):
            pass
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
        alignment_score=alignment_score,
        alignment_signals_json=row.get("alignment_signals_json") or {},
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
        last_alignment_score=row.get("last_alignment_score"),
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
        provider=cast(
            Literal["kiloclaw", "openclaw"],
            row.get("provider", "openclaw"),
        ),
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
    las = row.get("last_alignment_score")
    last_alignment: float | None = float(las) if las is not None else None
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
        last_alignment_score=last_alignment,
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


def _row_to_identity_cross_run_memory(row: dict[str, Any]) -> IdentityCrossRunMemoryRecord:
    sg = row.get("source_graph_run_id")
    st = row.get("strength")
    strength = float(st) if st is not None else 0.0
    pj = row.get("payload_json")
    cat = str(row.get("category", "run_outcome"))
    return IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=UUID(row["identity_cross_run_memory_id"]),
        identity_id=UUID(row["identity_id"]),
        category=cast(MemoryCategory, cat),
        memory_key=str(row.get("memory_key", "")),
        payload_json=pj if isinstance(pj, dict) else {},
        strength=strength,
        provenance=str(row.get("provenance", "")),
        source_graph_run_id=UUID(sg) if sg else None,
        operator_signal=row.get("operator_signal") if isinstance(row.get("operator_signal"), str) else None,
        created_at=_ts_to_iso(row.get("created_at")) or "",
        updated_at=_ts_to_iso(row.get("updated_at")) or "",
    )
