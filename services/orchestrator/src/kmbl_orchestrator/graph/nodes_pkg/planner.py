"""planner_node — invoke the planner role and persist the resulting build spec."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.persistence_validate import (
    validate_role_output_for_persistence,
)
from kmbl_orchestrator.contracts.planner_normalize import (
    apply_first_iteration_literal_cap,
    compact_planner_wire_output,
    normalize_build_spec_for_persistence,
)
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError, RoleInvocationFailed
from kmbl_orchestrator.graph.helpers import (
    _persist_invocation_failure,
    _save_checkpoint_with_event,
)
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.normalize import normalize_planner_output
from kmbl_orchestrator.normalize.planner_canonicalize import canonicalize_planner_raw
from kmbl_orchestrator.runtime.cool_generation_lane import apply_cool_generation_lane_presets
from kmbl_orchestrator.runtime.immersive_contract_hardening import (
    harden_immersive_planner_output,
)
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    WEBGL_EXPERIENCE_MODES,
    clamp_experience_mode_for_static_vertical,
)
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.reference_library import build_planner_reference_payload
from kmbl_orchestrator.runtime.habitat_strategy import (
    build_spec_with_effective_habitat,
    effective_habitat_strategy_for_iteration,
)
from kmbl_orchestrator.runtime.payload_budget_governor_v1 import (
    apply_payload_budget_governor_v1,
    merge_governor_report_into_telemetry,
)
from kmbl_orchestrator.runtime.payload_telemetry_v1 import build_payload_telemetry_v1
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.working_staging_read import (
    get_working_staging_for_thread_resilient,
)
from kmbl_orchestrator.memory.ops import memory_bias_for_experience_mode
from kmbl_orchestrator.runtime.generator_iteration_compact_v1 import (
    _PLANNER_REPLAN_SPEC_KEYS,
    build_spec_digest,
    compact_crawl_context_for_replan,
)
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)
from kmbl_orchestrator.staging.habitat_surface_reset import (
    clear_working_staging_surface,
    fingerprint_working_staging_payload,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)

def _derive_surface_type(experience_mode: str) -> str:
    """Map experience_mode to a surface_type for generator guidance.

    surface_type tells the generator what output shape to produce:
    - ``static_html``: standard HTML/CSS/JS (default)
    - ``webgl_experience``: canvas-based rendering with shader/config files
    """
    if experience_mode in WEBGL_EXPERIENCE_MODES:
        return "webgl_experience"
    return "static_html"


def planner_node(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Invoke the planner role and persist the resulting build spec."""
    gid = UUID(state["graph_run_id"])
    tid = UUID(state["thread_id"])
    raise_if_interrupt_requested(ctx.repo, gid, tid)
    cp0 = CheckpointRecord(
        checkpoint_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        checkpoint_kind="pre_role",
        state_json={**dict(state), "_role_checkpoint_gate": "pre_planner"},
        context_compaction_json=None,
    )
    _save_checkpoint_with_event(ctx.repo, cp0)
    append_graph_run_event(ctx.repo, gid, RunEventType.PLANNER_INVOCATION_STARTED, {}, thread_id=tid)
    _log.info(
        "graph_run graph_run_id=%s stage=planner_invocation_start elapsed_ms=0.0",
        gid,
    )

    iteration_idx = int(state.get("iteration_index", 0))

    # Build working staging facts for planner's habitat strategy decision
    ws = get_working_staging_for_thread_resilient(
        ctx.repo,
        tid,
        graph_run_id=gid,
        phase="planner",
        iteration_index=iteration_idx,
    )
    ws_facts: dict[str, Any] | None = None
    user_rating_context: dict[str, Any] | None = None

    if ws is not None:
        checkpoints = ctx.repo.list_staging_checkpoints(ws.working_staging_id, limit=5)
        latest_cp = checkpoints[0] if checkpoints else None

        # Collect recent user ratings for trend signal
        staging_snapshots = ctx.repo.list_staging_snapshots_for_thread(tid, limit=5)
        recent_ratings = [
            s.user_rating for s in staging_snapshots if s.user_rating is not None
        ]
        # Most-recent-first from DB → reverse so oldest→newest for trend calc
        recent_ratings = list(reversed(recent_ratings))

        facts = build_working_staging_facts(
            ws,
            checkpoint_count=len(checkpoints),
            latest_checkpoint_revision=latest_cp.revision_at_checkpoint if latest_cp else None,
            latest_checkpoint_trigger=latest_cp.trigger if latest_cp else None,
            patches_since_rebuild=(ws.revision - (ws.last_rebuild_revision or 0)),
            stagnation_count=ws.stagnation_count,
            recent_user_ratings=recent_ratings if recent_ratings else None,
        )
        ws_facts = working_staging_facts_to_payload(facts)

        # Build user_rating_context from most recent rated snapshot
        if staging_snapshots:
            latest_staging = staging_snapshots[0]
            if latest_staging.user_rating is not None:
                user_rating_context = {
                    "rating": latest_staging.user_rating,
                    "feedback": latest_staging.user_feedback,
                    "rated_at": latest_staging.rated_at,
                }

    # Check for user interrupts from autonomous loop
    user_interrupts: list[dict[str, Any]] = []
    identity_id_str = state.get("identity_id")
    if identity_id_str:
        try:
            loop = ctx.repo.get_autonomous_loop_for_identity(UUID(identity_id_str))
            if loop and loop.exploration_directions:
                user_interrupts = [
                    d for d in loop.exploration_directions
                    if d.get("type") == "user_interrupt"
                ]
        except Exception:
            pass

    ei = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
    identity_url = ei.get("identity_url")
    if not isinstance(identity_url, str) or not identity_url.strip():
        identity_url = None
    else:
        identity_url = identity_url.strip()

    # Crawl context is injected by context_hydrator into event_input
    crawl_context = ei.get("crawl_context") if isinstance(ei, dict) else None
    # On replans (iteration > 0) the planner already consumed the full crawl on
    # iteration 0 — send a compact view (counts/phase/exhaustion) not full page summaries.
    crawl_context_for_payload = (
        compact_crawl_context_for_replan(crawl_context)
        if iteration_idx > 0 and isinstance(crawl_context, dict)
        else crawl_context
    )
    payload: dict[str, Any] = {
        "graph_run_id": str(gid),
        "thread_id": state["thread_id"],
        "identity_context": state.get("identity_context") or {},
        "memory_context": state.get("memory_context") or {},
        "event_input": ei,
        "current_state_summary": state.get("current_state") or {},
        "working_staging_facts": ws_facts,
        "user_rating_context": user_rating_context,
        "user_interrupts": user_interrupts if user_interrupts else None,
        # Explicit for identity-vertical + Playwright grounding (see kmbl-planner SOUL)
        "identity_url": identity_url,
        # Structured identity profile for intent-driven planning.
        # Carries themes, tone, visual_tendencies, content_types, complexity, notable_entities.
        "structured_identity": state.get("structured_identity"),
        # Durable crawl state for cross-session resumption.
        # Tells the planner what URLs have been visited, what's next, whether crawl is exhausted.
        # Compacted on replans: full page summaries already incorporated in iteration 0 plan.
        "crawl_context": crawl_context_for_payload,
    }
    payload.update(
        build_planner_reference_payload(
            structured_identity=state.get("structured_identity")
            if isinstance(state.get("structured_identity"), dict)
            else None,
            crawl_context=crawl_context if isinstance(crawl_context, dict) else None,
            graph_run_id=str(gid),
        )
    )
    if iteration_idx > 0:
        ev = state.get("evaluation_report") if isinstance(state.get("evaluation_report"), dict) else {}
        bs = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
        # Slim prior_build_spec to only replan-relevant keys — creative/crawl blobs
        # are already incorporated into the identity profile and prior eval report.
        # Send digest so the planner can verify it's referencing the right spec.
        _slim_bs = {k: v for k, v in bs.items() if k in _PLANNER_REPLAN_SPEC_KEYS}
        rctx: dict[str, Any] = {
            "replan": True,
            "iteration_index": iteration_idx,
            "prior_build_spec_id": state.get("build_spec_id"),
            "prior_build_spec_digest": build_spec_digest(bs) if bs else None,
            "prior_evaluation_report": {
                "status": ev.get("status"),
                "summary": ev.get("summary"),
                "issues": ev.get("issues"),
            },
            "retry_context": state.get("retry_context"),
            "prior_build_spec": _slim_bs,
        }
        pv2 = state.get("last_build_candidate_summary_v2")
        pv1 = state.get("last_build_candidate_summary_v1")
        if isinstance(pv2, dict):
            rctx["prior_build_candidate_summary_v2"] = pv2
        if isinstance(pv1, dict):
            rctx["prior_build_candidate_summary_v1"] = pv1
        payload["replan_context"] = rctx
    payload, gov_rep_pl = apply_payload_budget_governor_v1("planner", payload)
    tel_pl = build_payload_telemetry_v1(
        "planner",
        payload,
        payload_budget_notes="replan" if iteration_idx > 0 else None,
    )
    tel_pl = merge_governor_report_into_telemetry(tel_pl, gov_rep_pl)
    t_pl = time.perf_counter()
    try:
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.openclaw_planner_config_key,
            input_payload=payload,
            iteration_index=state.get("iteration_index", 0),
            routing_metadata={"kmbl_payload_telemetry_v1": tel_pl},
        )
    except KiloclawRoleInvocationForbiddenError as e:
        raise RoleInvocationFailed(
            phase="planner",
            graph_run_id=gid,
            thread_id=tid,
            detail={
                "error_kind": "transport_forbidden",
                "message": str(e),
                "operator_hint": e.operator_hint,
            },
        ) from e
    _log.info(
        "graph_run graph_run_id=%s stage=planner_invocation_finished elapsed_ms=%.1f",
        gid,
        (time.perf_counter() - t_pl) * 1000,
    )
    if inv.status == "failed":
        ctx.repo.save_role_invocation(inv)
        raise RoleInvocationFailed(
            phase="planner",
            graph_run_id=gid,
            thread_id=tid,
            detail=raw,
        )
    raw = compact_planner_wire_output(raw)
    if not isinstance(raw.get("build_spec"), dict):
        raw["build_spec"] = {}

    bs0 = raw["build_spec"]
    if isinstance(bs0, dict):
        bs0, literal_capped = apply_first_iteration_literal_cap(bs0, iteration_idx)
        raw["build_spec"] = bs0
        if literal_capped:
            raw.setdefault("_kmbl_planner_metadata", {})[
                "first_iteration_literal_checks_capped"
            ] = True

    # FIX 3: Hoist top-level selected_urls into build_spec so
    # extract_planner_selected_urls() can find them regardless of where
    # the planner placed them.  Merge with any already inside build_spec.
    _hoist_selected_urls_into_build_spec(raw)

    wire_fixes = canonicalize_planner_raw(raw)
    if wire_fixes:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.PLANNER_WIRE_CANONICALIZED,
            {"fixes": wire_fixes},
            thread_id=tid,
        )
    norm_bs, normalized_fields = normalize_build_spec_for_persistence(raw["build_spec"])
    raw["build_spec"] = norm_bs
    if normalized_fields:
        md = raw.setdefault("_kmbl_planner_metadata", {})
        md["normalized_missing_fields"] = normalized_fields

    cc_plan = ei.get("crawl_context") if isinstance(ei, dict) else None
    if isinstance(cc_plan, dict):
        from kmbl_orchestrator.identity.crawl_frontier_tags import annotate_selected_urls_grounding

        gmeta = annotate_selected_urls_grounding(raw["build_spec"], cc_plan)
        if gmeta:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.PLANNER_CRAWL_COMPLIANCE,
                {"kind": "selected_url_grounding", **gmeta},
                thread_id=tid,
            )

    # Ensure experience_mode is always explicitly set in build_spec.
    # If the planner set it, we respect it; otherwise, derive from structured identity.
    # Cross-run memory may bias toward a remembered mode only when identity confidence is low
    # (see memory_bias_for_experience_mode); planner-authored experience_mode is never overridden.
    bs = raw["build_spec"]
    existing_mode = bs.get("experience_mode")
    if not isinstance(existing_mode, str) or not existing_mode.strip():
        from kmbl_orchestrator.identity.profile import (
            StructuredIdentityProfile,
            derive_experience_mode_with_confidence,
        )
        si_payload = state.get("structured_identity")
        if si_payload and isinstance(si_payload, dict):
            si = StructuredIdentityProfile.model_validate(si_payload)
        else:
            si = StructuredIdentityProfile()
        mode_result = derive_experience_mode_with_confidence(
            si, site_archetype=bs.get("site_archetype"),
        )
        derived_mode = mode_result["experience_mode"]
        bs["experience_mode"] = derived_mode
        md = raw.setdefault("_kmbl_planner_metadata", {})
        md["experience_mode_derived"] = True
        md["experience_mode_source"] = "structured_identity"
        md["experience_confidence"] = mode_result["experience_confidence"]
        mc = state.get("memory_context") or {}
        cross = mc.get("cross_run") if isinstance(mc, dict) else {}
        ts = cross.get("taste_summary") if isinstance(cross, dict) else {}
        ts_d = ts if isinstance(ts, dict) else {}
        bias_mode, bias_reason = memory_bias_for_experience_mode(
            structured_identity=si_payload if isinstance(si_payload, dict) else None,
            taste_summary=ts_d,
            settings=ctx.settings,
        )
        if bias_mode and bias_mode != derived_mode:
            bs["experience_mode"] = bias_mode
            md["experience_mode_source"] = "structured_identity_with_cross_run_memory_bias"
            md["experience_mode_memory_bias"] = {"to": bias_mode, "reason": bias_reason}
        _log.info(
            "graph_run graph_run_id=%s experience_mode derived=%s confidence=%.2f archetype=%s",
            gid, bs.get("experience_mode"), mode_result["experience_confidence"], bs.get("site_archetype"),
        )

    clamp_fixes = clamp_experience_mode_for_static_vertical(bs, ei)
    if clamp_fixes:
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.STATIC_VERTICAL_EXPERIENCE_MODE_CLAMPED,
            {"fixes": clamp_fixes},
            thread_id=tid,
        )

    # Derive surface_type from experience_mode so generator knows what output shape to produce.
    # This is a simple mapping — no over-engineering.
    if not isinstance(bs.get("surface_type"), str) or not bs.get("surface_type", "").strip():
        bs["surface_type"] = _derive_surface_type(bs.get("experience_mode", ""))
        raw.setdefault("_kmbl_planner_metadata", {})["surface_type_derived"] = True

    ib_lane = state.get("identity_brief") if isinstance(state.get("identity_brief"), dict) else {}
    si_lane = state.get("structured_identity") if isinstance(state.get("structured_identity"), dict) else {}
    raw["build_spec"], lane_meta = apply_cool_generation_lane_presets(
        raw["build_spec"],
        ei,
        ib_lane,
        si_lane,
    )
    if lane_meta.get("applied"):
        raw.setdefault("_kmbl_planner_metadata", {})["cool_generation_lane"] = lane_meta

    ei_habitat = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
    effective = effective_habitat_strategy_for_iteration(
        event_input=ei_habitat,
        build_spec=raw["build_spec"],
        iteration_index=iteration_idx,
    )
    raw["build_spec"] = build_spec_with_effective_habitat(raw["build_spec"], effective)
    append_graph_run_event(
        ctx.repo,
        gid,
        RunEventType.HABITAT_STRATEGY_ENFORCED,
        {
            "effective": effective,
            "iteration_index": iteration_idx,
            "kmbl_habitat_session": ei_habitat.get("kmbl_habitat_session"),
        },
        thread_id=tid,
    )

    raw, immersive_meta = harden_immersive_planner_output(raw, ei_habitat)
    if immersive_meta is not None:
        raw.setdefault("_kmbl_planner_metadata", {})["immersive_contract_hardening"] = immersive_meta

    prior_fp: str | None = None
    if effective in ("fresh_start", "rebuild_informed") and iteration_idx == 0:
        ws_reset = get_working_staging_for_thread_resilient(
            ctx.repo,
            tid,
            graph_run_id=gid,
            phase="planner_habitat_reset",
            iteration_index=iteration_idx,
        )
        if ws_reset is not None and ws_reset.payload_json:
            prior_fp = fingerprint_working_staging_payload(ws_reset.payload_json)
            ws_reset, _ = clear_working_staging_surface(
                ws_reset, reason=f"orchestrator_{effective}"
            )
            ctx.repo.save_working_staging(ws_reset)
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.HABITAT_SURFACE_CLEARED,
                {
                    "habitat_strategy_effective": effective,
                    "had_prior_payload": bool(prior_fp),
                },
                thread_id=tid,
            )

    try:
        validate_role_output_for_persistence("planner", raw)
    except (ValidationError, ValueError) as e:
        pe = e.errors() if isinstance(e, ValidationError) else None
        msg = (
            "Persist-time validation failed"
            if isinstance(e, ValidationError)
            else str(e)
        )
        detail = contract_validation_failure(
            phase="planner",
            message=msg,
            pydantic_errors=pe,
        )
        _persist_invocation_failure(
            inv=inv,
            raw_detail=detail,
            phase="planner",
            graph_run_id=gid,
            thread_id=tid,
            repo=ctx.repo,
        )
    else:
        h = raw.get("_kmbl_planner_metadata", {}).get("interactive_build_spec_hardening")
        ih = raw.get("_kmbl_planner_metadata", {}).get("immersive_contract_hardening")
        if (isinstance(h, dict) and h.get("interactive_vertical")) or isinstance(ih, dict):
            payload: dict[str, Any] = {}
            if isinstance(h, dict):
                payload["hardening"] = h
            if isinstance(ih, dict):
                payload["immersive_contract_hardening"] = ih
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.INTERACTIVE_BUILD_SPEC_NORMALIZED,
                payload,
                thread_id=tid,
            )

    ctx.repo.save_role_invocation(inv)
    spec = normalize_planner_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        planner_invocation_id=inv.role_invocation_id,
    )
    spec = spec.model_copy(update={"raw_payload_json": raw})
    # Sequential PostgREST writes — no cross-call rollback on Supabase (see RPC helpers for atomicity).
    ctx.repo.save_build_spec(spec)
    step_state = {
        **dict(state),
        "build_spec": raw.get("build_spec"),
        "build_spec_id": str(spec.build_spec_id),
    }
    _save_checkpoint_with_event(
        ctx.repo,
        CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="post_step",
            state_json=step_state,
            context_compaction_json=None,
        ),
    )
    append_graph_run_event(
        ctx.repo,
        gid,
        RunEventType.PLANNER_INVOCATION_COMPLETED,
        {"build_spec_id": str(spec.build_spec_id)},
    )

    # Planner type-selection observability: log why the planner chose the vertical it did.
    _bs_final = raw.get("build_spec") if isinstance(raw.get("build_spec"), dict) else {}
    _md_final = raw.get("_kmbl_planner_metadata") if isinstance(raw.get("_kmbl_planner_metadata"), dict) else {}
    _planner_type = str(_bs_final.get("type") or "").strip() or "unset"
    _vertical_event: dict[str, Any] = {
        "build_spec_type": _planner_type,
        "experience_mode": str(_bs_final.get("experience_mode") or ""),
        "surface_type": str(_bs_final.get("surface_type") or ""),
        "site_archetype": str(_bs_final.get("site_archetype") or ""),
        "experience_mode_derived": bool(_md_final.get("experience_mode_derived")),
        "experience_mode_source": str(_md_final.get("experience_mode_source") or "planner_authored"),
        "experience_confidence": _md_final.get("experience_confidence"),
        "has_creative_brief": isinstance(_bs_final.get("creative_brief"), dict),
        "has_execution_contract": isinstance(_bs_final.get("execution_contract"), dict),
        "kmbl_frontend_vertical_policy": (
            ei.get("constraints", {}).get("kmbl_frontend_vertical_policy")
            if isinstance(ei.get("constraints"), dict)
            else None
        ),
    }
    append_graph_run_event(
        ctx.repo,
        gid,
        RunEventType.PLANNER_VERTICAL_SELECTED,
        _vertical_event,
        thread_id=tid,
    )

    return {
        "build_spec": raw.get("build_spec"),
        "build_spec_id": str(spec.build_spec_id),
        "habitat_prior_static_fingerprint": prior_fp if iteration_idx == 0 else None,
        "orchestrator_habitat_strategy_effective": effective,
    }


def _hoist_selected_urls_into_build_spec(raw: dict[str, Any]) -> None:
    """Merge top-level ``selected_urls`` into ``build_spec.selected_urls``.

    The planner contract allows ``selected_urls`` at the top level of the
    output *or* inside ``build_spec``.  Downstream evidence resolution only
    looks at ``build_spec``, so we merge here to keep a single extraction
    path.  Deduplication preserves order (first occurrence wins).
    """
    top_urls = raw.get("selected_urls")
    if not isinstance(top_urls, list):
        return

    bs = raw.get("build_spec")
    if not isinstance(bs, dict):
        return

    existing = bs.get("selected_urls")
    if not isinstance(existing, list):
        existing = []

    seen: set[str] = set(existing)
    merged = list(existing)
    for u in top_urls:
        if isinstance(u, str) and u not in seen:
            seen.add(u)
            merged.append(u)

    bs["selected_urls"] = merged
