"""FastAPI entrypoint — health + internal orchestrator routes (docs/12 §5)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel  # noqa: F401 — kept for backward compat (tests may import)

from kmbl_orchestrator.api.middleware_api_key import optional_api_key_middleware
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.application.run_lifecycle import (
    resolve_start_event_input,
    run_graph_background,
)
from kmbl_orchestrator.graph.app import persist_graph_run_start
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    GraphRunRecord,
)
from kmbl_orchestrator.persistence.factory import (
    persisted_graph_runs_available,
    repository_backend,
)
from kmbl_orchestrator.persistence.exceptions import (
    ActiveGraphRunPerThreadConflictError,
    RepositoryDispatchBlockedError,
)
from kmbl_orchestrator.persistence.repository_health import (
    compact_preflight_for_start_response,
    get_cached_repository_preflight,
    merge_preflight_into_event_input,
    require_repository_dispatch_healthy,
    sanitize_repository_preflight_for_operator,
)
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.memory.taste import build_taste_profile
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
from kmbl_orchestrator.providers.kiloclaw_protocol import (
    KiloclawTransportConfigError,
    compute_openclaw_resolution,
    log_openclaw_transport_banner,
)
from kmbl_orchestrator.runtime.run_events import (
    RunEventType,
    append_graph_run_event,
    normalization_rescue_event_total,
)
from kmbl_orchestrator.runtime.run_failure_view import build_run_failure_view
from kmbl_orchestrator.runtime.run_snapshot_sanitize import (
    sanitize_checkpoint_state_for_api,
)
from kmbl_orchestrator.runtime.session_staging_links import (
    build_session_staging_links_dict,
    merge_session_staging_into_event_input,
)
from kmbl_orchestrator.runtime.stale_run import reconcile_stale_running_graph_run
from kmbl_orchestrator.staging.candidate_preview import preview_payload_from_build_candidate
from kmbl_orchestrator.staging.static_preview_assembly import (
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)
from kmbl_orchestrator.identity import (
    extract_identity_from_url,
    persist_identity_from_seed,
)
from kmbl_orchestrator.seeds import (
    KILOCLAW_IMAGE_ONLY_TEST_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_SCENARIO_TAG,
    SEEDED_GALLERY_STRIP_VARIED_SCENARIO_TAG,
    SEEDED_SCENARIO_TAG,
)

_log = logging.getLogger(__name__)


def _orchestrator_verbose_logging() -> None:
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


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler — replaces deprecated ``@app.on_event("startup")``."""
    _orchestrator_verbose_logging()
    log_openclaw_transport_banner(get_settings())
    yield


app = FastAPI(title="KMBL Orchestrator", version="0.1.0", lifespan=_lifespan)
app.middleware("http")(optional_api_key_middleware)

# Register extracted route modules
from kmbl_orchestrator.api.loops import router as _loops_router  # noqa: E402
from kmbl_orchestrator.api.routes_identity import router as _identity_router  # noqa: E402
from kmbl_orchestrator.api.routes_maintenance import router as _maintenance_router  # noqa: E402
from kmbl_orchestrator.api.routes_publication import router as _publication_router  # noqa: E402
from kmbl_orchestrator.api.routes_staging import router as _staging_router  # noqa: E402
from kmbl_orchestrator.api.routes_working_staging import router as _ws_router  # noqa: E402
app.include_router(_loops_router)
app.include_router(_identity_router)
app.include_router(_maintenance_router)
app.include_router(_publication_router)
app.include_router(_staging_router)
app.include_router(_ws_router)


# Dependency callables — single source from deps, re-exported for test compatibility.
from kmbl_orchestrator.api.deps import get_invoker, get_repo  # noqa: F401, E402


