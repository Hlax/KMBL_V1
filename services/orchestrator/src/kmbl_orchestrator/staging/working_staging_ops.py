"""Mutable working-staging operations: patch, rebuild, checkpoint, rollback, approve."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    PublicationSnapshotRecord,
    StagingCheckpointRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.staging.build_snapshot import (
    build_staging_snapshot_payload,
)
from kmbl_orchestrator.staging.checkpoint_policy import (
    CheckpointReason,
    checkpoint_reason_to_trigger,
    decide_post_update_checkpoint,
    decide_pre_update_checkpoint,
)
from kmbl_orchestrator.staging.guardrails import (
    compute_stagnation_count,
    evaluate_guardrails,
)
from kmbl_orchestrator.staging.mutation_intent import (
    apply_mutation_plan_to_refs,
    extract_mutation_intent,
    resolve_mutation_plan,
)
from kmbl_orchestrator.staging.pressure import (
    PressureEvaluation,
    count_patches_since_rebuild,
    evaluate_staging_pressure,
)
from kmbl_orchestrator.staging.revision_journal import (
    build_revision_summary,
    compute_artifact_delta,
    extract_issue_categories,
    revision_summary_to_event_payload,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Update-mode heuristic (enhanced with pressure evaluation)
# ---------------------------------------------------------------------------

def choose_update_mode(
    working_staging: WorkingStagingRecord | None,
    evaluation_status: str,
) -> Literal["patch", "rebuild"]:
    """Decide whether the next generator output should patch or replace working staging.

    Rebuild when:
    - no working staging yet (first run)
    - revision is 0 (empty surface)
    - evaluator said ``fail`` (current state is too broken to patch)

    Legacy interface — use choose_update_mode_with_pressure for richer decisions.
    """
    if working_staging is None or working_staging.revision == 0:
        return "rebuild"
    if evaluation_status == "fail":
        return "rebuild"
    return "patch"


def choose_update_mode_with_pressure(
    working_staging: WorkingStagingRecord | None,
    evaluation_status: str,
    evaluation_issue_count: int = 0,
) -> tuple[Literal["patch", "rebuild"], PressureEvaluation | None, str]:
    """Decide update mode using pressure evaluation.

    Returns (mode, pressure_evaluation, mode_reason_category).
    """
    if working_staging is None:
        return "rebuild", None, "initial_build"

    if working_staging.revision == 0:
        return "rebuild", None, "initial_build"

    patches_since = count_patches_since_rebuild(
        working_staging.revision,
        working_staging.last_rebuild_revision,
    )

    artifact_refs = _extract_artifact_refs(working_staging.payload_json)
    has_html = _payload_has_previewable_html(working_staging.payload_json)

    pressure = evaluate_staging_pressure(
        revision=working_staging.revision,
        patches_since_last_rebuild=patches_since,
        evaluator_status=evaluation_status,
        unresolved_issue_count=evaluation_issue_count,
        stagnation_iterations=working_staging.stagnation_count,
        total_artifact_count=len(artifact_refs),
        has_previewable_html=has_html,
    )

    if evaluation_status == "fail":
        return "rebuild", pressure, "evaluator_fail_status"

    if pressure.should_rebuild:
        return "rebuild", pressure, pressure.rebuild_reason or "pressure_threshold_exceeded"

    guardrails = evaluate_guardrails(
        revision=working_staging.revision,
        patches_since_rebuild=patches_since,
        stagnation_count=working_staging.stagnation_count,
        artifact_count=len(artifact_refs),
        checkpoint_count=0,
        has_previewable_html=has_html,
    )

    if guardrails.forced_rebuild_required:
        return "rebuild", pressure, guardrails.forced_rebuild_reason or "guardrail_violation"

    return "patch", pressure, "incremental_improvement"


def _extract_artifact_refs(payload: dict[str, Any]) -> list[Any]:
    """Extract artifact refs from payload."""
    arts = payload.get("artifacts")
    if isinstance(arts, dict):
        refs = arts.get("artifact_refs", [])
        return refs if isinstance(refs, list) else []
    return []


# ---------------------------------------------------------------------------
# Payload merge (patch mode)
# ---------------------------------------------------------------------------

def merge_artifacts_into_payload(
    existing_payload: dict[str, Any],
    new_payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge ``new_payload`` into ``existing_payload`` (patch semantics).

    - Top-level scalar keys in ``new_payload`` overwrite.
    - ``artifacts.artifact_refs``: new refs replace existing refs at the same ``path``;
      new paths are appended; existing paths not mentioned in the new set are kept.
    - ``metadata.working_state_patch``: deep-merged (new keys overwrite, old kept).
    - ``metadata.frontend_static``: replaced entirely from new payload when present.
    """
    merged = copy.deepcopy(existing_payload)

    for key in ("version", "ids", "summary", "evaluation", "preview"):
        if key in new_payload:
            merged[key] = copy.deepcopy(new_payload[key])

    _merge_artifacts(merged, new_payload)
    _merge_metadata(merged, new_payload)

    return merged


