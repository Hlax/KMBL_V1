"""FastAPI entrypoint — health + internal orchestrator routes (docs/12 §5)."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    PublicationSnapshotRecord,
    StagingSnapshotRecord,
)
from kmbl_orchestrator.publication.eligibility import (
    PublicationIneligible,
    validate_publication_eligibility,
)
from kmbl_orchestrator.persistence.factory import (
    get_repository,
    persisted_graph_runs_available,
    repository_backend,
)
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.graph_run_detail_read_model import (
    build_graph_run_detail_read_model,
)
from kmbl_orchestrator.runtime.scenario_visibility import (
    gallery_strip_visibility_from_staging_payload,
    scenario_badge_from_tag,
    scenario_tag_from_run_state,
)
from kmbl_orchestrator.runtime.graph_run_list_read_model import (
    build_graph_run_list_read_model,
)
from kmbl_orchestrator.runtime.operator_home_summary import (
    build_operator_home_summary,
)
from kmbl_orchestrator.runtime.run_resume import (
    compute_resume_eligibility,
    event_input_for_resume,
)
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.smoke_planner import run_smoke_planner_only
from kmbl_orchestrator.runtime.run_failure_view import build_run_failure_view
from kmbl_orchestrator.runtime.run_snapshot_sanitize import (
    sanitize_checkpoint_state_for_api,
)
from kmbl_orchestrator.runtime.stale_run import reconcile_stale_running_graph_run
from kmbl_orchestrator.staging.read_model import (
    evaluation_summary_from_payload,
    evaluation_summary_section_from_payload,
    identity_hint_from_uuid,
    linked_publications_read_model,
    payload_version_from_payload,
    proposal_read_model,
    review_readiness_explanation_for_staging,
    review_readiness_for_staging_record,
    short_title_from_payload,
    staging_lineage_read_model,
    staging_lifecycle_timeline,
    staging_snapshot_list_item,
)
from kmbl_orchestrator.staging.proposals_queue import (
    fetch_limit as proposals_fetch_limit,
    filter_proposals as filter_proposals_queue,
    normalize_blank as proposals_normalize_blank,
    parse_has_publication as proposals_parse_has_publication,
    parse_sort_mode as proposals_parse_sort_mode,
    sort_proposals_in_place,
    use_wide_pool as proposals_use_wide_pool,
    validate_review_action_state,
)
from kmbl_orchestrator.staging.review_action import derive_review_action_state
from kmbl_orchestrator.seeds import (
    SEEDED_GALLERY_STRIP_EVENT_INPUT,
    SEEDED_GALLERY_STRIP_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    SEEDED_LOCAL_EVENT_INPUT,
    SEEDED_LOCAL_SCENARIO_PRESET,
    SEEDED_SCENARIO_TAG,
    build_seeded_gallery_strip_varied_v1_event_input,
)

app = FastAPI(title="KMBL Orchestrator", version="0.1.0")
_log = logging.getLogger(__name__)


@app.on_event("startup")
async def _orchestrator_verbose_logging() -> None:
    """Opt-in: emit INFO from kmbl_orchestrator.* (root may stay WARNING under uvicorn)."""
    if os.environ.get("ORCHESTRATOR_VERBOSE_LOGS", "").strip().lower() not in ("1", "true", "yes"):
        return
    pkg = logging.getLogger("kmbl_orchestrator")
    pkg.setLevel(logging.INFO)
    if not getattr(pkg, "_kmb_verbose_handler", None):
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        pkg.addHandler(h)
        pkg._kmb_verbose_handler = h  # type: ignore[attr-defined]


def get_repo(settings: Settings = Depends(get_settings)) -> Repository:
    return get_repository(settings)


def get_invoker(settings: Settings = Depends(get_settings)) -> DefaultRoleInvoker:
    return DefaultRoleInvoker(settings=settings)


class StartRunBody(BaseModel):
    """Request body for starting a graph run. Omit identity_id / thread_id for a fresh run."""

    model_config = ConfigDict(
        json_schema_extra={
            # Empty object = safest default in Swagger (do not send the literal "string" for UUIDs).
            "example": {}
        }
    )

    identity_id: UUID | None = Field(
        default=None,
        description=(
            "Optional identity UUID. OpenAPI shows type 'string' because UUIDs are serialized "
            "as strings — use a real UUID, null, or omit this field. Never send the word 'string'."
        ),
    )
    thread_id: UUID | None = Field(
        default=None,
        description=(
            "Optional existing thread UUID. Same as identity_id: real UUID, null, or omit. "
            "Never send the placeholder 'string'."
        ),
    )
    trigger_type: Literal["prompt", "resume", "schedule", "system"] = "prompt"
    event_input: dict[str, Any] = Field(default_factory=dict)
    scenario_preset: (
        Literal[
            "seeded_local_v1",
            "seeded_gallery_strip_v1",
            "seeded_gallery_strip_varied_v1",
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "When set to seeded_local_v1 or seeded_gallery_strip_v1, event_input is replaced "
            "with the canonical seeded scenario (deterministic tag in event_input.scenario). "
            "seeded_gallery_strip_varied_v1 replaces event_input with a non-deterministic "
            "bounded-variation gallery scenario (fresh run_nonce per start). "
            "Ignores event_input for that run."
        ),
    )


class StartRunResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: Literal["running"] = Field(
        default="running",
        description=(
            "Run is accepted and executing asynchronously. Poll GET /orchestrator/runs/{id} "
            "for completed / failed and error details."
        ),
    )
    failure_phase: Literal["planner", "generator", "evaluator"] | None = Field(
        default=None,
        description="Always null from this endpoint; see GET run status when status=failed.",
    )
    failure: dict[str, Any] | None = Field(
        default=None,
        description="Always null from this endpoint; see GET run status when status=failed.",
    )
    error_kind: str | None = Field(
        default=None,
        description="Always null from this endpoint; see GET run status when status=failed.",
    )
    error_message: str | None = Field(
        default=None,
        description="Always null from this endpoint; see GET run status when status=failed.",
    )
    scenario_preset: str | None = Field(
        default=None,
        description="Echo: which seeded preset was applied (e.g. seeded_local_v1), else null.",
    )
    effective_event_input: dict[str, Any] = Field(
        default_factory=dict,
        description="Event input passed into the graph (after applying scenario_preset).",
    )


class BuildSpecSummary(BaseModel):
    """Latest build_spec row for this graph_run (if any)."""

    build_spec_id: str
    status: str
    title_hint: str | None = None


class BuildCandidateSummary(BaseModel):
    build_candidate_id: str
    candidate_kind: str
    status: str


class EvaluationSummary(BaseModel):
    evaluation_report_id: str
    status: str
    summary: str | None = None


class RunTimelineEventSummary(BaseModel):
    event_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class RunStatusResponse(BaseModel):
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"
    graph_run_id: str
    thread_id: str
    status: str
    failure_phase: str | None = Field(
        default=None,
        description="When status=failed, which role (if known).",
    )
    failure: dict[str, Any] | None = Field(
        default=None,
        description="Normalized failure payload when status=failed.",
    )
    error_kind: str | None = Field(
        default=None,
        description="Populated when status=failed (normalized taxonomy).",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable summary when status=failed.",
    )
    iteration_index: int | None = None
    decision: str | None = None
    build_spec: BuildSpecSummary | None = None
    build_candidate: BuildCandidateSummary | None = None
    evaluation: EvaluationSummary | None = None
    snapshot: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Sanitized subset of the latest post-role checkpoint — no raw role provider payloads."
        ),
    )
    scenario_tag: str | None = Field(
        default=None,
        description="From final state event_input.scenario when present (e.g. kmbl_seeded_local_v1).",
    )
    run_event_input: dict[str, Any] | None = Field(
        default=None,
        description="event_input from the post-run checkpoint (what the planner saw).",
    )
    outputs_substantive: bool = Field(
        default=False,
        description="Heuristic: non–no-op title or long evaluation summary or seeded scenario tag.",
    )
    timeline_events: list[RunTimelineEventSummary] = Field(
        default_factory=list,
        description="Append-only execution timeline (most recent window).",
    )


class GraphRunSummaryBlock(BaseModel):
    """Pass H: persisted run metadata for operator run detail."""

    graph_run_id: str
    thread_id: str
    identity_id: str | None = None
    trigger_type: str
    status: str
    started_at: str
    ended_at: str | None = None
    max_iteration_index: int | None = None
    latest_checkpoint_id: str | None = None
    run_state_hint: str
    attention_state: str
    attention_reason: str
    resume_count: int = 0
    last_resumed_at: str | None = None


class RoleInvocationDetailItem(BaseModel):
    role_invocation_id: str
    role_type: str
    status: str
    iteration_index: int
    started_at: str
    ended_at: str | None = None
    provider: str
    provider_config_key: str


class AssociatedOutputsBlock(BaseModel):
    build_spec_id: str | None = None
    build_candidate_id: str | None = None
    evaluation_report_id: str | None = None
    staging_snapshot_id: str | None = None
    publication_snapshot_id: str | None = None


class RunTimelineItem(BaseModel):
    kind: str
    label: str
    timestamp: str
    related_id: str | None = None
    event_type: str
    operator_triggered: bool = False


class OperatorActionItem(BaseModel):
    """Pass L — one operator/API-triggered row from graph_run_event."""

    kind: str
    label: str
    timestamp: str
    details: dict[str, Any] | None = None


class GraphRunDetailResponse(BaseModel):
    """Pass H — persisted read surface only (no live streaming)."""

    summary: GraphRunSummaryBlock
    operator_actions: list[OperatorActionItem] = Field(default_factory=list)
    role_invocations: list[RoleInvocationDetailItem]
    associated_outputs: AssociatedOutputsBlock
    timeline: list[RunTimelineItem]
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"
    resume_eligible: bool = False
    resume_operator_explanation: str | None = None
    retry_eligible: bool = False
    retry_deferred_note: str | None = (
        "Generic retry for failed runs is deferred — no duplicate-run rule in this release."
    )
    scenario_tag: str | None = None
    scenario_badge: str | None = None


class GraphRunListItem(BaseModel):
    """Pass I — one row in the runs index (persisted only)."""

    graph_run_id: str
    thread_id: str
    identity_id: str | None = None
    trigger_type: str
    status: str
    started_at: str
    ended_at: str | None = None
    max_iteration_index: int | None = None
    run_state_hint: str
    role_invocation_count: int = 0
    latest_staging_snapshot_id: str | None = None
    attention_state: str
    attention_reason: str
    scenario_tag: str | None = Field(
        default=None,
        description="From latest post-role checkpoint event_input.scenario when present.",
    )
    scenario_badge: str | None = Field(
        default=None,
        description="gallery_strip | local_seed | other — derived from scenario_tag.",
    )


class GraphRunListResponse(BaseModel):
    runs: list[GraphRunListItem]
    count: int
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"


class OperatorHomeRuntimeBlock(BaseModel):
    """Pass O — bounded window over recent graph_run rows."""

    runs_in_window: int
    runs_needing_attention: int
    failed_count: int
    paused_count: int


class OperatorHomeReviewQueueBlock(BaseModel):
    """Pass O — counts from staging snapshots in a bounded window."""

    ready_for_review: int
    ready_to_publish: int
    published: int
    not_actionable: int


class OperatorHomeCanonBlock(BaseModel):
    """Pass O — latest publication snapshot (if any)."""

    has_current_publication: bool
    latest_publication_snapshot_id: str | None = None
    latest_published_at: str | None = None


class OperatorHomeSummaryResponse(BaseModel):
    """Pass O — control-plane home dashboard (persisted only)."""

    basis: Literal["persisted_rows_only"] = "persisted_rows_only"
    runtime: OperatorHomeRuntimeBlock
    review_queue: OperatorHomeReviewQueueBlock
    canon: OperatorHomeCanonBlock


class LinkedPublicationItem(BaseModel):
    """Publication rows sourced from this staging snapshot (Pass F)."""

    publication_snapshot_id: str
    published_at: str
    published_by: str | None = None
    visibility: str


class LifecycleTimelineItem(BaseModel):
    """Derived lifecycle step from persisted rows only (Pass F)."""

    kind: str
    label: str
    at: str | None = None
    ref_publication_snapshot_id: str | None = None


class StagingLineageSection(BaseModel):
    """Provenance from persisted row + ``snapshot_payload_json.ids`` (Pass G)."""

    thread_id: str
    graph_run_id: str | None = None
    build_candidate_id: str
    evaluation_report_id: str | None = None
    identity_id: str | None = None


class StagingEvaluationDetail(BaseModel):
    """Evaluator output slice from persisted payload (Pass G) — not live runtime."""

    present: bool = False
    status: str | None = None
    summary: str = ""
    issue_count: int = 0
    artifact_count: int = 0
    metrics_key_count: int = 0
    metrics_preview: dict[str, Any] = Field(default_factory=dict)


class StagingSnapshotDetailResponse(BaseModel):
    """
    Persisted ``staging_snapshot`` row plus derived read-model fields (Pass C).

    Source of truth is the stored row and ``snapshot_payload_json`` only — no runtime or
    checkpoint reconstruction.
    """

    staging_snapshot_id: str
    thread_id: str
    build_candidate_id: str
    graph_run_id: str | None = None
    identity_id: str | None = None
    snapshot_payload_json: dict[str, Any] = Field(
        default_factory=dict,
        description="V1 payload sections: ids, summary, evaluation, preview, artifacts, metadata.",
    )
    preview_url: str | None = None
    status: str
    created_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    evaluation_summary: str = ""
    short_title: str | None = None
    identity_hint: str | None = None
    review_readiness: dict[str, Any] = Field(default_factory=dict)
    review_readiness_explanation: str = Field(
        default="",
        description="Derived operator-facing text from persisted status + payload (Pass G).",
    )
    payload_version: int | None = Field(
        default=None,
        description="From ``snapshot_payload_json.version`` when present (e.g. 1).",
    )
    lineage: StagingLineageSection = Field(
        description="Structured provenance — same ids as row + payload.ids where present.",
    )
    evaluation: StagingEvaluationDetail = Field(
        default_factory=StagingEvaluationDetail,
        description="Persisted evaluator output from snapshot payload (Pass G).",
    )
    linked_publications: list[LinkedPublicationItem] = Field(default_factory=list)
    lifecycle_timeline: list[LifecycleTimelineItem] = Field(default_factory=list)
    content_kind: str | None = Field(
        default=None,
        description="Derived: gallery_strip when payload includes ui_gallery_strip_v1.",
    )
    has_gallery_strip: bool = False
    gallery_strip_item_count: int = 0
    gallery_image_artifact_count: int = 0
    gallery_items_with_artifact_key: int = 0


class ApproveStagingBody(BaseModel):
    approved_by: str | None = Field(
        default=None,
        description="Operator identifier (audit / timeline only).",
    )


class RejectStagingBody(BaseModel):
    rejected_by: str | None = Field(
        default=None,
        description="Operator identifier (audit only).",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional short note stored on the staging row.",
    )


class UnapproveStagingBody(BaseModel):
    unapproved_by: str | None = Field(
        default=None,
        description="Optional operator id recorded in the graph_run event payload only.",
    )


class StagingMutationResponse(BaseModel):
    """Shared shape for approve / reject / unapprove responses."""

    staging_snapshot_id: str
    thread_id: str
    status: str
    created_at: str
    preview_url: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    review_readiness: dict[str, Any] = Field(default_factory=dict)


ApproveStagingResponse = StagingMutationResponse


class CreatePublicationBody(BaseModel):
    staging_snapshot_id: UUID
    visibility: Literal["private", "public"] = "private"
    published_by: str | None = Field(
        default=None,
        description="Operator identifier recorded on the publication row.",
    )


class CreatePublicationResponse(BaseModel):
    publication_snapshot_id: str
    source_staging_snapshot_id: str
    identity_id: str | None
    visibility: str
    published_at: str
    published_by: str | None = None
    status: Literal["published"] = "published"


class PublicationSnapshotListItem(BaseModel):
    publication_snapshot_id: str
    source_staging_snapshot_id: str
    identity_id: str | None = None
    visibility: str
    published_at: str
    published_by: str | None = None


class PublicationListResponse(BaseModel):
    publications: list[PublicationSnapshotListItem]
    count: int
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"


class StagingListResponse(BaseModel):
    """GET /orchestrator/staging — compact rows only (no full ``snapshot_payload_json``)."""

    snapshots: list[dict[str, Any]]
    count: int
    basis: Literal["persisted_rows_only"] = "persisted_rows_only"


class PublicationLineageSection(BaseModel):
    """Grouped provenance for canon snapshot (Pass G)."""

    source_staging_snapshot_id: str
    parent_publication_snapshot_id: str | None = None
    identity_id: str | None = None
    thread_id: str | None = None
    graph_run_id: str | None = None


class PublicationSnapshotDetailResponse(BaseModel):
    """Immutable persisted publication (canon) — no runtime reconstruction."""

    publication_snapshot_id: str
    source_staging_snapshot_id: str
    thread_id: str | None = None
    graph_run_id: str | None = None
    identity_id: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    visibility: str
    published_by: str | None = None
    parent_publication_snapshot_id: str | None = None
    published_at: str
    publication_lineage: PublicationLineageSection = Field(
        description="Mirrors key lineage fields for scanning (Pass G).",
    )


def _resolve_start_event_input(body: StartRunBody) -> tuple[dict[str, Any], str | None]:
    if body.scenario_preset == SEEDED_LOCAL_SCENARIO_PRESET:
        return dict(SEEDED_LOCAL_EVENT_INPUT), SEEDED_LOCAL_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_SCENARIO_PRESET:
        return dict(SEEDED_GALLERY_STRIP_EVENT_INPUT), SEEDED_GALLERY_STRIP_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET:
        return (
            build_seeded_gallery_strip_varied_v1_event_input(),
            SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
        )
    return dict(body.event_input), None


def _scenario_tag_from_snapshot(snap: dict[str, Any] | None) -> str | None:
    return scenario_tag_from_run_state(snap)


def _run_event_input_from_snapshot(snap: dict[str, Any] | None) -> dict[str, Any] | None:
    if not snap:
        return None
    ev = snap.get("event_input")
    return ev if isinstance(ev, dict) else None


def _outputs_substantive(
    bs: BuildSpecRecord | None,
    ev: EvaluationReportRecord | None,
    snap: dict[str, Any] | None,
) -> bool:
    tag = _scenario_tag_from_snapshot(snap)
    if tag in (
        SEEDED_SCENARIO_TAG,
        SEEDED_GALLERY_STRIP_SCENARIO_TAG,
        SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    ):
        return True
    hint = _spec_title_hint(bs.spec_json) if bs else None
    low = (hint or "").strip().lower()
    if low and low not in ("no-op", "noop", "none"):
        return True
    summ = (ev.summary or "").strip() if ev else ""
    if len(summ) > 120:
        return True
    return False


def _spec_title_hint(spec_json: dict[str, Any]) -> str | None:
    t = spec_json.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()[:200]
    ty = spec_json.get("type")
    if isinstance(ty, str) and ty.strip():
        return ty.strip()[:200]
    return None


def _spec_summary(rec: BuildSpecRecord) -> BuildSpecSummary:
    return BuildSpecSummary(
        build_spec_id=str(rec.build_spec_id),
        status=rec.status,
        title_hint=_spec_title_hint(rec.spec_json),
    )


def _candidate_summary(rec: BuildCandidateRecord) -> BuildCandidateSummary:
    return BuildCandidateSummary(
        build_candidate_id=str(rec.build_candidate_id),
        candidate_kind=rec.candidate_kind,
        status=rec.status,
    )


def _eval_summary(rec: EvaluationReportRecord) -> EvaluationSummary:
    return EvaluationSummary(
        evaluation_report_id=str(rec.evaluation_report_id),
        status=rec.status,
        summary=rec.summary,
    )


class InvokeRoleBody(BaseModel):
    """Passthrough to ``RoleProvider.invoke_role`` — dev / integration testing."""

    role_type: Literal["planner", "generator", "evaluator"]
    payload: dict[str, Any]


def _kiloclaw_configured(settings: Settings, eff: str) -> bool:
    if eff == "stub":
        return True
    if eff == "http":
        return bool((settings.kiloclaw_api_key or "").strip())
    if eff == "openclaw_cli":
        return bool((settings.kiloclaw_openclaw_executable or "").strip())
    return False


def _run_graph_background(
    *,
    thread_id: str,
    graph_run_id: str,
    identity_id: str | None,
    trigger_type: str,
    event_input: dict[str, Any],
) -> None:
    """Runs LangGraph after HTTP response; same-process thread pool (local dev)."""
    settings = get_settings()
    repo = get_repository(settings)
    invoker = DefaultRoleInvoker(settings=settings)
    gid_u = UUID(graph_run_id)
    tid_u = UUID(thread_id)
    t_bg = time.perf_counter()
    _log.info(
        "run_start_background graph_run_id=%s stage=background_graph_enter elapsed_ms=0.0",
        graph_run_id,
    )
    if settings.orchestrator_smoke_planner_only:
        _log.warning(
            "run_start_background graph_run_id=%s mode=ORCHESTRATOR_SMOKE_PLANNER_ONLY (single planner HTTP only)",
            graph_run_id,
        )
        try:
            run_smoke_planner_only(
                repo=repo,
                invoker=invoker,
                settings=settings,
                thread_id=thread_id,
                graph_run_id=graph_run_id,
                event_input=event_input,
            )
        except Exception:
            _log.exception(
                "smoke_planner_only failed graph_run_id=%s",
                graph_run_id,
            )
            try:
                repo.update_graph_run_status(
                    gid_u,
                    "failed",
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                _log.exception(
                    "Could not mark graph_run failed after smoke error (graph_run_id=%s)",
                    graph_run_id,
                )
        else:
            _log.info(
                "run_start_background graph_run_id=%s stage=background_graph_exit_ok elapsed_ms=%.1f",
                graph_run_id,
                (time.perf_counter() - t_bg) * 1000,
            )
        return
    try:
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": thread_id,
                "graph_run_id": graph_run_id,
                "identity_id": identity_id,
                "trigger_type": trigger_type,
                "event_input": event_input,
            },
        )
    except RoleInvocationFailed as e:
        _log.exception(
            "Background graph run RoleInvocationFailed stage=%s graph_run_id=%s",
            e.phase,
            graph_run_id,
        )
    except StagingIntegrityFailed as e:
        _log.exception(
            "Background graph run StagingIntegrityFailed stage=staging_reason=%s graph_run_id=%s",
            e.reason,
            graph_run_id,
        )
    except Exception as e:
        _log.exception(
            "Background graph run failed stage=unhandled graph_run_id=%s exc=%s",
            graph_run_id,
            type(e).__name__,
        )
        try:
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
            repo.save_checkpoint(
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": "graph_error",
                            "error_message": f"{type(e).__name__}: {e}",
                        }
                    },
                    context_compaction_json=None,
                )
            )
        except Exception:
            _log.exception(
                "Could not persist failed status / interrupt checkpoint (graph_run_id=%s)",
                graph_run_id,
            )
    else:
        _log.info(
            "run_start_background graph_run_id=%s stage=background_graph_exit_ok elapsed_ms=%.1f",
            graph_run_id,
            (time.perf_counter() - t_bg) * 1000,
        )


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Liveness + deployment hints. Never returns secret values — only booleans / non-sensitive config."""
    eff = settings.effective_kiloclaw_transport()
    key_set = bool((settings.kiloclaw_api_key or "").strip())
    supabase_ok = bool((settings.supabase_url or "").strip()) and bool(
        (settings.supabase_service_role_key or "").strip()
    )
    persist_ok = persisted_graph_runs_available(settings)
    kc_ok = _kiloclaw_configured(settings, eff)
    return {
        "status": "ok",
        "service": "kmbl-orchestrator",
        "listen": {
            "host": settings.orchestrator_host,
            "port": settings.orchestrator_port,
        },
        "kiloclaw_transport": settings.kiloclaw_transport,
        "kiloclaw_transport_effective": eff,
        "kiloclaw_base_url": settings.kiloclaw_base_url,
        "kiloclaw_invoke_path": settings.kiloclaw_invoke_path,
        "kiloclaw_chat_completions_user": settings.kiloclaw_chat_completions_user,
        "kiloclaw_planner_config_key": settings.kiloclaw_planner_config_key,
        "kiloclaw_generator_config_key": settings.kiloclaw_generator_config_key,
        "kiloclaw_evaluator_config_key": settings.kiloclaw_evaluator_config_key,
        "env": {
            "supabase_url_configured": bool((settings.supabase_url or "").strip()),
            "supabase_service_role_key_configured": bool(
                (settings.supabase_service_role_key or "").strip()
            ),
            "kiloclaw_api_key_configured": key_set,
            "http_transport_ready": eff == "http" and key_set,
        },
        "readiness": {
            "supabase_configured": supabase_ok,
            "kiloclaw_configured": kc_ok,
            "persisted_runs_available": persist_ok,
            "ready_for_full_local_run": persist_ok and kc_ok,
            "note": (
                "Config-only flags: they do not probe live Supabase REST or KiloClaw HTTP. "
                "A true ready_for_full_local_run still requires valid keys and network reachability."
            ),
        },
        "repository_backend": repository_backend(settings),
        "orchestrator_running_stale_after_seconds": settings.orchestrator_running_stale_after_seconds,
        "orchestrator_smoke_planner_only": settings.orchestrator_smoke_planner_only,
        "kiloclaw_http_connect_timeout_sec": settings.kiloclaw_http_connect_timeout_sec,
        "kiloclaw_http_read_timeout_sec": settings.kiloclaw_http_read_timeout_sec,
    }