# All Pydantic models are now in api/models.py — import and re-export for backward compat
from kmbl_orchestrator.api.models import (  # noqa: F401, E402
    AssociatedOutputsBlock,
    BuildCandidateSummary,
    BuildSpecSummary,
    EvaluationSummary,
    GraphRunDetailResponse,
    GraphRunListItem,
    GraphRunListResponse,
    GraphRunSummaryBlock,
    IdentityTraceBlock,
    MemoryInfluenceBlock,
    InvokeRoleBody,
    OperatorActionItem,
    OperatorHomeCanonBlock,
    OperatorHomeReviewQueueBlock,
    OperatorHomeRuntimeBlock,
    OperatorHomeSummaryResponse,
    ResumeRunResponse,
    RoleInvocationDetailItem,
    RunStatusResponse,
    RunTimelineEventSummary,
    RunTimelineItem,
    SessionStagingLinks,
    StartRunResponse,
    InterruptRunResponse,
)
# Override the shim with the real model
from kmbl_orchestrator.api.models import StartRunBody  # noqa: F811, F401, E402


def _session_staging_model(settings: Settings, gr: GraphRunRecord) -> SessionStagingLinks:
    return SessionStagingLinks(
        **build_session_staging_links_dict(
            settings,
            graph_run_id=str(gr.graph_run_id),
            thread_id=str(gr.thread_id),
        )
    )


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

# Backward-compatible names for tests and archive imports
_resolve_start_event_input = resolve_start_event_input
_run_graph_background = run_graph_background


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


def _loopback_openclaw_url(url: str) -> bool:
    u = url.strip().rstrip("/").lower()
    return u.startswith("http://127.0.0.1:") or u.startswith("http://localhost:")


def _resolution_public_view(trace: dict[str, object]) -> dict[str, object]:
    """Include deprecated kiloclaw_* mirrors of openclaw_* trace keys for older clients."""
    out = dict(trace)
    pairs = (
        ("kiloclaw_transport_configured", "openclaw_transport_configured"),
        ("kiloclaw_transport_resolved", "openclaw_transport_resolved"),
        ("kiloclaw_stub_mode", "openclaw_stub_mode"),
        ("kiloclaw_api_key_present", "openclaw_api_key_present"),
        ("kiloclaw_auto_resolution_note", "openclaw_auto_resolution_note"),
        ("kiloclaw_openclaw_cli_path", "openclaw_openclaw_cli_path"),
    )
    for legacy, modern in pairs:
        if legacy not in out and modern in out:
            out[legacy] = out[modern]
    return out