def _merge_artifacts(merged: dict[str, Any], new_payload: dict[str, Any]) -> None:
    existing_arts = merged.get("artifacts", {})
    new_arts = new_payload.get("artifacts", {})
    existing_refs: list[dict[str, Any]] = existing_arts.get("artifact_refs", [])
    new_refs: list[dict[str, Any]] = new_arts.get("artifact_refs", [])

    if not new_refs:
        return

    by_path: dict[str, dict[str, Any]] = {}
    for ref in existing_refs:
        if isinstance(ref, dict):
            path = ref.get("path", "")
            by_path[path] = ref

    for ref in new_refs:
        if isinstance(ref, dict):
            path = ref.get("path", "")
            by_path[path] = copy.deepcopy(ref)

    if "artifacts" not in merged:
        merged["artifacts"] = {}
    merged["artifacts"]["artifact_refs"] = list(by_path.values())


def _merge_metadata(merged: dict[str, Any], new_payload: dict[str, Any]) -> None:
    new_meta = new_payload.get("metadata", {})
    if not new_meta:
        return

    if "metadata" not in merged:
        merged["metadata"] = {}

    new_wsp = new_meta.get("working_state_patch")
    if isinstance(new_wsp, dict):
        old_wsp = merged["metadata"].get("working_state_patch", {})
        if not isinstance(old_wsp, dict):
            old_wsp = {}
        old_wsp.update(copy.deepcopy(new_wsp))
        merged["metadata"]["working_state_patch"] = old_wsp

    new_fs = new_meta.get("frontend_static")
    if new_fs is not None:
        merged["metadata"]["frontend_static"] = copy.deepcopy(new_fs)

    if "preview_kind" in new_meta:
        merged["metadata"]["preview_kind"] = new_meta["preview_kind"]


# ---------------------------------------------------------------------------
# Build payload from a single build candidate (same V1 shape, for merge/replace)
# ---------------------------------------------------------------------------

def build_payload_from_candidate(
    *,
    build_candidate: BuildCandidateRecord,
    evaluation_report: EvaluationReportRecord,
    build_spec: BuildSpecRecord | None,
    thread_id: UUID,
    identity_id: UUID | None,
) -> dict[str, Any]:
    """Build a V1-shaped payload dict from a build candidate, reusing the snapshot builder."""
    from kmbl_orchestrator.domain import ThreadRecord

    pseudo_thread = ThreadRecord(
        thread_id=thread_id,
        identity_id=identity_id,
    )
    return build_staging_snapshot_payload(
        build_candidate=build_candidate,
        evaluation_report=evaluation_report,
        thread=pseudo_thread,
        build_spec=build_spec,
    )


# ---------------------------------------------------------------------------
# Apply generator output to working staging
# ---------------------------------------------------------------------------