@app.post(
    "/orchestrator/runs/start",
    response_model=StartRunResponse,
    summary="Start a graph run",
    description=(
        "Use an **empty JSON object `{}`** for a normal fresh run. "
        "Returns immediately with `status: running` while the graph executes in-process; "
        "poll **GET /orchestrator/runs/{graph_run_id}** for `completed` / `failed` and artifacts. "
        "Swagger may list UUID fields as type `string` in the schema; that is normal. "
        "Do not paste placeholder values like `\"string\"` for UUID fields — that causes 422 or runtime errors."
    ),
)
async def start_run(
    background_tasks: BackgroundTasks,
    body: Annotated[
        StartRunBody,
        Body(
            openapi_examples={
                "fresh_run": {
                    "summary": "Fresh run (recommended)",
                    "description": "Empty body. New thread_id and graph_run_id are created.",
                    "value": {},
                },
                "explicit_defaults": {
                    "summary": "Explicit trigger only",
                    "value": {"trigger_type": "prompt", "event_input": {}},
                },
                "with_uuids": {
                    "summary": "Resume / tie to identity (real UUIDs only)",
                    "description": "Replace with real UUIDs from your database — not the word 'string'.",
                    "value": {
                        "identity_id": "00000000-0000-0000-0000-000000000001",
                        "thread_id": "00000000-0000-0000-0000-000000000002",
                        "trigger_type": "prompt",
                        "event_input": {},
                    },
                },
                "seeded_local_v1": {
                    "summary": "Seeded local scenario (inspectable planner/gen/eval)",
                    "description": "Replaces event_input with the canonical local seed; same as control-plane “Seeded” button.",
                    "value": {"scenario_preset": "seeded_local_v1"},
                },
                "seeded_gallery_strip_v1": {
                    "summary": "Gallery strip UI experiment (bounded updated_state)",
                    "description": (
                        "Replaces event_input with the gallery-strip seed — generator should emit "
                        "updated_state.ui_gallery_strip_v1 only."
                    ),
                    "value": {"scenario_preset": "seeded_gallery_strip_v1"},
                },
                "seeded_gallery_strip_varied_v1": {
                    "summary": "Gallery strip — bounded non-deterministic variation (local dev)",
                    "description": (
                        "Replaces event_input with a gallery-strip scenario that includes explicit "
                        "variation (run_nonce, variants). Deterministic smoke preset unchanged."
                    ),
                    "value": {"scenario_preset": "seeded_gallery_strip_varied_v1"},
                },
            },
        ),
    ],
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StartRunResponse:
    """Create thread + graph_run rows, enqueue LangGraph (persist before graph)."""
    t_req = time.perf_counter()
    _log.info("run_start stage=request_received elapsed_ms=0.0")
    effective_event_input, preset_applied = _resolve_start_event_input(body)
    _log.info(
        "run_start stage=event_input_resolved elapsed_ms=%.1f",
        (time.perf_counter() - t_req) * 1000,
    )
    timeout_sec = float(settings.orchestrator_run_start_sync_timeout_sec or 0.0)
    persist_kw: dict[str, Any] = {
        "repo": repo,
        "thread_id": str(body.thread_id) if body.thread_id is not None else None,
        "graph_run_id": None,
        "identity_id": str(body.identity_id) if body.identity_id is not None else None,
        "trigger_type": body.trigger_type,
        "event_input": effective_event_input,
    }
    try:
        if timeout_sec > 0:
            tid, gid = await asyncio.wait_for(
                asyncio.to_thread(persist_graph_run_start, **persist_kw),
                timeout=timeout_sec,
            )
        else:
            tid, gid = await asyncio.to_thread(persist_graph_run_start, **persist_kw)
    except asyncio.TimeoutError:
        _log.error(
            "run_start stage=persist_graph_run_start TIMEOUT after %.1fs (limit=%s)",
            timeout_sec,
            timeout_sec,
        )
        raise HTTPException(
            status_code=504,
            detail={
                "error_kind": "orchestrator_sync_timeout",
                "step": "persist_graph_run_start",
                "timeout_sec": timeout_sec,
                "message": (
                    "Persisting thread + graph_run exceeded ORCHESTRATOR_RUN_START_SYNC_TIMEOUT_SEC. "
                    "Increase the limit or fix slow Supabase / network I/O."
                ),
            },
        ) from None
    except Exception as e:
        _log.exception("persist_graph_run_start failed")
        raise HTTPException(
            status_code=500,
            detail={
                "error_kind": "persistence_error",
                "step": "persist_graph_run_start",
                "exception": type(e).__name__,
                "message": str(e),
            },
        ) from e

    _log.info(
        "run_start stage=graph_run_persisted thread_id=%s graph_run_id=%s elapsed_ms=%.1f",
        tid,
        gid,
        (time.perf_counter() - t_req) * 1000,
    )
    background_tasks.add_task(
        _run_graph_background,
        thread_id=tid,
        graph_run_id=gid,
        identity_id=str(body.identity_id) if body.identity_id is not None else None,
        trigger_type=body.trigger_type,
        event_input=effective_event_input,
    )
    _log.info(
        "run_start stage=response_returning thread_id=%s graph_run_id=%s total_elapsed_ms=%.1f",
        tid,
        gid,
        (time.perf_counter() - t_req) * 1000,
    )
    return StartRunResponse(
        graph_run_id=gid,
        thread_id=tid,
        scenario_preset=preset_applied,
        effective_event_input=effective_event_input,
    )


def _optional_query_str(value: str | None) -> str | None:
    if value is None:
        return None
    t = value.strip()
    return t if t else None


@app.get("/orchestrator/runs", response_model=GraphRunListResponse)
def list_graph_runs_endpoint(
    status: str | None = None,
    trigger_type: str | None = None,
    identity_id: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
) -> GraphRunListResponse:
    """
    Pass I: compact index of recent graph runs (persisted rows only).

    Does not reconcile stale ``running`` rows or return checkpoint snapshots — use
    **GET /orchestrator/runs/{id}** or **/detail** for per-run views.
    """
    lim = max(1, min(limit, 200))
    st = _optional_query_str(status)
    tt = _optional_query_str(trigger_type)
    id_uuid: UUID | None = None
    id_raw = _optional_query_str(identity_id)
    if id_raw is not None:
        try:
            id_uuid = UUID(id_raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e

    runs = repo.list_graph_runs(
        status=st,
        trigger_type=tt,
        identity_id=id_uuid,
        limit=lim,
    )
    raw = build_graph_run_list_read_model(repo, runs)
    return GraphRunListResponse(
        runs=[GraphRunListItem(**x) for x in raw],
        count=len(raw),
    )


@app.get(
    "/orchestrator/operator-summary",
    response_model=OperatorHomeSummaryResponse,
)
def operator_home_summary(
    repo: Repository = Depends(get_repo),
) -> OperatorHomeSummaryResponse:
    """
    Pass O — compact persisted counts for the control-plane home page.

    Uses bounded windows over recent runs and staging rows — not full-table analytics.
    """
    raw = build_operator_home_summary(repo)
    return OperatorHomeSummaryResponse(**raw)


@app.get("/orchestrator/runs/{graph_run_id}", response_model=RunStatusResponse)
def run_status(
    graph_run_id: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RunStatusResponse:
    try:
        gid = UUID(graph_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid graph_run_id") from e
    gr = repo.get_graph_run(gid)
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    reconcile_stale_running_graph_run(repo, settings, gid)
    gr = repo.get_graph_run(gid)
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    snap = repo.get_run_snapshot(gid)
    iteration = None
    decision = None
    if snap:
        iteration = snap.get("iteration_index")
        if isinstance(iteration, (float, int)):
            iteration = int(iteration)
        decision = snap.get("decision")
        if decision is not None and not isinstance(decision, str):
            decision = str(decision)

    bs = repo.get_latest_build_spec_for_graph_run(gid)
    bc = repo.get_latest_build_candidate_for_graph_run(gid)
    ev = repo.get_latest_evaluation_report_for_graph_run(gid)

    fv = build_run_failure_view(repo, gid, status=gr.status)
    timeline_raw = repo.list_graph_run_events(gid, limit=120)
    timeline_events = [
        RunTimelineEventSummary(
            event_type=e.event_type,
            payload_json=dict(e.payload_json),
            created_at=e.created_at,
        )
        for e in timeline_raw
    ]

    return RunStatusResponse(
        graph_run_id=str(gr.graph_run_id),
        thread_id=str(gr.thread_id),
        status=gr.status,
        failure_phase=fv["failure_phase"],
        failure=fv["failure"],
        error_kind=fv["error_kind"],
        error_message=fv["error_message"],
        iteration_index=iteration,
        decision=decision,
        build_spec=_spec_summary(bs) if bs else None,
        build_candidate=_candidate_summary(bc) if bc else None,
        evaluation=_eval_summary(ev) if ev else None,
        snapshot=sanitize_checkpoint_state_for_api(snap),
        scenario_tag=_scenario_tag_from_snapshot(snap),
        run_event_input=_run_event_input_from_snapshot(snap),
        outputs_substantive=_outputs_substantive(bs, ev, snap),
        timeline_events=timeline_events,
    )


@app.get("/orchestrator/runs/{graph_run_id}/detail", response_model=GraphRunDetailResponse)
def graph_run_detail(
    graph_run_id: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> GraphRunDetailResponse:
    """
    Pass H: compact operator read model for one graph run (persisted rows only).

    Poll **GET /orchestrator/runs/{id}** for full ``RunStatusResponse`` including snapshot;
    this endpoint avoids large payloads and focuses on lineage-friendly summaries.
    """
    try:
        gid = UUID(graph_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid graph_run_id") from e
    gr = repo.get_graph_run(gid)
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    reconcile_stale_running_graph_run(repo, settings, gid)
    gr = repo.get_graph_run(gid)
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")

    thread = repo.get_thread(gr.thread_id)
    invocations = repo.list_role_invocations_for_graph_run(gid)
    staging_rows = repo.list_staging_snapshots_for_graph_run(gid, limit=20)
    publications = repo.list_publications_for_graph_run(gid, limit=20)
    events = repo.list_graph_run_events(gid, limit=500)
    latest_cp = repo.get_latest_checkpoint_for_graph_run(gid)
    has_interrupt = repo.get_latest_interrupt_orchestrator_error(gid) is not None

    bs = repo.get_latest_build_spec_for_graph_run(gid)
    bc = repo.get_latest_build_candidate_for_graph_run(gid)
    ev = repo.get_latest_evaluation_report_for_graph_run(gid)

    raw = build_graph_run_detail_read_model(
        thread=thread,
        gr=gr,
        invocations=invocations,
        staging_rows=staging_rows,
        publications=publications,
        events=events,
        latest_checkpoint=latest_cp,
        has_interrupt_signal=has_interrupt,
        bs=bs,
        bc=bc,
        ev=ev,
    )
    eligible, resume_expl = compute_resume_eligibility(repo, gid)
    snap_detail = repo.get_run_snapshot(gid)
    scen_tag = scenario_tag_from_run_state(snap_detail)
    scen_badge = scenario_badge_from_tag(scen_tag)
    return GraphRunDetailResponse(
        summary=GraphRunSummaryBlock(**raw["summary"]),
        operator_actions=[
            OperatorActionItem(**x) for x in raw.get("operator_actions", [])
        ],
        role_invocations=[RoleInvocationDetailItem(**x) for x in raw["role_invocations"]],
        associated_outputs=AssociatedOutputsBlock(**raw["associated_outputs"]),
        timeline=[RunTimelineItem(**x) for x in raw["timeline"]],
        resume_eligible=eligible,
        resume_operator_explanation=resume_expl,
        retry_eligible=False,
        scenario_tag=scen_tag,
        scenario_badge=scen_badge,
    )


class ResumeRunResponse(BaseModel):
    """Pass K — operator resumed graph execution for this graph_run_id."""

    ok: bool = True
    graph_run_id: str
    status: str = "running"


@app.post(
    "/orchestrator/runs/{graph_run_id}/resume",
    response_model=ResumeRunResponse,
    status_code=200,
)
def resume_graph_run(
    graph_run_id: str,
    background_tasks: BackgroundTasks,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ResumeRunResponse:
    """Re-queue LangGraph for this run id when paused or stale-failed (persisted rules only)."""
    try:
        gid = UUID(graph_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid graph_run_id") from e
    gr0 = repo.get_graph_run(gid)
    if gr0 is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    reconcile_stale_running_graph_run(repo, settings, gid)
    gr = repo.get_graph_run(gid)
    if gr is None:
        raise HTTPException(status_code=404, detail="graph_run not found")

    eligible, reason = compute_resume_eligibility(repo, gid)
    if not eligible:
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "resume_not_eligible",
                "message": reason or "not eligible",
            },
        )

    repo.mark_graph_run_resuming(gid)
    append_graph_run_event(
        repo,
        gid,
        RunEventType.GRAPH_RUN_RESUMED,
        {"basis": "operator_resume"},
    )
    th = repo.get_thread(gr.thread_id)
    identity_s = str(th.identity_id) if th and th.identity_id else None
    event_input = event_input_for_resume(repo, gid)
    background_tasks.add_task(
        _run_graph_background,
        thread_id=str(gr.thread_id),
        graph_run_id=str(gid),
        identity_id=identity_s,
        trigger_type="resume",
        event_input=event_input,
    )
    return ResumeRunResponse(graph_run_id=str(gid), status="running")


@app.get("/orchestrator/staging", response_model=StagingListResponse)
def list_staging_snapshots(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    status: str | None = Query(
        None,
        description="Filter by staging_snapshot.status (e.g. review_ready).",
    ),
    identity_id: str | None = Query(
        None,
        description="Filter by identity UUID.",
    ),
) -> StagingListResponse:
    """Query persisted staging rows for operator review — no runtime reconstruction."""
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    rows = repo.list_staging_snapshots(limit=limit, status=status, identity_id=id_u)
    snapshots = [staging_snapshot_list_item(r) for r in rows]
    return StagingListResponse(snapshots=snapshots, count=len(snapshots))


@app.get("/orchestrator/proposals")
def list_proposals(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    identity_id: str | None = Query(
        None,
        description="Filter by identity UUID.",
    ),
    review_action_state: str | None = Query(
        None,
        description="Filter by derived review action state (Pass N).",
    ),
    staging_status: str | None = Query(
        None,
        description="Filter by staging_snapshot.status.",
    ),
    has_publication: str | None = Query(
        None,
        description="true = at least one publication row; false = none.",
    ),
    sort: str | None = Query(
        None,
        description="default = Pass J tiers; newest / oldest = by created_at only.",
    ),
) -> dict[str, Any]:
    """
    Review queue read model from persisted ``staging_snapshot`` rows (Pass J / N).

    Includes multiple staging statuses; each row gets ``review_action_state`` from stored
    status plus ``publication_snapshot`` counts — not a workflow engine.
    """
    id_u: UUID | None = None
    id_raw = proposals_normalize_blank(identity_id)
    if id_raw is not None:
        try:
            id_u = UUID(id_raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e

    staging_f = proposals_normalize_blank(staging_status)
    try:
        ras_f = validate_review_action_state(review_action_state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    has_pub_f = proposals_parse_has_publication(has_publication)
    sort_mode = proposals_parse_sort_mode(sort)
    wide = proposals_use_wide_pool(
        review_action_state=ras_f,
        has_publication=has_pub_f,
        sort_mode=sort_mode,
    )
    fetch_n = proposals_fetch_limit(limit=limit, wide=wide)

    rows = repo.list_staging_snapshots(
        limit=fetch_n,
        status=staging_f,
        identity_id=id_u,
    )
    sids = [r.staging_snapshot_id for r in rows]
    pub_counts = repo.publication_counts_for_staging_snapshot_ids(sids)
    proposals: list[dict[str, Any]] = []
    for r in rows:
        d = proposal_read_model(r)
        pc = pub_counts.get(r.staging_snapshot_id, 0)
        action, reason = derive_review_action_state(r, pc)
        d["linked_publication_count"] = pc
        d["review_action_state"] = action
        d["review_action_reason"] = reason
        proposals.append(d)

    proposals = filter_proposals_queue(
        proposals,
        review_action_state=ras_f,
        has_publication=has_pub_f,
    )
    sort_proposals_in_place(proposals, sort_mode=sort_mode)
    proposals = proposals[:limit]

    return {
        "proposals": proposals,
        "count": len(proposals),
        "basis": "persisted_rows_only",
    }


def _publication_list_item(rec: PublicationSnapshotRecord) -> PublicationSnapshotListItem:
    return PublicationSnapshotListItem(
        publication_snapshot_id=str(rec.publication_snapshot_id),
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        visibility=rec.visibility,
        published_at=rec.published_at,
        published_by=rec.published_by,
    )


def _publication_detail(rec: PublicationSnapshotRecord) -> PublicationSnapshotDetailResponse:
    lineage = PublicationLineageSection(
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        parent_publication_snapshot_id=str(rec.parent_publication_snapshot_id)
        if rec.parent_publication_snapshot_id
        else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        thread_id=str(rec.thread_id) if rec.thread_id else None,
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
    )
    return PublicationSnapshotDetailResponse(
        publication_snapshot_id=str(rec.publication_snapshot_id),
        source_staging_snapshot_id=str(rec.source_staging_snapshot_id),
        thread_id=str(rec.thread_id) if rec.thread_id else None,
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        payload_json=dict(rec.payload_json),
        visibility=rec.visibility,
        published_by=rec.published_by,
        parent_publication_snapshot_id=str(rec.parent_publication_snapshot_id)
        if rec.parent_publication_snapshot_id
        else None,
        published_at=rec.published_at,
        publication_lineage=lineage,
    )


def _staging_mutation_response(rec: StagingSnapshotRecord) -> StagingMutationResponse:
    return StagingMutationResponse(
        staging_snapshot_id=str(rec.staging_snapshot_id),
        thread_id=str(rec.thread_id),
        status=rec.status,
        created_at=rec.created_at,
        preview_url=rec.preview_url,
        approved_by=rec.approved_by,
        approved_at=rec.approved_at,
        rejected_by=rec.rejected_by,
        rejected_at=rec.rejected_at,
        rejection_reason=rec.rejection_reason,
        review_readiness=review_readiness_for_staging_record(rec),
    )


@app.post(
    "/orchestrator/staging/{staging_snapshot_id}/approve",
    response_model=StagingMutationResponse,
)
def approve_staging_snapshot(
    staging_snapshot_id: str,
    body: ApproveStagingBody = Body(default=ApproveStagingBody()),
    repo: Repository = Depends(get_repo),
) -> StagingMutationResponse:
    """Transition ``review_ready`` → ``approved`` (explicit human approval; not a workflow engine)."""
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if rec.status == "approved":
        return _staging_mutation_response(rec)
    if rec.status == "rejected":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "approve_ineligible",
                "reason": "staging_rejected",
                "message": "cannot approve a rejected staging snapshot — create a new staging snapshot",
                "staging_status": rec.status,
            },
        )
    if rec.status != "review_ready":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "approve_ineligible",
                "reason": "staging_not_review_ready",
                "message": f"cannot approve staging in status {rec.status!r}",
                "staging_status": rec.status,
            },
        )
    updated = repo.update_staging_snapshot_status(
        sid, "approved", approved_by=body.approved_by
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_APPROVED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "approved_by": body.approved_by,
            },
        )
    return _staging_mutation_response(updated)


@app.post(
    "/orchestrator/staging/{staging_snapshot_id}/reject",
    response_model=StagingMutationResponse,
)
def reject_staging_snapshot(
    staging_snapshot_id: str,
    body: RejectStagingBody = Body(default=RejectStagingBody()),
    repo: Repository = Depends(get_repo),
) -> StagingMutationResponse:
    """
    Mark staging as ``rejected`` (terminal for this snapshot).

    Allowed from ``review_ready`` or ``approved`` when no publication exists for this staging id.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if rec.status == "rejected":
        return _staging_mutation_response(rec)
    pubs = repo.list_publications_for_staging(sid)
    if pubs:
        latest = pubs[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "reject_blocked_canon_exists",
                "message": "cannot reject — a publication snapshot already exists for this staging id",
                "staging_snapshot_id": str(sid),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    if rec.status not in ("review_ready", "approved"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "reject_ineligible",
                "message": f"cannot reject staging in status {rec.status!r}",
                "staging_status": rec.status,
            },
        )
    updated = repo.update_staging_snapshot_status(
        sid,
        "rejected",
        rejected_by=body.rejected_by,
        rejection_reason=body.rejection_reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_REJECTED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "rejected_by": body.rejected_by,
                "rejection_reason": body.rejection_reason,
            },
        )
    return _staging_mutation_response(updated)


@app.post(
    "/orchestrator/staging/{staging_snapshot_id}/unapprove",
    response_model=StagingMutationResponse,
)
def unapprove_staging_snapshot(
    staging_snapshot_id: str,
    body: UnapproveStagingBody = Body(default=UnapproveStagingBody()),
    repo: Repository = Depends(get_repo),
) -> StagingMutationResponse:
    """
    Transition ``approved`` → ``review_ready`` (withdraw approval).

    Only when no publication exists for this staging id.
    """
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    pubs = repo.list_publications_for_staging(sid)
    if pubs:
        latest = pubs[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "unapprove_blocked_canon_exists",
                "message": "cannot withdraw approval — a publication snapshot already exists",
                "staging_snapshot_id": str(sid),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    if rec.status != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "unapprove_ineligible",
                "message": f"unapprove only applies to approved staging (current status {rec.status!r})",
                "staging_status": rec.status,
            },
        )
    updated = repo.update_staging_snapshot_status(sid, "review_ready")
    if updated is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    if updated.graph_run_id is not None:
        append_graph_run_event(
            repo,
            updated.graph_run_id,
            RunEventType.STAGING_SNAPSHOT_UNAPPROVED,
            {
                "staging_snapshot_id": str(updated.staging_snapshot_id),
                "thread_id": str(updated.thread_id),
                "graph_run_id": str(updated.graph_run_id),
                "unapproved_by": body.unapproved_by,
            },
        )
    return _staging_mutation_response(updated)


@app.get(
    "/orchestrator/publication/current",
    response_model=PublicationSnapshotDetailResponse,
)
def get_current_publication(
    repo: Repository = Depends(get_repo),
    identity_id: str | None = Query(
        None,
        description="When set, latest publication for this identity; else latest overall.",
    ),
) -> PublicationSnapshotDetailResponse:
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    cur = repo.get_latest_publication_snapshot(identity_id=id_u)
    if cur is None:
        raise HTTPException(status_code=404, detail="no publication_snapshot found")
    return _publication_detail(cur)


@app.get("/orchestrator/publication", response_model=PublicationListResponse)
def list_publications(
    repo: Repository = Depends(get_repo),
    limit: int = Query(20, ge=1, le=200),
    identity_id: str | None = Query(None, description="Filter by identity UUID."),
    visibility: str | None = Query(
        None,
        description="Filter by visibility (private or public).",
    ),
) -> PublicationListResponse:
    id_u: UUID | None = None
    if identity_id is not None and identity_id.strip() != "":
        try:
            id_u = UUID(identity_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid identity_id") from e
    vis: str | None = None
    if visibility is not None and visibility.strip() != "":
        v = visibility.strip().lower()
        if v not in ("private", "public"):
            raise HTTPException(status_code=400, detail="invalid visibility")
        vis = v
    rows = repo.list_publication_snapshots(
        limit=limit, identity_id=id_u, visibility=vis
    )
    items = [_publication_list_item(r) for r in rows]
    return PublicationListResponse(publications=items, count=len(items))


@app.post(
    "/orchestrator/publication",
    response_model=CreatePublicationResponse,
)
def create_publication(
    body: Annotated[CreatePublicationBody, Body()],
    repo: Repository = Depends(get_repo),
) -> CreatePublicationResponse:
    """Create immutable ``publication_snapshot`` from an **approved** staging row only."""
    staging = repo.get_staging_snapshot(body.staging_snapshot_id)
    if staging is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    existing = repo.list_publications_for_staging(staging.staging_snapshot_id)
    if existing:
        latest = existing[0]
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "publication_already_exists_for_staging",
                "message": "a publication snapshot already exists for this staging snapshot",
                "staging_snapshot_id": str(staging.staging_snapshot_id),
                "publication_snapshot_id": str(latest.publication_snapshot_id),
            },
        )
    try:
        validate_publication_eligibility(staging)
    except PublicationIneligible as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "publication_ineligible",
                "reason": e.reason,
                "message": e.message,
            },
        ) from e

    parent = repo.get_latest_publication_snapshot(identity_id=staging.identity_id)
    pub_id = uuid4()
    published_at = datetime.now(timezone.utc).isoformat()
    snap = PublicationSnapshotRecord(
        publication_snapshot_id=pub_id,
        source_staging_snapshot_id=staging.staging_snapshot_id,
        thread_id=staging.thread_id,
        graph_run_id=staging.graph_run_id,
        identity_id=staging.identity_id,
        payload_json=copy.deepcopy(staging.snapshot_payload_json),
        visibility=body.visibility,
        published_by=body.published_by,
        parent_publication_snapshot_id=parent.publication_snapshot_id if parent else None,
        published_at=published_at,
    )
    repo.save_publication_snapshot(snap)
    if staging.graph_run_id is not None:
        append_graph_run_event(
            repo,
            staging.graph_run_id,
            RunEventType.PUBLICATION_SNAPSHOT_CREATED,
            {
                "publication_snapshot_id": str(pub_id),
                "source_staging_snapshot_id": str(staging.staging_snapshot_id),
                "identity_id": str(staging.identity_id) if staging.identity_id else None,
                "visibility": body.visibility,
                "published_by": body.published_by,
            },
        )
    return CreatePublicationResponse(
        publication_snapshot_id=str(pub_id),
        source_staging_snapshot_id=str(staging.staging_snapshot_id),
        identity_id=str(staging.identity_id) if staging.identity_id else None,
        visibility=body.visibility,
        published_at=published_at,
        published_by=body.published_by,
    )


@app.get(
    "/orchestrator/publication/{publication_snapshot_id}",
    response_model=PublicationSnapshotDetailResponse,
)
def get_publication_snapshot(
    publication_snapshot_id: str,
    repo: Repository = Depends(get_repo),
) -> PublicationSnapshotDetailResponse:
    try:
        pid = UUID(publication_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid publication_snapshot_id") from e
    rec = repo.get_publication_snapshot(pid)
    if rec is None:
        raise HTTPException(status_code=404, detail="publication_snapshot not found")
    return _publication_detail(rec)


@app.get(
    "/orchestrator/staging/{staging_snapshot_id}",
    response_model=StagingSnapshotDetailResponse,
)
def get_staging_snapshot(
    staging_snapshot_id: str,
    repo: Repository = Depends(get_repo),
) -> StagingSnapshotDetailResponse:
    """Return the persisted ``staging_snapshot`` row only — no runtime reconstruction."""
    try:
        sid = UUID(staging_snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid staging_snapshot_id") from e
    rec = repo.get_staging_snapshot(sid)
    if rec is None:
        raise HTTPException(status_code=404, detail="staging_snapshot not found")
    pubs = repo.list_publications_for_staging(sid)
    p = dict(rec.snapshot_payload_json)
    timeline_raw = staging_lifecycle_timeline(rec, pubs)
    linked_raw = linked_publications_read_model(pubs)
    lineage_raw = staging_lineage_read_model(rec, p)
    eval_raw = evaluation_summary_section_from_payload(p)
    explain = review_readiness_explanation_for_staging(rec, p)
    gv = gallery_strip_visibility_from_staging_payload(p)
    ck = "gallery_strip" if gv.get("has_gallery_strip") else None
    return StagingSnapshotDetailResponse(
        staging_snapshot_id=str(rec.staging_snapshot_id),
        thread_id=str(rec.thread_id),
        build_candidate_id=str(rec.build_candidate_id),
        graph_run_id=str(rec.graph_run_id) if rec.graph_run_id else None,
        identity_id=str(rec.identity_id) if rec.identity_id else None,
        snapshot_payload_json=p,
        preview_url=rec.preview_url,
        status=rec.status,
        created_at=rec.created_at,
        approved_by=rec.approved_by,
        approved_at=rec.approved_at,
        rejected_by=rec.rejected_by,
        rejected_at=rec.rejected_at,
        rejection_reason=rec.rejection_reason,
        evaluation_summary=evaluation_summary_from_payload(p),
        short_title=short_title_from_payload(p),
        identity_hint=identity_hint_from_uuid(rec.identity_id),
        review_readiness=review_readiness_for_staging_record(rec),
        review_readiness_explanation=explain,
        payload_version=payload_version_from_payload(p),
        lineage=StagingLineageSection(**lineage_raw),
        evaluation=StagingEvaluationDetail(**eval_raw),
        linked_publications=[LinkedPublicationItem(**x) for x in linked_raw],
        lifecycle_timeline=[LifecycleTimelineItem(**x) for x in timeline_raw],
        content_kind=ck,
        has_gallery_strip=bool(gv.get("has_gallery_strip")),
        gallery_strip_item_count=int(gv.get("gallery_strip_item_count") or 0),
        gallery_image_artifact_count=int(gv.get("gallery_image_artifact_count") or 0),
        gallery_items_with_artifact_key=int(gv.get("gallery_items_with_artifact_key") or 0),
    )


@app.post("/orchestrator/invoke-role")
def invoke_role(
    body: Annotated[
        InvokeRoleBody,
        Body(
            openapi_examples={
                "planner_smoke": {
                    "summary": "Planner smoke",
                    "value": {
                        "role_type": "planner",
                        "payload": {
                            "thread_id": "00000000-0000-0000-0000-000000000001",
                            "identity_context": {},
                            "memory_context": {},
                            "event_input": {"task": "smoke"},
                            "current_state_summary": {},
                        },
                    },
                },
                "generator_smoke": {
                    "summary": "Generator smoke (minimal)",
                    "value": {
                        "role_type": "generator",
                        "payload": {
                            "thread_id": "00000000-0000-0000-0000-000000000001",
                            "build_spec": {"title": "x", "steps": []},
                            "current_working_state": {},
                            "iteration_feedback": None,
                        },
                    },
                },
                "evaluator_smoke": {
                    "summary": "Evaluator smoke (minimal)",
                    "value": {
                        "role_type": "evaluator",
                        "payload": {
                            "thread_id": "00000000-0000-0000-0000-000000000001",
                            "build_candidate": {},
                            "success_criteria": [],
                            "evaluation_targets": [],
                            "iteration_hint": 0,
                        },
                    },
                },
            },
        ),
    ],
    invoker: DefaultRoleInvoker = Depends(get_invoker),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Internal dev hook — production path is the LangGraph nodes.

    TODO: Remove or protect when KiloClaw is only reachable from orchestrator graph.
    """
    # Minimal synthetic IDs for standalone calls
    gid = UUID(int=0)
    tid = UUID(int=1)
    key = {
        "planner": settings.kiloclaw_planner_config_key,
        "generator": settings.kiloclaw_generator_config_key,
        "evaluator": settings.kiloclaw_evaluator_config_key,
    }[body.role_type]
    _inv, raw = invoker.invoke(
        graph_run_id=gid,
        thread_id=tid,
        role_type=body.role_type,
        provider_config_key=key,
        input_payload=body.payload,
        iteration_index=0,
    )
    return {"output": raw}


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "kmbl_orchestrator.api.main:app",
        host=s.orchestrator_host,
        port=s.orchestrator_port,
        reload=s.orchestrator_reload,
    )


if __name__ == "__main__":
    run()
