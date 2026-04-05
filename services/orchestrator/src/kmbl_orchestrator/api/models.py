"""Pydantic request/response models for the KMBL Orchestrator API.

Extracted from api/main.py to keep route handlers slim.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# start run
# ---------------------------------------------------------------------------

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


class StartRunResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: Literal["starting", "running"] = Field(
        default="starting",
        description=(
            "Persisted lifecycle: starting when enqueued, then running once the graph begins. "
            "Poll GET /orchestrator/runs/{id} for interrupt_requested / completed / failed / interrupted."
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


class InterruptRunResponse(BaseModel):
    graph_run_id: str
    thread_id: str
    status: str
    interrupt_requested_at: str | None = None


# ---------------------------------------------------------------------------
# run status
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# graph run detail
# ---------------------------------------------------------------------------

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
    interrupt_requested_at: str | None = None
    started_at: str
    ended_at: str | None = None
    max_iteration_index: int | None = None
    latest_checkpoint_id: str | None = None
    run_state_hint: str
    attention_state: str
    attention_reason: str
    resume_count: int = 0
    last_resumed_at: str | None = None
    openclaw_transport_trace: dict[str, Any] | None = Field(
        default=None,
        description="From first planner routing_metadata_json when present.",
    )
    quality_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Durable normalization rescue counts (events + generator routing flags). "
            "Only genuine recovery/correction events are counted; informational "
            "enrichment (e.g. content_index_built, content_enrichment) is tracked "
            "separately and does not inflate rescue metrics."
        ),
    )
    pressure_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="v1 pressure telemetry from persisted graph_run_event rows (extensible).",
    )
    working_staging_present: bool = Field(
        default=False,
        description=(
            "True when a working_staging row exists for summary.thread_id "
            "(required for GET …/working-staging/{thread_id}/live / live habitat)."
        ),
    )


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
    openclaw_transport_trace: dict[str, Any] | None = Field(
        default=None,
        description="Subset of persisted routing_metadata_json (OpenClaw gateway trace keys).",
    )
    normalization_rescue: bool | None = Field(
        default=None,
        description=(
            "True when generator invocation required normalization rescue — "
            "i.e. actual recovery/correction of malformed output (persisted flag). "
            "Informational enrichment does not set this flag."
        ),
    )


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


class MemoryInfluenceBlock(BaseModel):
    """Cross-run memory read/write trace for this graph run (and optional taste snapshot)."""

    loaded_payloads: list[dict[str, Any]] = Field(
        default_factory=list,
        description="CROSS_RUN_MEMORY_LOADED events for this run (payload_json + created_at).",
    )
    updated_payloads: list[dict[str, Any]] = Field(
        default_factory=list,
        description="CROSS_RUN_MEMORY_UPDATED events for this run.",
    )
    persisted_memory_keys_for_run: list[str] = Field(
        default_factory=list,
        description="identity_cross_run_memory rows with source_graph_run_id = this run.",
    )
    identity_taste_summary: dict[str, Any] | None = Field(
        default=None,
        description="Aggregated taste for thread.identity_id when available.",
    )


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
    memory_influence: MemoryInfluenceBlock | None = Field(
        default=None,
        description="Cross-run memory audit: events + persisted keys + optional taste summary.",
    )
    failure_info: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When status=failed: failure_phase, error_kind, error_message "
            "(from failed role_invocation or graph_run_failed event)."
        ),
    )
    last_meaningful_event: dict[str, Any] | None = Field(
        default=None,
        description="Most recent high-signal graph_run_event with full payload (debugging).",
    )


# ---------------------------------------------------------------------------
# graph run list
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# operator home summary
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# invoke role
# ---------------------------------------------------------------------------

class InvokeRoleBody(BaseModel):
    """Passthrough to ``RoleProvider.invoke_role`` — dev / integration testing."""

    role_type: Literal["planner", "generator", "evaluator"]
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# resume run
# ---------------------------------------------------------------------------

class ResumeRunResponse(BaseModel):
    """Pass K — operator resumed graph execution for this graph_run_id."""

    ok: bool = True
    graph_run_id: str
    status: str = "running"