def apply_generator_to_working_staging(
    *,
    working_staging: WorkingStagingRecord,
    build_candidate: BuildCandidateRecord,
    evaluation_report: EvaluationReportRecord,
    build_spec: BuildSpecRecord | None,
    mode: Literal["patch", "rebuild"],
    mode_reason_category: str = "incremental_improvement",
    pressure_evaluation: PressureEvaluation | None = None,
) -> WorkingStagingRecord:
    """Apply a generator build candidate to the working staging record.

    Returns the *mutated* ``WorkingStagingRecord`` (same object, updated in place).
    The caller is responsible for persisting it and creating any checkpoints.
    """
    previous_revision = working_staging.revision
    before_refs = _extract_artifact_refs(working_staging.payload_json)

    new_payload = build_payload_from_candidate(
        build_candidate=build_candidate,
        evaluation_report=evaluation_report,
        build_spec=build_spec,
        thread_id=working_staging.thread_id,
        identity_id=working_staging.identity_id,
    )

    new_refs = _extract_artifact_refs(new_payload)
    intents = extract_mutation_intent(build_candidate.raw_payload_json or {})
    plan = resolve_mutation_plan(
        update_mode=mode,
        intents=intents,
        new_artifact_refs=new_refs,
        existing_artifact_refs=before_refs,
    )

    if mode == "rebuild":
        working_staging.payload_json = new_payload
        working_staging.last_rebuild_revision = previous_revision + 1
    else:
        if plan.fallback_used:
            working_staging.payload_json = merge_artifacts_into_payload(
                working_staging.payload_json,
                new_payload,
            )
        else:
            merged_refs = apply_mutation_plan_to_refs(plan, before_refs, new_refs)
            working_staging.payload_json = merge_artifacts_into_payload(
                working_staging.payload_json,
                new_payload,
            )
            if "artifacts" not in working_staging.payload_json:
                working_staging.payload_json["artifacts"] = {}
            working_staging.payload_json["artifacts"]["artifact_refs"] = merged_refs

    working_staging.last_update_mode = mode
    working_staging.last_update_graph_run_id = build_candidate.graph_run_id
    working_staging.last_update_build_candidate_id = build_candidate.build_candidate_id
    working_staging.revision += 1
    working_staging.updated_at = _utc_now_iso()

    after_refs = _extract_artifact_refs(working_staging.payload_json)
    after_has_html = _payload_has_previewable_html(working_staging.payload_json)

    # Partial/fail iterations update draft habitat for engineering; only **pass** promotes
    # operator-facing review_ready (artifact-first: avoid treating partials as "ready for review").
    if after_has_html and working_staging.status == "draft":
        if evaluation_report.status == "pass":
            working_staging.status = "review_ready"

    new_stagnation = compute_stagnation_count(
        current_issue_count=len(evaluation_report.issues_json),
        previous_issue_count=working_staging.last_evaluator_issue_count,
        current_status=evaluation_report.status,
        previous_status="unknown",
        existing_stagnation_count=working_staging.stagnation_count,
    )
    working_staging.stagnation_count = new_stagnation
    working_staging.last_evaluator_issue_count = len(evaluation_report.issues_json)

    artifact_delta = compute_artifact_delta(before_refs, after_refs)
    improvement = _compute_improvement_signal(
        evaluation_report.status,
        len(evaluation_report.issues_json),
        working_staging.last_evaluator_issue_count,
    )

    revision_summary = build_revision_summary(
        revision=working_staging.revision,
        previous_revision=previous_revision,
        update_mode=mode,
        mode_reason_category=mode_reason_category,
        mode_reason_explanation=pressure_evaluation.rebuild_reason if pressure_evaluation and pressure_evaluation.rebuild_reason else "",
        contributing_factors=[s.signal_name for s in (pressure_evaluation.signals if pressure_evaluation else []) if s.exceeded],
        evaluator_status=evaluation_report.status,
        evaluator_issue_count=len(evaluation_report.issues_json),
        evaluator_issue_categories=extract_issue_categories(evaluation_report.issues_json),
        improvement_signal=improvement,
        artifacts_added=artifact_delta.artifacts_added,
        artifacts_replaced=artifact_delta.artifacts_replaced,
        artifacts_removed=artifact_delta.artifacts_removed,
        total_artifact_count=artifact_delta.total_artifact_count,
        has_previewable_html=artifact_delta.has_previewable_html,
        outcome_assessment=_compute_outcome(improvement, mode),
    )
    working_staging.last_revision_summary_json = revision_summary_to_event_payload(revision_summary)

    return working_staging


