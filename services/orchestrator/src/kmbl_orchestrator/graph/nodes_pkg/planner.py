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
from kmbl_orchestrator.runtime.static_vertical_invariants import clamp_experience_mode_for_static_vertical
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.memory.ops import memory_bias_for_experience_mode
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


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

    # Build working staging facts for planner's habitat strategy decision
    ws = ctx.repo.get_working_staging_for_thread(tid)
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

    iteration_idx = int(state.get("iteration_index", 0))
    # Crawl context is injected by context_hydrator into event_input
    crawl_context = ei.get("crawl_context") if isinstance(ei, dict) else None
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
        "crawl_context": crawl_context,
    }
    if iteration_idx > 0:
        ev = state.get("evaluation_report") if isinstance(state.get("evaluation_report"), dict) else {}
        bs = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
        payload["replan_context"] = {
            "replan": True,
            "iteration_index": iteration_idx,
            "prior_build_spec_id": state.get("build_spec_id"),
            "prior_evaluation_report": {
                "status": ev.get("status"),
                "summary": ev.get("summary"),
                "issues": ev.get("issues"),
            },
            "retry_context": state.get("retry_context"),
            "prior_build_spec": bs,
        }
    t_pl = time.perf_counter()
    try:
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.openclaw_planner_config_key,
            input_payload=payload,
            iteration_index=state.get("iteration_index", 0),
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
    return {
        "build_spec": raw.get("build_spec"),
        "build_spec_id": str(spec.build_spec_id),
    }