def _openclaw_configured(settings: Settings, eff: str) -> bool:
    if eff == "invalid":
        return False
    if eff == "stub":
        return True
    if eff == "http":
        base = (settings.openclaw_base_url or "").strip()
        if not base:
            return False
        key = bool((settings.openclaw_api_key or "").strip())
        return key or _loopback_openclaw_url(base)
    if eff == "openclaw_cli":
        return bool((settings.openclaw_openclaw_executable or "").strip())
    return False


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Liveness + deployment hints. Never returns secret values — only booleans / non-sensitive config."""
    eff = settings.effective_openclaw_transport()
    key_set = bool((settings.openclaw_api_key or "").strip())
    supabase_ok = bool((settings.supabase_url or "").strip()) and bool(
        (settings.supabase_service_role_key or "").strip()
    )
    persist_ok = persisted_graph_runs_available(settings)
    oc_ok = _openclaw_configured(settings, eff)

    openclaw_resolution: dict[str, object] = {}
    try:
        r = compute_openclaw_resolution(settings)
        openclaw_resolution = _resolution_public_view(
            {
                "configuration_valid": True,
                **r.to_trace_dict(),
                "real_agent_capable": not r.stub_mode,
            }
        )
    except KiloclawTransportConfigError as e:
        openclaw_resolution = {
            "configuration_valid": False,
            "configuration_error": str(e),
            "real_agent_capable": False,
        }

    dispatch = settings.orchestrator_graph_run_dispatch
    dispatch_note = (
        "Graph runs use FastAPI BackgroundTasks (same process, not durable across restarts)."
        if dispatch == "fastapi_background"
        else f"dispatch_mode={dispatch}"
    )

    loopback = _loopback_openclaw_url(settings.openclaw_base_url or "")
    http_ready = eff == "http" and bool((settings.openclaw_base_url or "").strip()) and (
        key_set or loopback
    )

    return {
        "status": "ok",
        "service": "kmbl-orchestrator",
        "listen": {
            "host": settings.orchestrator_host,
            "port": settings.orchestrator_port,
        },
        "kmbl_env": settings.kmbl_env,
        "allow_stub_transport": settings.allow_stub_transport,
        "openclaw_transport": settings.openclaw_transport,
        "openclaw_transport_effective": eff,
        "openclaw_resolution": openclaw_resolution,
        "openclaw_base_url": settings.openclaw_base_url,
        "openclaw_invoke_path": settings.openclaw_invoke_path,
        "openclaw_chat_completions_user": settings.openclaw_chat_completions_user,
        "openclaw_planner_config_key": settings.openclaw_planner_config_key,
        "openclaw_generator_config_key": settings.openclaw_generator_config_key,
        "openclaw_evaluator_config_key": settings.openclaw_evaluator_config_key,
        # Deprecated: same values as openclaw_* — kept for short-lived scripts / older tooling.
        "kiloclaw_transport": settings.openclaw_transport,
        "kiloclaw_transport_effective": eff,
        "kiloclaw_resolution": openclaw_resolution,
        "kiloclaw_base_url": settings.openclaw_base_url,
        "kiloclaw_invoke_path": settings.openclaw_invoke_path,
        "kiloclaw_chat_completions_user": settings.openclaw_chat_completions_user,
        "kiloclaw_planner_config_key": settings.openclaw_planner_config_key,
        "kiloclaw_generator_config_key": settings.openclaw_generator_config_key,
        "kiloclaw_evaluator_config_key": settings.openclaw_evaluator_config_key,
        "normalization_rescue_events_total": normalization_rescue_event_total(),
        "normalization_rescue_events_total_note": (
            "Process-local counter since orchestrator start — use graph_run detail quality_metrics for durable counts."
        ),
        "orchestrator_graph_run_dispatch": dispatch,
        "orchestrator_graph_run_dispatch_note": dispatch_note,
        "env": {
            "supabase_url_configured": bool((settings.supabase_url or "").strip()),
            "supabase_service_role_key_configured": bool(
                (settings.supabase_service_role_key or "").strip()
            ),
            "openclaw_api_key_configured": key_set,
            "kiloclaw_api_key_configured": key_set,
            "http_transport_ready": http_ready,
        },
        "readiness": {
            "supabase_configured": supabase_ok,
            "openclaw_configured": oc_ok,
            "kiloclaw_configured": oc_ok,
            "openclaw_transport_operational": eff != "invalid"
            and bool(openclaw_resolution.get("configuration_valid")),
            "kiloclaw_transport_operational": eff != "invalid"
            and bool(openclaw_resolution.get("configuration_valid")),
            "persisted_runs_available": persist_ok,
            "ready_for_full_local_run": persist_ok and oc_ok,
            "note": (
                "Config-only flags: they do not probe live Supabase REST or OpenClaw gateway HTTP. "
                "A true ready_for_full_local_run still requires valid keys and network reachability."
            ),
        },
        "repository_last_preflight": (
            sanitize_repository_preflight_for_operator(lp)
            if (lp := get_cached_repository_preflight())
            else None
        ),
        "repository_last_preflight_note": (
            "Process-local snapshot from the last successful or attempted Supabase REST preflight "
            "(start_run / autonomous loop). Null until a run is attempted."
        ),
        "repository_backend": repository_backend(settings),
        "orchestrator_running_stale_after_seconds": settings.orchestrator_running_stale_after_seconds,
        "orchestrator_smoke_planner_only": settings.orchestrator_smoke_planner_only,
        "openclaw_http_connect_timeout_sec": settings.openclaw_http_connect_timeout_sec,
        "openclaw_http_read_timeout_sec": settings.openclaw_http_read_timeout_sec,
        "kiloclaw_http_connect_timeout_sec": settings.openclaw_http_connect_timeout_sec,
        "kiloclaw_http_read_timeout_sec": settings.openclaw_http_read_timeout_sec,
    }


def _finalize_interrupt_requested_for_new_start(
    repo: Repository,
    *,
    graph_run_id: UUID,
    thread_id: UUID,
) -> None:
    """Mark ``interrupt_requested`` run as ``interrupted`` so the same thread can start again."""
    ended = datetime.now(timezone.utc).isoformat()
    repo.update_graph_run_status(graph_run_id, "interrupted", ended)
    append_graph_run_event(
        repo,
        graph_run_id,
        RunEventType.GRAPH_RUN_INTERRUPTED,
        {
            "reason": "superseded_by_new_start",
            "note": (
                "Prior run was interrupt_requested; marked interrupted so a new run "
                "could start on the same thread."
            ),
        },
        thread_id=thread_id,
    )


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
                "identity_url_bundle_v1": {
                    "summary": "Identity URL — planner may choose static or interactive bundle",
                    "description": (
                        "Default identity vertical: does not pin canonical_vertical before planning. "
                        "Use identity_url_static_v1 to force static_frontend_file_v1."
                    ),
                    "value": {
                        "identity_url": "https://example.com/",
                        "scenario_preset": "identity_url_bundle_v1",
                    },
                },
                "identity_url_cool_generation_lane": {
                    "summary": "Identity URL + cool_generation_v1 lane (merge into preset)",
                    "description": (
                        "Sets identity_url and merges event_input.cool_generation_lane into the identity URL "
                        "seed (default bundle-capable; use scenario_preset identity_url_static_v1 to pin static)."
                    ),
                    "value": {
                        "identity_url": "https://example.com/",
                        "event_input": {"cool_generation_lane": True},
                    },
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

    preflight_snapshot: dict[str, Any] | None = None
    try:
        preflight_snapshot = require_repository_dispatch_healthy(
            repo, settings, context="post_orchestrator_runs_start"
        )
    except RepositoryDispatchBlockedError as e:
        bp = e.snapshot.get("block_phase")
        if bp == "write_canary":
            msg = (
                "Supabase write-path RPC canary failed — the PostgREST rpc channel is unusable "
                "for atomic persistence. Fix migrations, keys, or network before starting a run."
            )
            hint = (
                "Apply the latest Supabase migrations (including kmbl_repository_write_path_canary), "
                "verify service_role can execute RPCs, and ensure no proxy returns HTML for /rest/v1/rpc."
            )
        else:
            msg = (
                "Supabase REST read preflight failed — fix SUPABASE_URL and service role key "
                "before starting a run."
            )
            hint = (
                "Ensure SUPABASE_URL is the project's REST API base (https://<ref>.supabase.co), "
                "not the dashboard URL; verify the key; ensure no proxy returns HTML."
            )
        raise HTTPException(
            status_code=503,
            detail={
                "error_kind": "repository_preflight_failed",
                "message": msg,
                "repository_health": sanitize_repository_preflight_for_operator(e.snapshot),
                "hint": hint,
            },
        ) from e

    identity_id_str = str(body.identity_id) if body.identity_id is not None else None
    identity_seed_summary: str | None = None

    # Continuation: same thread + identity — skip re-fetch/re-seed so working_staging and ratings apply.
    continuation = (
        body.identity_url
        and body.identity_id is not None
        and body.thread_id is not None
        and body.habitat_session != "fresh"
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
    elif (
        body.identity_url
        and body.identity_id is not None
        and body.habitat_session == "fresh"
    ):
        identity_id_str = str(body.identity_id)
        _log.info(
            "run_start stage=identity_reuse_new_habitat identity_id=%s url=%s (new thread, same identity)",
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
    effective_event_input = {
        **effective_event_input,
        "kmbl_habitat_session": (
            "fresh" if body.habitat_session == "fresh" else "continue"
        ),
    }
    if body.user_instructions and str(body.user_instructions).strip():
        effective_event_input = {
            **effective_event_input,
            "user_instructions": str(body.user_instructions).strip(),
        }
    effective_event_input = merge_preflight_into_event_input(
        effective_event_input, preflight_snapshot
    )
    _log.info(
        "run_start stage=event_input_resolved elapsed_ms=%.1f",
        (time.perf_counter() - t_req) * 1000,
    )
    if body.thread_id is not None and body.habitat_session != "fresh":
        tid_u = UUID(str(body.thread_id))
        try:
            active = await asyncio.to_thread(
                repo.get_active_graph_run_for_thread, tid_u
            )
        except Exception as e:
            _log.exception("get_active_graph_run_for_thread failed")
            raise HTTPException(
                status_code=500,
                detail={
                    "error_kind": "persistence_error",
                    "step": "get_active_graph_run_for_thread",
                    "exception": type(e).__name__,
                    "message": str(e),
                },
            ) from e
        if active is not None:
            if active.status == "interrupt_requested":
                await asyncio.to_thread(
                    _finalize_interrupt_requested_for_new_start,
                    repo,
                    graph_run_id=active.graph_run_id,
                    thread_id=active.thread_id,
                )
                _log.info(
                    "run_start superseded interrupt_requested graph_run_id=%s thread_id=%s",
                    active.graph_run_id,
                    tid_u,
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_kind": "active_graph_run",
                        "message": (
                            "This thread already has an active graph run. "
                            "Wait for it to finish, interrupt it, or use a different thread."
                        ),
                        "active_graph_run_id": str(active.graph_run_id),
                        "active_status": active.status,
                    },
                )

    timeout_sec = float(settings.orchestrator_run_start_sync_timeout_sec or 0.0)
    persist_kw: dict[str, Any] = {
        "repo": repo,
        "thread_id": (
            None
            if body.habitat_session == "fresh"
            else (str(body.thread_id) if body.thread_id is not None else None)
        ),
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
    except ActiveGraphRunPerThreadConflictError:
        _log.warning(
            "run_start race: concurrent persist for thread_id=%s (graph_run_one_active_per_thread)",
            body.thread_id,
        )
        active_after: GraphRunRecord | None = None
        if body.thread_id is not None:
            try:
                active_after = await asyncio.to_thread(
                    repo.get_active_graph_run_for_thread,
                    UUID(str(body.thread_id)),
                )
            except Exception:
                active_after = None
        if active_after is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_kind": "active_graph_run",
                    "message": (
                        "This thread already has an active graph run (detected after a concurrent "
                        "start raced). Wait for it to finish, interrupt it, or retry shortly."
                    ),
                    "active_graph_run_id": str(active_after.graph_run_id),
                    "active_status": active_after.status,
                },
            ) from None
        raise HTTPException(
            status_code=409,
            detail={
                "error_kind": "active_graph_run",
                "message": (
                    "Concurrent start requests conflicted for this thread. "
                    "Only one active graph run is allowed per thread."
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
        status="starting",
        scenario_preset=preset_applied,
        effective_event_input=effective_event_input,
        identity_id=identity_id_str,
        session_staging=session_staging,
        repository_preflight=compact_preflight_for_start_response(preflight_snapshot),
    )


@app.post(
    "/orchestrator/runs/{graph_run_id}/interrupt",
    response_model=InterruptRunResponse,
    summary="Request cooperative interrupt for a graph run",
)
def interrupt_graph_run(
    graph_run_id: str,
    repo: Repository = Depends(get_repo),
) -> InterruptRunResponse:
    try:
        gid = UUID(graph_run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid graph_run_id") from e
    gr_before = repo.get_graph_run(gid)
    if gr_before is None:
        raise HTTPException(status_code=404, detail="graph_run not found")
    try:
        gr = repo.request_graph_run_interrupt(gid)
    except KeyError:
        raise HTTPException(status_code=404, detail="graph_run not found") from None
    except ValueError as e:
        msg = str(e)
        if msg.startswith("terminal_status:"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error_kind": "run_terminal",
                    "message": "Run is already in a terminal state.",
                    "detail": msg,
                },
            ) from e
        if msg == "paused":
            raise HTTPException(
                status_code=409,
                detail={
                    "error_kind": "run_paused",
                    "message": "Cannot interrupt a paused run — use resume instead.",
                },
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e

    need_event = (
        gr_before.status != "interrupt_requested"
        or gr_before.interrupt_requested_at is None
    )
    if need_event:
        append_graph_run_event(
            repo,
            gid,
            RunEventType.INTERRUPT_REQUESTED,
            {},
            thread_id=gr.thread_id,
        )
    return InterruptRunResponse(
        graph_run_id=str(gr.graph_run_id),
        thread_id=str(gr.thread_id),
        status=gr.status,
        interrupt_requested_at=gr.interrupt_requested_at,
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
    thread_id: str | None = None,
    limit: int = 50,
    repo: Repository = Depends(get_repo),
) -> GraphRunListResponse:
    """
    Pass I: compact index of recent graph runs (persisted rows only).

    Does not reconcile stale ``running`` rows or return checkpoint snapshots — use
    **GET /orchestrator/runs/{id}** or **/detail** for per-run views.

    Optional **thread_id** scopes results to a single thread (newest ``started_at`` first).
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
    thread_uuid: UUID | None = None
    thread_raw = _optional_query_str(thread_id)
    if thread_raw is not None:
        try:
            thread_uuid = UUID(thread_raw)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid thread_id") from e

    runs = repo.list_graph_runs(
        status=st,
        trigger_type=tt,
        identity_id=id_uuid,
        thread_id=thread_uuid,
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


@app.get("/orchestrator/runs/{graph_run_id}/candidate-preview")
def graph_run_candidate_preview(
    graph_run_id: str,
    bundle_id: str | None = Query(None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Serve assembled HTML from the **latest** persisted ``build_candidate`` for this graph run.

    Use for evaluator / MCP / Playwright during iterate loops: ``working_staging`` preview may
    lag until ``staging_node`` runs; this URL tracks the most recent generator output for the run.
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

    bc = repo.get_latest_build_candidate_for_graph_run(gid)
    if bc is None:
        raise HTTPException(
            status_code=404,
            detail={"error_kind": "candidate_preview_unavailable", "reason": "no_build_candidate"},
        )
    p = preview_payload_from_build_candidate(bc)
    entry, err = resolve_static_preview_entry_path(p, bundle_id=bundle_id)
    if err or not entry:
        raise HTTPException(
            status_code=404,
            detail={
                "error_kind": "candidate_preview_unavailable",
                "reason": err or "unknown",
            },
        )
    html, aerr = assemble_static_preview_html(p, entry_path=entry)
    if aerr or not html:
        raise HTTPException(
            status_code=404,
            detail={
                "error_kind": "candidate_preview_unavailable",
                "reason": aerr or "unknown",
            },
        )
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; img-src data: https:; font-src data:; "
                "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self' https://unpkg.com https://cdn.jsdelivr.net"
            ),
            "Cache-Control": "private, no-store",
        },
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
    raw["summary"]["working_staging_present"] = (
        repo.get_working_staging_for_thread(gr.thread_id) is not None
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
    mem_loaded = [
        {"created_at": e.created_at, "payload": dict(e.payload_json or {})}
        for e in events
        if e.event_type == RunEventType.CROSS_RUN_MEMORY_LOADED
    ]
    mem_updated = [
        {"created_at": e.created_at, "payload": dict(e.payload_json or {})}
        for e in events
        if e.event_type == RunEventType.CROSS_RUN_MEMORY_UPDATED
    ]
    rows_by_run = repo.list_identity_cross_run_memory_by_source_run(gid)
    mem_keys = [r.memory_key for r in rows_by_run]
    taste_summary: dict[str, Any] | None = None
    if thread and thread.identity_id:
        all_rows = repo.list_identity_cross_run_memory(thread.identity_id, limit=80)
        taste_summary = build_taste_profile(all_rows, settings).model_dump()
    mem_block = MemoryInfluenceBlock(
        loaded_payloads=mem_loaded,
        updated_payloads=mem_updated,
        persisted_memory_keys_for_run=mem_keys,
        identity_taste_summary=taste_summary,
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
        memory_influence=mem_block,
        failure_info=raw.get("failure_info"),
        last_meaningful_event=raw.get("last_meaningful_event"),
    )


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
            "planner": settings.openclaw_planner_config_key,
            "generator": settings.openclaw_generator_config_key,
            "evaluator": settings.openclaw_evaluator_config_key,
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