def _compute_improvement_signal(
    status: str,
    issue_count: int,
    previous_issue_count: int,
) -> str:
    """Compute improvement signal based on evaluator state changes."""
    if status == "pass":
        return "improved"
    if issue_count < previous_issue_count:
        return "improved"
    if issue_count > previous_issue_count:
        return "regressed"
    return "neutral"


def _compute_outcome(improvement: str, mode: str) -> str:
    """Compute outcome assessment."""
    if improvement == "improved":
        return "progress"
    if improvement == "regressed":
        return "regression"
    if mode == "rebuild":
        return "neutral"
    return "neutral"


# ---------------------------------------------------------------------------
# Checkpoint logic (enhanced with policy)
# ---------------------------------------------------------------------------

def should_auto_checkpoint(
    before: WorkingStagingRecord,
    after: WorkingStagingRecord,
    mode: Literal["patch", "rebuild"],
) -> str | None:
    """Return the checkpoint trigger reason, or None if no checkpoint is warranted.

    Rules:
    - ``pre_rebuild``: always checkpoint before a rebuild (checked by caller *before* apply)
    - ``post_patch``: after a successful patch (now using milestones)
    - ``first_previewable_html``: when working staging first gains previewable HTML

    Legacy interface — use should_auto_checkpoint_with_policy for richer decisions.
    """
    before_has_html = _payload_has_previewable_html(before.payload_json)
    after_has_html = _payload_has_previewable_html(after.payload_json)

    if not before_has_html and after_has_html:
        return "first_previewable_html"

    if mode == "patch":
        return "post_patch"

    return None


def should_auto_checkpoint_with_policy(
    before: WorkingStagingRecord,
    after: WorkingStagingRecord,
    mode: Literal["patch", "rebuild"],
    pressure_score: float = 0.0,
) -> tuple[str | None, CheckpointReason | None]:
    """Return checkpoint trigger and reason using policy-based decisions.

    Returns (trigger_string, CheckpointReason) or (None, None) if no checkpoint needed.
    """
    before_has_html = _payload_has_previewable_html(before.payload_json)
    after_has_html = _payload_has_previewable_html(after.payload_json)
    is_first_previewable = not before_has_html and after_has_html

    decision = decide_post_update_checkpoint(
        before=before,
        after=after,
        update_mode=mode,
        is_first_previewable=is_first_previewable,
        is_milestone=(after.revision > 0 and after.revision % 3 == 0),
    )

    if decision.should_checkpoint and decision.reason:
        trigger = checkpoint_reason_to_trigger(decision.reason)
        return trigger, decision.reason

    return None, None


def create_staging_checkpoint(
    working_staging: WorkingStagingRecord,
    *,
    trigger: str,
    source_graph_run_id: UUID | None = None,
    reason: CheckpointReason | None = None,
) -> StagingCheckpointRecord:
    """Snapshot the current working staging payload into a checkpoint record."""
    return StagingCheckpointRecord(
        staging_checkpoint_id=uuid4(),
        working_staging_id=working_staging.working_staging_id,
        thread_id=working_staging.thread_id,
        payload_snapshot_json=copy.deepcopy(working_staging.payload_json),
        revision_at_checkpoint=working_staging.revision,
        trigger=trigger,  # type: ignore[arg-type]
        source_graph_run_id=source_graph_run_id,
        reason_category=reason.category if reason else None,
        reason_explanation=reason.explanation if reason else None,
    )


