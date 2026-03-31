"""FastAPI entrypoint — health + internal orchestrator routes (docs/12 §5)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from kmbl_orchestrator.api.middleware_api_key import optional_api_key_middleware
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunRecord,
)
from kmbl_orchestrator.persistence.factory import (
    get_repository,
    persisted_graph_runs_available,
    repository_backend,
)
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.runtime.graph_run_detail_read_model import (
    build_graph_run_detail_read_model,
)
from kmbl_orchestrator.runtime.scenario_visibility import (
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
from kmbl_orchestrator.runtime.session_staging_links import (
    build_session_staging_links_dict,
    merge_session_staging_into_event_input,
)
from kmbl_orchestrator.runtime.stale_run import reconcile_stale_running_graph_run
from kmbl_orchestrator.identity import (
    extract_identity_from_url,
    persist_identity_from_seed,
)
from kmbl_orchestrator.seeds import (
    IDENTITY_URL_STATIC_FRONTEND_PRESET,
    KILOCLAW_IMAGE_ONLY_TEST_EVENT_INPUT,
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET,
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_EVENT_INPUT,
    SEEDED_GALLERY_STRIP_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    SEEDED_LOCAL_EVENT_INPUT,
    SEEDED_LOCAL_SCENARIO_PRESET,
    SEEDED_SCENARIO_TAG,
    build_identity_url_static_frontend_event_input,
    build_seeded_gallery_strip_varied_v1_event_input,
)

app = FastAPI(title="KMBL Orchestrator", version="0.1.0")
app.middleware("http")(optional_api_key_middleware)
_log = logging.getLogger(__name__)

# Register extracted route modules
from kmbl_orchestrator.api.loops import router as _loops_router  # noqa: E402
from kmbl_orchestrator.api.routes_identity import router as _identity_router  # noqa: E402
from kmbl_orchestrator.api.routes_publication import router as _publication_router  # noqa: E402
from kmbl_orchestrator.api.routes_staging import router as _staging_router  # noqa: E402
from kmbl_orchestrator.api.routes_working_staging import router as _ws_router  # noqa: E402
app.include_router(_loops_router)
app.include_router(_identity_router)
app.include_router(_publication_router)
app.include_router(_staging_router)
app.include_router(_ws_router)


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


# Dependency callables — single source from deps, re-exported for test compatibility.
from kmbl_orchestrator.api.deps import get_invoker, get_repo  # noqa: F401, E402


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
    identity_url: str | None = Field(
        default=None,
        description=(
            "Website URL for the identity vertical. First run (no thread_id + identity_id): "
            "fetch URL, extract signals, create identity. Continuation: send the same URL with "
            "thread_id and identity_id from a prior run to reuse identity and thread (working staging)."
        ),
    )
    deep_crawl: bool = Field(
        default=True,
        description=(
            "When extracting identity from a URL, crawl additional pages (about, work, portfolio, "
            "etc.) to build richer identity signals. Enabled by default."
        ),
    )
    scenario_preset: (
        Literal[
            "identity_url_static_v1",
            "seeded_local_v1",
            "seeded_gallery_strip_v1",
            "seeded_gallery_strip_varied_v1",
            "kiloclaw_image_only_test_v1",
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "identity_url_static_v1: canonical vertical — requires identity_url field. "
            "When set to seeded_local_v1 or seeded_gallery_strip_v1, event_input is replaced "
            "with the canonical seeded scenario (deterministic tag in event_input.scenario). "
            "seeded_gallery_strip_varied_v1 replaces event_input with a non-deterministic "
            "bounded-variation gallery scenario (fresh run_nonce per start). "
            "kiloclaw_image_only_test_v1 requires gallery images via KiloClaw kmbl-image-gen routing "
            "(KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY). "
            "Ignores event_input for that run."
        ),
    )
    user_instructions: str | None = Field(
        default=None,
        description=(
            "Merged into event_input as user_instructions for planner/generator (e.g. autonomous loop chat)."
        ),
    )
    max_iterations: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=(
            "Generator↔evaluator loop bound. Omit to use KMBL_GRAPH_MAX_ITERATIONS_DEFAULT "
            "(orchestrator settings; default 10)."
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
    identity_id: str | None = Field(
        default=None,
        description="Identity used for this run (new extraction or continuation).",
    )
    session_staging: SessionStagingLinks | None = Field(
        default=None,
        description="Stable links to live working staging (also in event_input.kmbl_session_staging).",
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
    evaluator_iteration_index: int | None = Field(
        default=None,
        description=(
            "Graph iteration_index for this evaluator invocation when known "
            "(from role_invocation)."
        ),
    )
    alignment_score: float | None = Field(
        default=None,
        description="Orchestrator-computed identity alignment (0-1) when an identity brief was present.",
    )
    alignment_signals_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-criterion alignment breakdown (e.g. must_mention_hit_rate, source).",
    )


class RunTimelineEventSummary(BaseModel):
    event_type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SessionStagingLinks(BaseModel):
    """Stable per-run links to live working staging (same thread as this graph run)."""

    graph_run_id: str
    thread_id: str
    orchestrator_staging_preview_path: str
    orchestrator_working_staging_json_path: str
    control_plane_staging_preview_path: str
    control_plane_live_habitat_path: str
    note: str
    orchestrator_staging_preview_url: str | None = None
    orchestrator_working_staging_json_url: str | None = None


def _session_staging_model(settings: Settings, gr: GraphRunRecord) -> SessionStagingLinks:
    return SessionStagingLinks(
        **build_session_staging_links_dict(
            settings,
            graph_run_id=str(gr.graph_run_id),
            thread_id=str(gr.thread_id),
        )
    )


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
    evaluation_history: list[EvaluationSummary] = Field(
        default_factory=list,
        description=(
            "All evaluation_report rows for this graph run, oldest first (per-iteration view). "
            "``evaluation`` remains the latest row for backward compatibility."
        ),
    )
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
    session_staging: SessionStagingLinks | None = Field(
        default=None,
        description="Stable URLs to live working staging for this run (thread-scoped).",
    )


class GraphRunSummaryBlock(BaseModel):
    """Pass H: persisted run metadata for operator run detail."""

    graph_run_id: str
    thread_id: str
    identity_id: str | None = None
    graph_run_identity_id: str | None = Field(
        default=None,
        description="Denormalized identity on graph_run when set (may match thread.identity_id).",
    )
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
    routing_hints: dict[str, Any] | None = Field(
        default=None,
        description="Subset of persisted routing_metadata_json (generator invocations only).",
    )
    routing_fact_source: Literal["persisted", "none"] = "none"


class AssociatedOutputsBlock(BaseModel):
    build_spec_id: str | None = None
    build_candidate_id: str | None = None
    evaluation_report_id: str | None = None
    staging_snapshot_id: str | None = None
    publication_snapshot_id: str | None = None
    alignment_score: float | None = Field(
        default=None,
        description="From latest evaluation_report row when present.",
    )
    alignment_signals_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured alignment signals from evaluation_report.",
    )


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


class IdentityTraceBlock(BaseModel):
    """Minimal visibility: thread vs graph_run ids and planner input identity_context."""

    thread_identity_id: str | None = None
    graph_run_identity_id: str | None = None
    planner_identity_context: dict[str, Any] | None = Field(
        default=None,
        description="From first planner role_invocation.input_payload_json.identity_context.",
    )


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
    identity_trace: IdentityTraceBlock | None = Field(
        default=None,
        description="Debug: identity linkage and hydrated planner identity_context.",
    )
    session_staging: SessionStagingLinks | None = Field(
        default=None,
        description="Stable links to live working staging for this run (thread-scoped).",
    )


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


# Staging review models re-exported from extracted route module
from kmbl_orchestrator.api.routes_staging import (  # noqa: F401, E402
    ApproveStagingBody,
    LinkedPublicationItem,
    LifecycleTimelineItem,
    RateStagingBody,
    RateStagingResponse,
    RejectStagingBody,
    StagingEvaluationDetail,
    StagingLineageSection,
    StagingListResponse,
    StagingMutationResponse,
    StagingSnapshotDetailResponse,
    UnapproveStagingBody,
)
ApproveStagingResponse = StagingMutationResponse


# Publication models re-exported from extracted route module
from kmbl_orchestrator.api.routes_publication import (  # noqa: F401, E402
    CreatePublicationBody,
    CreatePublicationResponse,
    PublicationLineageSection,
    PublicationListResponse,
    PublicationSnapshotDetailResponse,
    PublicationSnapshotListItem,
)


# Working-staging models re-exported from extracted route module
from kmbl_orchestrator.api.routes_working_staging import (  # noqa: F401, E402
    ApproveWorkingStagingBody,
    LiveWorkingStagingResponse,
    RollbackWorkingStagingBody,
    WorkingStagingCheckpointItem,
    WorkingStagingResponse,
)


def _resolve_start_event_input(
    body: StartRunBody,
    *,
    identity_seed_summary: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    if body.identity_url or body.scenario_preset == IDENTITY_URL_STATIC_FRONTEND_PRESET:
        url = body.identity_url or ""
        return (
            build_identity_url_static_frontend_event_input(
                identity_url=url,
                seed_summary=identity_seed_summary,
            ),
            IDENTITY_URL_STATIC_FRONTEND_PRESET,
        )
    if body.scenario_preset == SEEDED_LOCAL_SCENARIO_PRESET:
        return dict(SEEDED_LOCAL_EVENT_INPUT), SEEDED_LOCAL_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_SCENARIO_PRESET:
        return dict(SEEDED_GALLERY_STRIP_EVENT_INPUT), SEEDED_GALLERY_STRIP_SCENARIO_PRESET
    if body.scenario_preset == SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET:
        return (
            build_seeded_gallery_strip_varied_v1_event_input(),
            SEEDED_GALLERY_STRIP_VARIED_SCENARIO_PRESET,
        )
    if body.scenario_preset == KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET:
        return (
            dict(KILOCLAW_IMAGE_ONLY_TEST_EVENT_INPUT),
            KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_PRESET,
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
        KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
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


def _eval_summary(
    rec: EvaluationReportRecord,
    *,
    evaluator_iteration_index: int | None = None,
) -> EvaluationSummary:
    return EvaluationSummary(
        evaluation_report_id=str(rec.evaluation_report_id),
        status=rec.status,
        summary=rec.summary,
        evaluator_iteration_index=evaluator_iteration_index,
        alignment_score=rec.alignment_score,
        alignment_signals_json=dict(rec.alignment_signals_json or {}),
    )


def _evaluator_iteration_by_invocation_id(
    repo: Repository, graph_run_id: UUID
) -> dict[str, int]:
    """Map evaluator role_invocation_id -> iteration_index for this run."""
    invs = repo.list_role_invocations_for_graph_run(graph_run_id)
    out: dict[str, int] = {}
    for inv in invs:
        if inv.role_type == "evaluator":
            out[str(inv.role_invocation_id)] = int(inv.iteration_index)
    return out


def _evaluation_history_summaries(
    repo: Repository, graph_run_id: UUID
) -> list[EvaluationSummary]:
    rows = repo.list_evaluation_reports_for_graph_run(graph_run_id, limit=50)
    iters = _evaluator_iteration_by_invocation_id(repo, graph_run_id)
    result: list[EvaluationSummary] = []
    for rec in rows:
        ii = iters.get(str(rec.evaluator_invocation_id))
        result.append(_eval_summary(rec, evaluator_iteration_index=ii))
    return result


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
    max_iterations: int | None = None,
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
        mi = max_iterations if max_iterations is not None else settings.graph_max_iterations_default
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
                "max_iterations": mi,
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
                "kiloclaw_image_only_test_v1": {
                    "summary": "KiloClaw image agent integration (3–4 gallery images)",
                    "description": (
                        "Routes generator to kmbl-image-gen when image intent matches. "
                        "Requires KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY and a working gateway."
                    ),
                    "value": {"scenario_preset": "kiloclaw_image_only_test_v1"},
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

    identity_id_str = str(body.identity_id) if body.identity_id is not None else None
    identity_seed_summary: str | None = None

    # Continuation: same thread + identity — skip re-fetch/re-seed so working_staging and ratings apply.
    continuation = (
        body.identity_url
        and body.identity_id is not None
        and body.thread_id is not None
    )
    if body.identity_url and continuation:
        identity_id_str = str(body.identity_id)
        _log.info(
            "run_start stage=identity_url_reuse thread_id=%s identity_id=%s url=%s (skip extract)",
            body.thread_id,
            identity_id_str,
            body.identity_url,
        )
        try:
            prof = repo.get_identity_profile(UUID(identity_id_str))
            if prof and prof.profile_summary:
                identity_seed_summary = prof.profile_summary
        except Exception:
            pass
    elif body.identity_url:
        _log.info(
            "run_start stage=identity_url_extract url=%s deep_crawl=%s",
            body.identity_url, body.deep_crawl,
        )
        try:
            seed = extract_identity_from_url(body.identity_url, deep_crawl=body.deep_crawl)
            iid = persist_identity_from_seed(repo, seed)
            identity_id_str = str(iid)
            identity_seed_summary = seed.to_profile_summary()
            crawl_info = f" pages={len(seed.crawled_pages)}" if seed.crawled_pages else ""
            _log.info(
                "run_start stage=identity_url_extracted identity_id=%s confidence=%.2f%s elapsed_ms=%.1f",
                iid, seed.confidence, crawl_info, (time.perf_counter() - t_req) * 1000,
            )
        except Exception as e:
            _log.warning("run_start identity_url extraction failed: %s", e)
            identity_seed_summary = f"extraction failed: {type(e).__name__}"

    effective_event_input, preset_applied = _resolve_start_event_input(
        body, identity_seed_summary=identity_seed_summary
    )
    if body.user_instructions and str(body.user_instructions).strip():
        effective_event_input = {
            **effective_event_input,
            "user_instructions": str(body.user_instructions).strip(),
        }
    _log.info(
        "run_start stage=event_input_resolved elapsed_ms=%.1f",
        (time.perf_counter() - t_req) * 1000,
    )
    timeout_sec = float(settings.orchestrator_run_start_sync_timeout_sec or 0.0)
    persist_kw: dict[str, Any] = {
        "repo": repo,
        "thread_id": str(body.thread_id) if body.thread_id is not None else None,
        "graph_run_id": None,
        "identity_id": identity_id_str,
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
    effective_event_input = merge_session_staging_into_event_input(
        settings,
        effective_event_input,
        graph_run_id=gid,
        thread_id=tid,
    )
    session_staging = SessionStagingLinks(
        **build_session_staging_links_dict(
            settings,
            graph_run_id=gid,
            thread_id=tid,
        )
    )
    background_tasks.add_task(
        _run_graph_background,
        thread_id=tid,
        graph_run_id=gid,
        identity_id=identity_id_str,
        trigger_type=body.trigger_type,
        event_input=effective_event_input,
        max_iterations=body.max_iterations,
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
        identity_id=identity_id_str,
        session_staging=session_staging,
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
    eval_hist = _evaluation_history_summaries(repo, gid)

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
        evaluation=eval_hist[-1] if eval_hist else None,
        evaluation_history=eval_hist,
        snapshot=sanitize_checkpoint_state_for_api(snap),
        scenario_tag=_scenario_tag_from_snapshot(snap),
        run_event_input=_run_event_input_from_snapshot(snap),
        outputs_substantive=_outputs_substantive(bs, ev, snap),
        timeline_events=timeline_events,
        session_staging=_session_staging_model(settings, gr),
    )


@app.get("/orchestrator/runs/{graph_run_id}/staging-preview")
def graph_run_session_staging_preview_redirect(
    graph_run_id: str,
    bundle_id: str | None = Query(None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Redirect to live working staging HTML for this run's thread (stable per graph_run_id)."""
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
    tid = str(gr.thread_id)
    target = f"/orchestrator/working-staging/{tid}/preview"
    q: dict[str, str] = {}
    if bundle_id:
        q["bundle_id"] = bundle_id
    if q:
        target += "?" + urlencode(q)
    return RedirectResponse(url=target, status_code=307)


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
    first_planner = next((r for r in invocations if r.role_type == "planner"), None)
    planner_ic: dict[str, Any] | None = None
    if first_planner:
        inp = first_planner.input_payload_json or {}
        c = inp.get("identity_context")
        planner_ic = c if isinstance(c, dict) else None
    id_trace = IdentityTraceBlock(
        thread_identity_id=str(thread.identity_id) if thread and thread.identity_id else None,
        graph_run_identity_id=str(gr.identity_id) if gr.identity_id else None,
        planner_identity_context=planner_ic,
    )
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
        identity_trace=id_trace,
        session_staging=_session_staging_model(settings, gr),
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

    Disabled unless ``ORCHESTRATOR_ALLOW_DEV_ROLE_INVOKE`` / ``orchestrator_allow_dev_role_invoke`` is true.
    """
    if not settings.orchestrator_allow_dev_role_invoke:
        raise HTTPException(status_code=404, detail="Not found")
    # Minimal synthetic IDs for standalone calls
    gid = UUID(int=0)
    tid = UUID(int=1)
    routing_meta: dict[str, Any] = {"invoke_role_dev": True, "role_type": body.role_type}
    if body.role_type == "generator":
        p = body.payload
        try:
            key, routing_meta = select_generator_provider_config(
                settings,
                build_spec=p.get("build_spec") or {},
                event_input=p.get("event_input") or {},
                generator_payload=p if isinstance(p, dict) else {},
            )
        except (ImageRouteConfigurationError, ImageRouteBudgetExceededError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
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
        routing_metadata=routing_meta,
    )
    return {"output": raw}


# --- Autonomous Loop / Cron Endpoints ---
# All loop and cron routes live in api/loops.py and are registered at the top of
# this file via app.include_router(_loops_router).
# See api/loops.py::run_graph_for_loop for the execution bridge.


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
