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
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
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

    payload = {
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
    }
    t_pl = time.perf_counter()
    try:
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.kiloclaw_planner_config_key,
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
    norm_bs, normalized_fields = normalize_build_spec_for_persistence(raw["build_spec"])
    raw["build_spec"] = norm_bs
    if normalized_fields:
        md = raw.setdefault("_kmbl_planner_metadata", {})
        md["normalized_missing_fields"] = normalized_fields

    # Ensure experience_mode is always explicitly set in build_spec.
    # If the planner set it, we respect it; otherwise, derive from structured identity.
    bs = raw["build_spec"]
    existing_mode = bs.get("experience_mode")
    if not isinstance(existing_mode, str) or not existing_mode.strip():
        from kmbl_orchestrator.identity.profile import (
            StructuredIdentityProfile,
            derive_experience_mode,
        )
        si_payload = state.get("structured_identity")
        if si_payload and isinstance(si_payload, dict):
            si = StructuredIdentityProfile.model_validate(si_payload)
        else:
            si = StructuredIdentityProfile()
        derived_mode = derive_experience_mode(
            si, site_archetype=bs.get("site_archetype"),
        )
        bs["experience_mode"] = derived_mode
        md = raw.setdefault("_kmbl_planner_metadata", {})
        md["experience_mode_derived"] = True
        md["experience_mode_source"] = "structured_identity"
        _log.info(
            "graph_run graph_run_id=%s experience_mode derived=%s archetype=%s",
            gid, derived_mode, bs.get("site_archetype"),
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

    ctx.repo.save_role_invocation(inv)
    spec = normalize_planner_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        planner_invocation_id=inv.role_invocation_id,
    )
    spec = spec.model_copy(update={"raw_payload_json": raw})
    with ctx.repo.transaction():
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