def create_pre_rebuild_checkpoint(
    working_staging: WorkingStagingRecord,
    *,
    source_graph_run_id: UUID | None = None,
    pressure_score: float = 0.0,
) -> StagingCheckpointRecord | None:
    """Create a pre-rebuild safety checkpoint if warranted by policy."""
    decision = decide_pre_update_checkpoint(
        working_staging=working_staging,
        update_mode="rebuild",
        pressure_score=pressure_score,
    )

    if not decision.should_checkpoint or not decision.reason:
        return None

    return create_staging_checkpoint(
        working_staging,
        trigger=checkpoint_reason_to_trigger(decision.reason),
        source_graph_run_id=source_graph_run_id,
        reason=decision.reason,
    )


# ---------------------------------------------------------------------------
# Recovery / rollback
# ---------------------------------------------------------------------------

def rollback_to_checkpoint(
    working_staging: WorkingStagingRecord,
    checkpoint: StagingCheckpointRecord,
) -> WorkingStagingRecord:
    """Restore working staging payload from a checkpoint."""
    working_staging.payload_json = copy.deepcopy(checkpoint.payload_snapshot_json)
    working_staging.current_checkpoint_id = checkpoint.staging_checkpoint_id
    working_staging.revision += 1
    working_staging.last_update_mode = "init"
    working_staging.updated_at = _utc_now_iso()
    return working_staging


def rollback_to_publication(
    working_staging: WorkingStagingRecord,
    publication: PublicationSnapshotRecord,
) -> WorkingStagingRecord:
    """Restore working staging payload from a publication snapshot."""
    working_staging.payload_json = copy.deepcopy(publication.payload_json)
    working_staging.revision += 1
    working_staging.last_update_mode = "init"
    working_staging.status = "review_ready"
    working_staging.updated_at = _utc_now_iso()
    return working_staging


def fresh_rebuild(working_staging: WorkingStagingRecord) -> WorkingStagingRecord:
    """Clear the working staging payload so the next generator run starts fresh."""
    working_staging.payload_json = {}
    working_staging.revision += 1
    working_staging.last_update_mode = "init"
    working_staging.status = "draft"
    working_staging.current_checkpoint_id = None
    working_staging.updated_at = _utc_now_iso()
    return working_staging


# ---------------------------------------------------------------------------
# Approval → publication
# ---------------------------------------------------------------------------

def approve_working_staging(
    working_staging: WorkingStagingRecord,
    *,
    approved_by: str = "operator",
    source_staging_snapshot_id: UUID,
) -> tuple[WorkingStagingRecord, PublicationSnapshotRecord, StagingCheckpointRecord]:
    """Freeze working staging into a publication snapshot.

    ``source_staging_snapshot_id`` must reference a persisted ``staging_snapshot`` row
    (e.g. latest review snapshot for the thread). Callers resolve it; this function
    does not invent surrogate ids.

    Returns (updated working staging, new publication, pre-approval checkpoint).
    """
    checkpoint = create_staging_checkpoint(
        working_staging,
        trigger="pre_approval",
    )

    publication = PublicationSnapshotRecord(
        publication_snapshot_id=uuid4(),
        source_staging_snapshot_id=source_staging_snapshot_id,
        source_working_staging_id=working_staging.working_staging_id,
        source_staging_checkpoint_id=checkpoint.staging_checkpoint_id,
        thread_id=working_staging.thread_id,
        identity_id=working_staging.identity_id,
        payload_json=copy.deepcopy(working_staging.payload_json),
        visibility="private",
        published_by=approved_by,
    )

    working_staging.status = "frozen"
    working_staging.current_checkpoint_id = checkpoint.staging_checkpoint_id
    working_staging.updated_at = _utc_now_iso()

    return working_staging, publication, checkpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload_has_previewable_html(payload: dict[str, Any]) -> bool:
    """Check whether the V1 payload contains at least one previewable HTML artifact."""
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        fs = meta.get("frontend_static")
        if isinstance(fs, dict) and fs.get("has_previewable_html"):
            return True

    arts = payload.get("artifacts")
    if isinstance(arts, dict):
        refs = arts.get("artifact_refs", [])
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if is_frontend_file_artifact_role(ref.get("role")) and ref.get("language") == "html":
                return True

    return False
