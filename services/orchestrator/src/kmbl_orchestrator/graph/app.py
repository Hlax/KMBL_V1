"""
LangGraph application — minimal v1: thread → context → checkpoint → planner → generator
→ evaluator → decision → (iterate | staging | end).
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any, Literal, cast
from datetime import datetime, timezone
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.normalized_errors import (
    contract_validation_failure,
    error_kind_from_detail,
    staging_integrity_failure,
)
from kmbl_orchestrator.contracts.persistence_validate import (
    validate_role_output_for_persistence,
)
from kmbl_orchestrator.contracts.planner_normalize import (
    compact_planner_wire_output,
    normalize_build_spec_for_persistence,
)
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    CheckpointRecord,
    GraphRunRecord,
    StagingSnapshotRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.errors import RoleInvocationFailed, StagingIntegrityFailed
from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.identity.hydrate import (
    build_planner_identity_context,
    upsert_identity_evolution_signal,
)
from kmbl_orchestrator.identity.brief import build_identity_brief_from_repo
from kmbl_orchestrator.identity.alignment import (
    compute_alignment_trend,
    score_alignment,
    select_retry_direction,
)
from kmbl_orchestrator.normalize import (
    normalize_evaluator_output,
    normalize_generator_output,
    normalize_planner_output,
)
from kmbl_orchestrator.normalize.gallery_strip_harness import (
    merge_gallery_strip_harness_checks,
)
from kmbl_orchestrator.domain import ThreadRecord
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload
from kmbl_orchestrator.staging.duplicate_rejection import apply_duplicate_staging_rejection
from kmbl_orchestrator.staging.integrity import (
    validate_generator_output_for_candidate,
    validate_preview_integrity,
)
from kmbl_orchestrator.staging.working_staging_ops import (
    apply_generator_to_working_staging,
    choose_update_mode,
    choose_update_mode_with_pressure,
    create_pre_rebuild_checkpoint,
    create_staging_checkpoint,
    should_auto_checkpoint,
    should_auto_checkpoint_with_policy,
)
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)
from kmbl_orchestrator.staging.pressure import (
    pressure_evaluation_to_event_payload,
)
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.kilo_model_routing import (
    ImageRouteBudgetExceededError,
    ImageRouteConfigurationError,
    select_generator_provider_config,
)
from kmbl_orchestrator.runtime.evaluation_surface_gate import apply_preview_surface_gate
from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.session_staging_links import (
    merge_session_staging_into_event_input,
    resolve_evaluator_preview_url,
)

_log = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid4())


class GraphContext:
    """Closure dependencies for graph nodes."""

    def __init__(
        self,
        repo: Repository,
        invoker: DefaultRoleInvoker,
        settings: Settings,
    ) -> None:
        self.repo = repo
        self.invoker = invoker
        self.settings = settings


def _extract_html_file_map_from_working_staging(
    ws: Any,
) -> dict[str, str]:
    """Extract ``path → html_content`` from a working_staging record.

    Returns only HTML files so they can be used as block merge targets.
    """
    file_map: dict[str, str] = {}
    if ws is None:
        return file_map
    refs = (
        ws.payload_json.get("artifacts", {}).get("artifact_refs", [])
        if isinstance(ws.payload_json, dict)
        else []
    )
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("role") != "static_frontend_file_v1":
            continue
        if ref.get("language") != "html":
            continue
        path = ref.get("path", "")
        content = ref.get("content", "")
        if isinstance(path, str) and path and isinstance(content, str) and content:
            file_map[path] = content
    return file_map


def _apply_html_blocks_to_candidate(
    ctx: "GraphContext",
    cand: "BuildCandidateRecord",
    tid: UUID,
) -> "BuildCandidateRecord":
    """If the build candidate contains ``html_block_v1`` artifacts, apply them.

    Fetches the current working_staging for ``tid``, applies each block to the
    corresponding HTML file (creating a minimal skeleton if the file doesn't exist
    yet), and returns an updated ``BuildCandidateRecord`` where:

    - The merged ``static_frontend_file_v1`` artifacts are added to ``artifact_refs_json``
      alongside the original ``html_block_v1`` artifacts (kept for provenance).
    - ``working_state_patch_json["block_preview_anchors"]`` lists the applied block
      anchors so the staging snapshot metadata can expose a direct preview link.

    When there are no ``html_block_v1`` artifacts, the candidate is returned unchanged.
    """
    from kmbl_orchestrator.contracts.html_block_artifact_v1 import (
        HtmlBlockArtifactV1,
        normalize_html_block_artifact,
    )
    from kmbl_orchestrator.staging.block_merge import apply_blocks_to_static_files

    raw_refs = list(cand.artifact_refs_json)
    raw_blocks = [r for r in raw_refs if isinstance(r, dict) and r.get("role") == "html_block_v1"]
    if not raw_blocks:
        return cand

    # Validate blocks — skip malformed ones
    blocks: list[HtmlBlockArtifactV1] = []
    for raw in raw_blocks:
        try:
            blocks.append(HtmlBlockArtifactV1.model_validate(raw))
        except Exception as exc:
            _log.warning(
                "graph_run block application: invalid html_block_v1 block_id=%s err=%s",
                raw.get("block_id", "?"),
                exc,
            )

    if not blocks:
        return cand

    # Get the current working staging HTML for block targets
    ws = ctx.repo.get_working_staging_for_thread(tid)
    file_map = _extract_html_file_map_from_working_staging(ws)

    # Apply blocks
    merged_map, anchors = apply_blocks_to_static_files(blocks, file_map)

    if not merged_map:
        _log.info(
            "graph_run block_application: no files were changed (all blocks returned identical content)"
        )
        return cand

    # Build updated artifact_refs:
    # - existing non-block artifacts unchanged
    # - merged static files replace existing ones at the same path (or are added)
    # - original html_block_v1 artifacts retained as provenance
    non_block_refs = [r for r in raw_refs if isinstance(r, dict) and r.get("role") != "html_block_v1"]
    existing_by_path: dict[str, Any] = {}
    for ref in non_block_refs:
        if isinstance(ref, dict):
            p = ref.get("path", "")
            if p:
                existing_by_path[p] = ref

    # Merge new static files
    for path, html_content in merged_map.items():
        # Try to inherit bundle_id from the existing file or the first block targeting this path
        bundle_id: str | None = None
        if path in existing_by_path:
            bundle_id = existing_by_path[path].get("bundle_id")
        if bundle_id is None:
            for blk in blocks:
                if blk.target_path == path and blk.bundle_id:
                    bundle_id = blk.bundle_id
                    break

        existing_by_path[path] = {
            "role": "static_frontend_file_v1",
            "path": path,
            "language": "html",
            "content": html_content,
            "entry_for_preview": True,
            "bundle_id": bundle_id,
        }

    # Other non-static-html artifacts not in merged_map stay unchanged
    other_refs = [
        ref for ref in non_block_refs
        if not (isinstance(ref, dict) and ref.get("path", "") in existing_by_path)
           or not (isinstance(ref, dict) and ref.get("language") == "html")
    ]
    # Build the final list: non-HTML non-block refs + all (updated) static refs + block provenance
    static_refs = list(existing_by_path.values())
    updated_refs = (
        [r for r in non_block_refs if not (isinstance(r, dict) and r.get("path", "") in merged_map)]
        + static_refs
        + raw_blocks  # provenance
    )

    # Record anchors in working_state_patch
    updated_wsp = dict(cand.working_state_patch_json)
    if anchors:
        updated_wsp["block_preview_anchors"] = anchors

    _log.info(
        "graph_run block_application: applied %d block(s) to %d file(s) anchors=%s",
        len(blocks),
        len(merged_map),
        anchors,
    )

    return cand.model_copy(
        update={
            "artifact_refs_json": updated_refs,
            "working_state_patch_json": updated_wsp,
        }
    )


def build_graph_context(
    settings: Settings,
    repo: Repository,
    invoker: DefaultRoleInvoker | None = None,
) -> "GraphContext":
    """Public factory: create a ``GraphContext`` from settings and repo."""
    inv = invoker or DefaultRoleInvoker(settings=settings)
    return GraphContext(repo, inv, settings)


def get_compiled_graph(ctx: "GraphContext"):
    """Public factory: compile and return the LangGraph graph for a given context.

    The returned object supports both ``.invoke()`` (synchronous) and ``.ainvoke()``
    / ``.astream()`` (async) — use the appropriate form depending on your call site.
    """
    return build_compiled_graph(ctx)


def _save_checkpoint_with_event(
    ctx: GraphContext,
    record: CheckpointRecord,
) -> None:
    ctx.repo.save_checkpoint(record)
    append_graph_run_event(
        ctx.repo,
        record.graph_run_id,
        RunEventType.CHECKPOINT_WRITTEN,
        {
            "checkpoint_kind": record.checkpoint_kind,
            "checkpoint_id": str(record.checkpoint_id),
        },
        thread_id=record.thread_id,
    )


def _persist_invocation_failure(
    *,
    inv: Any,
    raw_detail: dict[str, Any],
    phase: Literal["planner", "generator", "evaluator"],
    graph_run_id: UUID,
    thread_id: UUID,
    repo: Repository,
) -> None:
    ended = datetime.now(timezone.utc).isoformat()
    failed = inv.model_copy(
        update={
            "output_payload_json": raw_detail,
            "status": "failed",
            "ended_at": ended,
        }
    )
    repo.save_role_invocation(failed)
    raise RoleInvocationFailed(
        phase=phase,
        graph_run_id=graph_run_id,
        thread_id=thread_id,
        detail=raw_detail,
    )


def compute_evaluator_decision(
    status: str,
    iteration: int,
    max_iterations: int,
) -> tuple[Literal["stage", "iterate", "interrupt"], str | None]:
    """Pure decision logic: maps evaluator status + iteration to a routing decision.

    Alignment scores do **not** affect this branch — see ``docs/19_EVALUATOR_DECISION_POLICY.md``.

    Returns (decision, interrupt_reason).

    - pass: always stage (no retry needed)
    - partial/fail: iterate if under max_iterations, otherwise stage
    - blocked: interrupt (no staging)
    """
    if status == "pass":
        return "stage", None
    if status == "blocked":
        return "interrupt", "evaluator_blocked"
    if status in ("fail", "partial"):
        if iteration < max_iterations:
            return "iterate", None
        return "stage", None
    return "interrupt", "unknown_eval_status"


def maybe_suppress_duplicate_staging(
    decision: Literal["stage", "iterate", "interrupt"],
    interrupt_reason: str | None,
    status: str,
    metrics: dict[str, Any] | None,
) -> tuple[Literal["stage", "iterate", "interrupt"], str | None, bool]:
    """After max iterations, fail+duplicate_rejection would otherwise stage a useless duplicate snapshot."""
    m = metrics if isinstance(metrics, dict) else {}
    if (
        decision == "stage"
        and status == "fail"
        and m.get("duplicate_rejection") is True
    ):
        return "interrupt", "duplicate_output_after_max_iterations", True
    return decision, interrupt_reason, False


def _iteration_plan_extras_from_ws_facts(
    ws_facts: dict[str, Any] | None,
) -> tuple[int, str | None]:
    if not ws_facts:
        return 0, None
    rh = ws_facts.get("revision_history") or {}
    st = int(rh.get("stagnation_count") or 0)
    ps = ws_facts.get("pressure_summary") or {}
    rec = ps.get("recommendation") if isinstance(ps, dict) else None
    return st, str(rec) if rec else None


def build_compiled_graph(ctx: GraphContext):
    def thread_resolver(state: GraphState) -> dict[str, Any]:
        tid = state.get("thread_id") or _uuid()
        gid = state.get("graph_run_id") or _uuid()
        return {"thread_id": tid, "graph_run_id": gid, "status": "running"}

    def context_hydrator(state: GraphState) -> dict[str, Any]:
        iid_raw = state.get("identity_id")
        identity_brief_payload: dict[str, Any] | None = None
        if iid_raw:
            try:
                iid_uuid = UUID(str(iid_raw))
                ic = build_planner_identity_context(
                    ctx.repo, iid_uuid, settings=ctx.settings
                )
                # Build identity_brief independently of what planner will do with ic.
                # This is the fix: identity survives past the planner boundary.
                brief = build_identity_brief_from_repo(ctx.repo, iid_uuid)
                if brief is not None:
                    identity_brief_payload = brief.to_generator_payload()
            except ValueError:
                ic = {}
        else:
            ic = state.get("identity_context") or {}
        # If identity_brief was already set in state (e.g. resume), keep it
        if identity_brief_payload is None:
            identity_brief_payload = state.get("identity_brief")

        gid = state.get("graph_run_id")
        tid = state.get("thread_id")
        ei = merge_session_staging_into_event_input(
            ctx.settings,
            state.get("event_input") if isinstance(state.get("event_input"), dict) else None,
            graph_run_id=str(gid) if gid else None,
            thread_id=str(tid) if tid else None,
        )
        out: dict[str, Any] = {
            "identity_context": ic,
            "memory_context": state.get("memory_context") or {},
            "current_state": state.get("current_state") or {},
            "compacted_context": state.get("compacted_context") or {},
            "event_input": ei,
        }
        if identity_brief_payload is not None:
            out["identity_brief"] = identity_brief_payload
        return out

    def checkpoint_pre(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        cp = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=UUID(state["thread_id"]),
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_graph"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp)
        return {}

    def planner_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_planner"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
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
        }
        t_pl = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key=ctx.settings.kiloclaw_planner_config_key,
            input_payload=payload,
            iteration_index=state.get("iteration_index", 0),
        )
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
        ctx.repo.save_build_spec(spec)
        step_state = {
            **dict(state),
            "build_spec": raw.get("build_spec"),
            "build_spec_id": str(spec.build_spec_id),
        }
        _save_checkpoint_with_event(
            ctx,
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

    def generator_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bsid = state.get("build_spec_id")
        if not bsid:
            raise RuntimeError("build_spec_id required before generator")
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_generator"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
        append_graph_run_event(ctx.repo, gid, RunEventType.GENERATOR_INVOCATION_STARTED, {}, thread_id=tid)
        _log.info(
            "graph_run graph_run_id=%s stage=generator_invocation_start elapsed_ms=0.0",
            gid,
        )

        iteration = int(state.get("iteration_index", 0))
        feedback: Any = None
        if iteration > 0:
            feedback = state.get("evaluation_report")

        ws = ctx.repo.get_working_staging_for_thread(tid)
        ws_facts: dict[str, Any] | None = None

        # On iteration > 0, build facts from the current build_candidate in state
        # so generator sees fresh context from this run's candidate
        ev_status = feedback.get("status") if isinstance(feedback, dict) else None
        ev_issues = feedback.get("issues") if isinstance(feedback, dict) else None

        if iteration > 0 and state.get("build_candidate"):
            # Build facts from in-progress candidate (not stale DB state)
            candidate = state.get("build_candidate") or {}
            candidate_artifacts = candidate.get("artifact_outputs", [])
            artifact_count = len(candidate_artifacts)
            has_html = any(
                a.get("artifact_type") == "static_file" and 
                str(a.get("path", "")).endswith((".html", ".htm"))
                for a in candidate_artifacts
            )
            facts = build_working_staging_facts(
                ws,
                checkpoint_count=0,
                latest_checkpoint_revision=None,
                latest_checkpoint_trigger=None,
                evaluator_status=ev_status,
                evaluator_issues=ev_issues,
                patches_since_rebuild=iteration,
                stagnation_count=(ws.stagnation_count if ws is not None else 0),
            )
            # Override with fresh candidate info
            facts.artifact_inventory.total_count = artifact_count
            facts.artifact_inventory.has_previewable_html = has_html
            facts.iteration_context = {
                "iteration_index": iteration,
                "previous_status": ev_status,
                "issue_count": len(ev_issues) if ev_issues else 0,
            }
            ws_facts = working_staging_facts_to_payload(facts)
        elif ws is not None:
            checkpoints = ctx.repo.list_staging_checkpoints(ws.working_staging_id, limit=5)
            latest_cp = checkpoints[0] if checkpoints else None

            facts = build_working_staging_facts(
                ws,
                checkpoint_count=len(checkpoints),
                latest_checkpoint_revision=latest_cp.revision_at_checkpoint if latest_cp else None,
                latest_checkpoint_trigger=latest_cp.trigger if latest_cp else None,
                evaluator_status=ev_status,
                evaluator_issues=ev_issues,
                patches_since_rebuild=(ws.revision - (ws.last_rebuild_revision or 0)),
                stagnation_count=ws.stagnation_count,
            )
            ws_facts = working_staging_facts_to_payload(facts)

        st_plan, pr_plan = _iteration_plan_extras_from_ws_facts(ws_facts)
        iteration_plan = (
            build_iteration_plan_for_generator(
                feedback,
                stagnation_count=st_plan,
                pressure_recommendation=pr_plan,
            )
            if iteration > 0 and isinstance(feedback, dict)
            else None
        )

        payload = {
            "thread_id": state["thread_id"],
            "build_spec": state.get("build_spec") or {},
            "current_working_state": state.get("current_state") or {},
            "iteration_feedback": feedback,
            "iteration_plan": iteration_plan,
            "event_input": state.get("event_input") or {},
            "working_staging_facts": ws_facts,
            # Fix 1: identity_brief injected directly — survives planner reinterpretation
            "identity_brief": state.get("identity_brief"),
            # Fix 3: retry_context carries orchestrator-selected direction on iterations
            # Generator must use retry_context.retry_direction to determine approach
        }
        # Merge retry_context into iteration_plan when present.
        # In-graph retries: iteration > 0 (evaluator feedback from prior step).
        # Autonomous loop ticks: each run_graph starts at iteration_index 0, but the loop
        # still passes orchestrator retry_context — merge when trigger_type is autonomous_loop.
        rc = state.get("retry_context") or {}
        should_merge_retry_context = bool(rc) and (
            iteration > 0
            or str(state.get("trigger_type") or "") == "autonomous_loop"
        )
        if should_merge_retry_context:
            if payload["iteration_plan"] is None:
                payload["iteration_plan"] = {}
            payload["iteration_plan"] = {**payload["iteration_plan"], **rc}
        try:
            gen_key, routing_meta = select_generator_provider_config(
                ctx.settings,
                build_spec=state.get("build_spec") or {},
                event_input=state.get("event_input") or {},
                generator_payload=payload,
            )
        except (ImageRouteConfigurationError, ImageRouteBudgetExceededError) as e:
            detail = contract_validation_failure(
                phase="generator",
                message=str(e),
                pydantic_errors=None,
            )
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=detail,
            ) from e
        except Exception as e:
            # Catch any other routing configuration errors
            _log.error(
                "generator routing failed unexpectedly: exc_type=%s message=%s",
                type(e).__name__,
                str(e)[:200],
            )
            detail = contract_validation_failure(
                phase="generator",
                message=f"generator routing configuration error: {type(e).__name__}: {e!s}",
                pydantic_errors=None,
            )
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.CONTRACT_WARNING,
                {
                    "role": "generator",
                    "phase": "routing_configuration",
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                },
                thread_id=tid,
            )
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=detail,
            ) from e
        t_gen = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            provider_config_key=gen_key,
            input_payload=payload,
            iteration_index=iteration,
            routing_metadata=routing_meta,
        )
        _log.info(
            "graph_run graph_run_id=%s stage=generator_invocation_finished elapsed_ms=%.1f",
            gid,
            (time.perf_counter() - t_gen) * 1000,
        )
        if inv.status == "failed":
            ctx.repo.save_role_invocation(inv)
            raise RoleInvocationFailed(
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        try:
            validate_generator_output_for_candidate(raw)
        except ValueError as e:
            detail = contract_validation_failure(
                phase="generator",
                message=str(e),
                pydantic_errors=None,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="generator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )
        try:
            validate_role_output_for_persistence("generator", raw)
        except (ValidationError, ValueError) as e:
            _log.warning(
                "generator persist-time validation issue (non-fatal, normalization proceeds): %s", e,
            )
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.CONTRACT_WARNING,
                {
                    "role": "generator",
                    "phase": "persist_validation",
                    "warning": str(e),
                },
                thread_id=tid,
            )

        ctx.repo.save_role_invocation(inv)

        # Get identity_id from state for image generation context
        iid_raw = state.get("identity_id")
        identity_id: UUID | None = None
        if iid_raw:
            try:
                identity_id = UUID(str(iid_raw))
            except (ValueError, TypeError):
                pass

        cand = normalize_generator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=inv.role_invocation_id,
            build_spec_id=UUID(bsid),
            identity_id=identity_id,
            enable_image_generation=ctx.settings.habitat_image_generation_enabled,
        )
        # Emit normalization rescue event when the normalizer had to recover
        rescue_paths = (cand.raw_payload_json or {}).get("_normalization_rescues")
        if rescue_paths:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.NORMALIZATION_RESCUE,
                {
                    "rescue_paths": rescue_paths,
                    "build_candidate_id": str(cand.build_candidate_id),
                },
                thread_id=tid,
            )
            _log.info(
                "graph_run graph_run_id=%s normalization_rescues=%s",
                gid,
                rescue_paths,
            )

        # Apply html_block_v1 artifacts to the current working staging (if any)
        cand = _apply_html_blocks_to_candidate(ctx, cand, tid)

        ctx.repo.save_build_candidate(cand)
        block_anchors = (cand.working_state_patch_json or {}).get("block_preview_anchors") or []
        step_state = {
            **dict(state),
            "build_candidate": {
                "proposed_changes": raw.get("proposed_changes"),
                "artifact_outputs": raw.get("artifact_outputs"),
                "updated_state": raw.get("updated_state"),
                "sandbox_ref": raw.get("sandbox_ref"),
                "preview_url": raw.get("preview_url"),
                "block_anchors": block_anchors if block_anchors else None,
            },
            "build_candidate_id": str(cand.build_candidate_id),
            "current_state": raw.get("updated_state") or state.get("current_state") or {},
        }
        _save_checkpoint_with_event(
            ctx,
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
            RunEventType.GENERATOR_INVOCATION_COMPLETED,
            {"build_candidate_id": str(cand.build_candidate_id)},
        )
        return {
            "build_candidate": step_state["build_candidate"],
            "build_candidate_id": str(cand.build_candidate_id),
            "current_state": step_state["current_state"],
        }

    def evaluator_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bcid = state.get("build_candidate_id")
        bsid = state.get("build_spec_id")
        if not bcid or not bsid:
            raise RuntimeError("build_candidate_id and build_spec_id required before evaluator")
        cp0 = CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="pre_role",
            state_json={**dict(state), "_role_checkpoint_gate": "pre_evaluator"},
            context_compaction_json=None,
        )
        _save_checkpoint_with_event(ctx, cp0)
        append_graph_run_event(ctx.repo, gid, RunEventType.EVALUATOR_INVOCATION_STARTED, {}, thread_id=tid)
        _log.info(
            "graph_run graph_run_id=%s stage=evaluator_invocation_start elapsed_ms=0.0",
            gid,
        )

        spec = ctx.repo.get_build_spec(UUID(bsid))
        if spec is None:
            raise RoleInvocationFailed(
                phase="evaluator",
                detail={
                    "error_kind": "configuration_error",
                    "message": f"build_spec not found for build_spec_id={bsid}",
                },
                thread_id=tid,
            )
        success = spec.success_criteria_json
        targets = spec.evaluation_targets_json

        ws = ctx.repo.get_working_staging_for_thread(tid)
        ws_facts: dict[str, Any] | None = None
        user_rating_context: dict[str, Any] | None = None
        if ws is not None:
            checkpoints = ctx.repo.list_staging_checkpoints(ws.working_staging_id, limit=5)
            latest_cp = checkpoints[0] if checkpoints else None
            facts = build_working_staging_facts(
                ws,
                checkpoint_count=len(checkpoints),
                latest_checkpoint_revision=latest_cp.revision_at_checkpoint if latest_cp else None,
                latest_checkpoint_trigger=latest_cp.trigger if latest_cp else None,
                patches_since_rebuild=(ws.revision - (ws.last_rebuild_revision or 0)),
                stagnation_count=ws.stagnation_count,
            )
            ws_facts = working_staging_facts_to_payload(facts)
        
        # Get user rating context for evaluator
        staging_snapshots = ctx.repo.list_staging_snapshots_for_thread(tid, limit=5)
        for snap in staging_snapshots:
            if snap.user_rating is not None:
                user_rating_context = {
                    "rating": snap.user_rating,
                    "feedback": snap.user_feedback,
                    "rated_at": snap.rated_at,
                    "from_staging_id": str(snap.staging_snapshot_id),
                }
                break

        bc = state.get("build_candidate") if isinstance(state.get("build_candidate"), dict) else {}
        iter_hint = int(state.get("iteration_index", 0))
        prev_ev = state.get("evaluation_report") if iter_hint > 0 else None
        preview_url = resolve_evaluator_preview_url(
            ctx.settings,
            graph_run_id=str(gid),
            thread_id=str(tid),
            build_candidate=bc,
        )
        payload = {
            "thread_id": state["thread_id"],
            "build_candidate": bc,
            "success_criteria": success,
            "evaluation_targets": targets,
            "iteration_hint": iter_hint,
            "working_staging_facts": ws_facts,
            "user_rating_context": user_rating_context,
            # Fix 1+2: identity_brief enables evaluator to produce alignment_report
            "identity_brief": state.get("identity_brief"),
            # Prefer live assembled staging preview for Playwright / visual grounding
            "preview_url": preview_url,
            "iteration_context": {
                "iteration_index": iter_hint,
                "has_previous_evaluation_report": bool(prev_ev),
            },
            # Prior evaluator JSON (same thread run) for visual-delta / sameness checks
            "previous_evaluation_report": prev_ev if iter_hint > 0 else None,
        }
        t_ev = time.perf_counter()
        inv, raw = ctx.invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="evaluator",
            provider_config_key=ctx.settings.kiloclaw_evaluator_config_key,
            input_payload=payload,
            iteration_index=int(state.get("iteration_index", 0)),
        )
        _log.info(
            "graph_run graph_run_id=%s stage=evaluator_invocation_finished elapsed_ms=%.1f",
            gid,
            (time.perf_counter() - t_ev) * 1000,
        )
        if inv.status == "failed":
            ctx.repo.save_role_invocation(inv)
            raise RoleInvocationFailed(
                phase="evaluator",
                graph_run_id=gid,
                thread_id=tid,
                detail=raw,
            )
        try:
            validate_role_output_for_persistence("evaluator", raw)
        except (ValidationError, ValueError) as e:
            pe = e.errors() if isinstance(e, ValidationError) else None
            msg = (
                "Persist-time validation failed"
                if isinstance(e, ValidationError)
                else str(e)
            )
            detail = contract_validation_failure(
                phase="evaluator",
                message=msg,
                pydantic_errors=pe,
            )
            _persist_invocation_failure(
                inv=inv,
                raw_detail=detail,
                phase="evaluator",
                graph_run_id=gid,
                thread_id=tid,
                repo=ctx.repo,
            )

        ctx.repo.save_role_invocation(inv)
        report = normalize_evaluator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=inv.role_invocation_id,
            build_candidate_id=UUID(bcid),
        )
        bc_row = ctx.repo.get_build_candidate(UUID(bcid))
        ev_input = state.get("event_input") or {}
        is_static_vertical = (
            ev_input.get("scenario", "").startswith("kmbl_identity_url_static")
            or (ev_input.get("constraints") or {}).get("canonical_vertical") == "static_frontend_file_v1"
        )
        if bc_row is not None and not is_static_vertical:
            report = merge_gallery_strip_harness_checks(report, bc_row)
        if bc_row is not None:
            prev_ev_status = report.status
            report = apply_duplicate_staging_rejection(
                report,
                bc=bc_row,
                repo=ctx.repo,
                thread_id=tid,
                graph_run_id=gid,
            )
            if (
                prev_ev_status != report.status
                and report.metrics_json.get("duplicate_rejection")
            ):
                append_graph_run_event(
                    ctx.repo,
                    gid,
                    RunEventType.CONTRACT_WARNING,
                    {
                        "kind": "duplicate_static_output",
                        "previous_status": prev_ev_status,
                        "duplicate_of_staging_snapshot_id": report.metrics_json.get(
                            "duplicate_of_staging_snapshot_id"
                        ),
                    },
                    thread_id=tid,
                )
        report = apply_preview_surface_gate(report, is_static_vertical=is_static_vertical)

        # Fix 2: compute alignment score from evaluator output + identity_brief
        identity_brief = state.get("identity_brief")
        alignment_score: float | None = None
        alignment_signals: dict[str, Any] = {}
        if identity_brief:
            cand_artifact_refs: list[Any] = []
            if bc_row is not None:
                cand_artifact_refs = list(bc_row.artifact_refs_json or [])
            alignment_score, alignment_signals = score_alignment(
                metrics=report.metrics_json,
                artifact_refs=cand_artifact_refs,
                identity_brief=identity_brief,
            )
            if alignment_score is not None:
                _log.info(
                    "graph_run graph_run_id=%s alignment_score=%.3f source=%s",
                    gid,
                    alignment_score,
                    alignment_signals.get("source", "unknown"),
                )

        report = report.model_copy(update={
            "raw_payload_json": raw,
            "alignment_score": alignment_score,
            "alignment_signals_json": alignment_signals,
        })
        ctx.repo.save_evaluation_report(report)

        # Update alignment score history in state
        alignment_history: list[dict[str, Any]] = list(
            state.get("alignment_score_history") or []
        )
        if alignment_score is not None:
            alignment_history.append({
                "iteration_index": int(state.get("iteration_index", 0)),
                "score": alignment_score,
            })

        step_state = {
            **dict(state),
            "evaluation_report": {
                "status": report.status,
                "summary": report.summary,
                "issues": report.issues_json,
                "metrics": report.metrics_json,
                "artifacts": report.artifacts_json,
                # Include alignment so decision_router can use it
                "alignment_score": alignment_score,
                "alignment_signals": alignment_signals,
            },
            "evaluation_report_id": str(report.evaluation_report_id),
            "alignment_score_history": alignment_history,
            "last_alignment_score": alignment_score,
        }
        _save_checkpoint_with_event(
            ctx,
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
            RunEventType.EVALUATOR_INVOCATION_COMPLETED,
            {"evaluation_report_id": str(report.evaluation_report_id)},
        )
        return {
            "evaluation_report": step_state["evaluation_report"],
            "evaluation_report_id": str(report.evaluation_report_id),
            "alignment_score_history": step_state["alignment_score_history"],
            "last_alignment_score": step_state["last_alignment_score"],
        }

    def decision_router(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        ev = state.get("evaluation_report") or {}
        status = ev.get("status", "fail")
        iteration = int(state.get("iteration_index", 0))
        max_iter = int(state.get("max_iterations", ctx.settings.graph_max_iterations_default))

        decision, interrupt_reason = compute_evaluator_decision(
            status, iteration, max_iter
        )

        metrics = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
        decision, interrupt_reason, dup_suppressed = maybe_suppress_duplicate_staging(
            decision, interrupt_reason, status, metrics
        )
        if dup_suppressed:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.CONTRACT_WARNING,
                {
                    "kind": "duplicate_staging_suppressed",
                    "message": "Evaluation still duplicate vs prior staging; skipping snapshot",
                },
                thread_id=UUID(state["thread_id"]),
            )

        if status not in ("pass", "partial"):
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.STAGING_SNAPSHOT_BLOCKED,
                {
                    "reason": "evaluator_not_pass",
                    "error_kind": "staging_integrity",
                    "evaluation_status": status,
                },
            )

        out: dict[str, Any] = {"decision": decision}
        if interrupt_reason:
            out["interrupt_reason"] = interrupt_reason

        # Track pass_count for quality-based visibility (currently informational;
        # enables future policy: "require N consecutive passes before staging").
        current_pass_count = int(state.get("pass_count") or 0)
        if status == "pass":
            out["pass_count"] = current_pass_count + 1
        else:
            out["pass_count"] = 0

        # Fix 3: compute retry_direction and retry_context for next iteration.
        # This is orchestrator-owned — the planner receives a concrete direction,
        # not just a request to "do better." The direction is deterministic from
        # alignment trend + evaluator status + stagnation.
        if decision == "iterate":
            next_iteration = iteration + 1
            out["iteration_index"] = next_iteration

            alignment_score: float | None = state.get("last_alignment_score")
            alignment_history: list[dict[str, Any]] = list(
                state.get("alignment_score_history") or []
            )
            alignment_trend = compute_alignment_trend(alignment_history)
            stagnation = int(
                (state.get("current_state") or {}).get("stagnation_count", 0)
            )
            prior_direction: str | None = state.get("retry_direction")

            retry_dir = select_retry_direction(
                alignment_score=alignment_score,
                alignment_trend=alignment_trend,
                evaluator_status=status,
                iteration_index=iteration,
                stagnation_count=stagnation,
                prior_direction=prior_direction,
            )
            out["retry_direction"] = retry_dir

            # Extract failed criteria IDs from issues for planner context
            issues = ev.get("issues") or []
            failed_criteria = [
                iss.get("type") or iss.get("id") or iss.get("criterion")
                for iss in issues
                if isinstance(iss, dict)
            ]
            failed_criteria = [f for f in failed_criteria if f][:8]

            retry_context: dict[str, Any] = {
                "retry_direction": retry_dir,
                "iteration_strategy": retry_dir,  # mirrors iteration_plan key
                "prior_alignment_score": alignment_score,
                "alignment_trend": alignment_trend,
                "failed_criteria_ids": failed_criteria,
                "iteration_index": next_iteration,
                "orchestrator_note": (
                    f"Direction selected by orchestrator based on alignment_trend={alignment_trend} "
                    f"status={status} iteration={iteration}. "
                    f"This is binding — use {retry_dir} strategy."
                ),
            }
            out["retry_context"] = retry_context

            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.ITERATION_STARTED,
                {
                    "iteration_index": next_iteration,
                    "previous_status": status,
                    "max_iterations": max_iter,
                    "retry_direction": retry_dir,
                    "alignment_score": alignment_score,
                    "alignment_trend": alignment_trend,
                },
            )
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.DECISION_MADE,
            {
                "decision": decision,
                "interrupt_reason": interrupt_reason,
                "pass_count": out["pass_count"],
                "evaluation_status": status,
                "retry_direction": out.get("retry_direction"),
                "last_alignment_score": state.get("last_alignment_score"),
            },
        )
        return out

    def staging_node(state: GraphState) -> dict[str, Any]:
        gid = UUID(state["graph_run_id"])
        tid = UUID(state["thread_id"])
        bcid_s = state.get("build_candidate_id")
        erid_s = state.get("evaluation_report_id")
        bsid_s = state.get("build_spec_id")
        if not bcid_s or not erid_s or not bsid_s:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="staging_integrity",
                message="staging_node requires build_candidate_id, evaluation_report_id, build_spec_id",
                detail={"stage": "staging_node"},
            )
        bc = ctx.repo.get_build_candidate(UUID(bcid_s))
        ev = ctx.repo.get_evaluation_report(UUID(erid_s))
        if bc is None or ev is None:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="persistence_error",
                message="could not load build_candidate or evaluation_report for staging",
                detail={
                    "build_candidate_id": bcid_s,
                    "evaluation_report_id": erid_s,
                },
            )
        if ev.status not in ("pass", "partial", "fail"):
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.STAGING_SNAPSHOT_BLOCKED,
                {
                    "reason": "staging_integrity",
                    "error_kind": "staging_integrity",
                    "evaluation_status": ev.status,
                },
            )
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="staging_integrity",
                message="evaluation_report.status must be pass, partial, or fail to stage (blocked is not stageable)",
                detail={"evaluation_status": ev.status},
            )
        try:
            validate_preview_integrity(bc, ev)
        except ValueError as e:
            append_graph_run_event(
                ctx.repo,
                gid,
                RunEventType.STAGING_SNAPSHOT_BLOCKED,
                {
                    "reason": "preview_integrity",
                    "error_kind": "staging_integrity",
                    "message": str(e),
                },
            )
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="preview_integrity",
                message=str(e),
                detail={"build_candidate_id": str(bc.build_candidate_id)},
            ) from e
        thread = ctx.repo.get_thread(tid)
        if thread is None:
            raise StagingIntegrityFailed(
                graph_run_id=gid,
                thread_id=tid,
                reason="persistence_error",
                message="thread not found for staging_snapshot",
                detail={"thread_id": str(tid)},
            )
        spec = ctx.repo.get_build_spec(UUID(bsid_s))
        t_st = time.perf_counter()

        # --- Working staging path (primary) ---
        ws = ctx.repo.get_working_staging_for_thread(tid)

        mode, pressure_eval, mode_reason = choose_update_mode_with_pressure(
            ws, ev.status, evaluation_issue_count=len(ev.issues_json)
        )

        if ws is None:
            ws = WorkingStagingRecord(
                working_staging_id=uuid4(),
                thread_id=tid,
                identity_id=thread.identity_id,
            )

        before_snapshot = copy.deepcopy(ws)

        pressure_score = pressure_eval.pressure_score if pressure_eval else 0.0
        if mode == "rebuild" and ws.revision > 0:
            pre_cp = create_pre_rebuild_checkpoint(
                ws, source_graph_run_id=gid, pressure_score=pressure_score,
            )
            if pre_cp:
                ctx.repo.save_staging_checkpoint(pre_cp)
                ws.current_checkpoint_id = pre_cp.staging_checkpoint_id
                append_graph_run_event(
                    ctx.repo, gid,
                    RunEventType.WORKING_STAGING_CHECKPOINT_CREATED,
                    {
                        "staging_checkpoint_id": str(pre_cp.staging_checkpoint_id),
                        "trigger": pre_cp.trigger,
                        "reason_category": pre_cp.reason_category,
                    },
                )

        ws = apply_generator_to_working_staging(
            working_staging=ws,
            build_candidate=bc,
            evaluation_report=ev,
            build_spec=spec,
            mode=mode,
            mode_reason_category=mode_reason,
            pressure_evaluation=pressure_eval,
        )

        trigger, reason = should_auto_checkpoint_with_policy(
            before_snapshot, ws, mode, pressure_score=pressure_score,
        )
        if trigger:
            post_cp = create_staging_checkpoint(
                ws, trigger=trigger, source_graph_run_id=gid, reason=reason,
            )
            ctx.repo.save_staging_checkpoint(post_cp)
            ws.current_checkpoint_id = post_cp.staging_checkpoint_id
            append_graph_run_event(
                ctx.repo, gid,
                RunEventType.WORKING_STAGING_CHECKPOINT_CREATED,
                {
                    "staging_checkpoint_id": str(post_cp.staging_checkpoint_id),
                    "trigger": trigger,
                    "reason_category": reason.category if reason else None,
                },
            )

        # Persist alignment score on working staging for trend detection
        alignment_score_for_ws: float | None = state.get("last_alignment_score")
        if alignment_score_for_ws is not None:
            ws.last_alignment_score = alignment_score_for_ws

        ctx.repo.save_working_staging(ws)

        event_payload: dict[str, Any] = {
            "working_staging_id": str(ws.working_staging_id),
            "mode": mode,
            "mode_reason": mode_reason,
            "revision": ws.revision,
            "status": ws.status,
            "thread_id": str(tid),
            "build_candidate_id": str(bc.build_candidate_id),
            "stagnation_count": ws.stagnation_count,
        }
        if pressure_eval:
            event_payload["pressure"] = pressure_evaluation_to_event_payload(pressure_eval)
        if ws.last_revision_summary_json:
            event_payload["revision_summary"] = ws.last_revision_summary_json

        append_graph_run_event(
            ctx.repo, gid,
            RunEventType.WORKING_STAGING_UPDATED,
            event_payload,
        )

        # --- Legacy snapshot path (backward compat) ---
        prior_on_thread = ctx.repo.list_staging_snapshots_for_thread(tid, limit=1)
        prior_staging_id: UUID | None = (
            prior_on_thread[0].staging_snapshot_id if prior_on_thread else None
        )

        payload = build_staging_snapshot_payload(
            build_candidate=bc,
            evaluation_report=ev,
            thread=thread,
            build_spec=spec,
            prior_staging_snapshot_id=prior_staging_id,
        )
        ssid = uuid4()
        snap = StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=bc.thread_id,
            build_candidate_id=bc.build_candidate_id,
            graph_run_id=bc.graph_run_id,
            identity_id=thread.identity_id,
            prior_staging_snapshot_id=prior_staging_id,
            snapshot_payload_json=payload,
            preview_url=bc.preview_url,
            status="review_ready",
        )
        ctx.repo.save_staging_snapshot(snap)
        append_graph_run_event(
            ctx.repo,
            gid,
            RunEventType.STAGING_SNAPSHOT_CREATED,
            {
                "staging_snapshot_id": str(ssid),
                "graph_run_id": str(gid),
                "thread_id": str(tid),
                "build_candidate_id": str(bc.build_candidate_id),
                "reason": "snapshot_persisted",
                "review_ready": True,
                "preview_url": bc.preview_url,
                "prior_staging_snapshot_id": str(prior_staging_id)
                if prior_staging_id is not None
                else None,
            },
        )

        # --- Evaluator → identity feedback loop ---
        # Upsert evaluation signals back into identity_profile so future planner
        # invocations on the same identity receive richer context about what has
        # and hasn't worked across runs.
        if thread.identity_id is not None:
            try:
                upsert_identity_evolution_signal(
                    ctx.repo,
                    thread.identity_id,
                    graph_run_id=gid,
                    evaluation_status=ev.status,
                    evaluation_summary=ev.summary or "",
                    issue_count=len(ev.issues_json),
                    staging_snapshot_id=ssid,
                    # Fix 2: alignment score is now part of the evolution signal
                    alignment_score=ev.alignment_score,
                )
                append_graph_run_event(
                    ctx.repo,
                    gid,
                    RunEventType.IDENTITY_FEEDBACK_UPSERT,
                    {
                        "identity_id": str(thread.identity_id),
                        "evaluation_status": ev.status,
                        "issue_count": len(ev.issues_json),
                        "staging_snapshot_id": str(ssid),
                    },
                    thread_id=tid,
                )
            except Exception as fb_exc:
                _log.warning(
                    "identity_feedback_upsert failed (non-fatal) identity_id=%s exc=%s",
                    thread.identity_id,
                    type(fb_exc).__name__,
                )

        _log.info(
            "graph_run graph_run_id=%s stage=staging_done working_staging_id=%s mode=%s revision=%d snapshot_id=%s elapsed_ms=%.1f",
            gid, ws.working_staging_id, mode, ws.revision, ssid,
            (time.perf_counter() - t_st) * 1000,
        )
        return {
            "staging_snapshot_id": str(ssid),
            "working_staging_id": str(ws.working_staging_id),
            "status": "completed",
        }

    def route_after_decision(state: GraphState) -> str:
        d = state.get("decision")
        if d == "iterate":
            return "generator"
        if d == "stage":
            return "staging"
        return "end"

    graph = StateGraph(GraphState)
    graph.add_node("thread_resolver", thread_resolver)
    graph.add_node("context_hydrator", context_hydrator)
    graph.add_node("checkpoint_pre", checkpoint_pre)
    graph.add_node("planner", planner_node)
    graph.add_node("generator", generator_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("decision_router", decision_router)
    graph.add_node("staging", staging_node)

    graph.add_edge(START, "thread_resolver")
    graph.add_edge("thread_resolver", "context_hydrator")
    graph.add_edge("context_hydrator", "checkpoint_pre")
    graph.add_edge("checkpoint_pre", "planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "evaluator")
    graph.add_edge("evaluator", "decision_router")
    graph.add_conditional_edges(
        "decision_router",
        route_after_decision,
        {
            "generator": "generator",
            "staging": "staging",
            "end": END,
        },
    )
    graph.add_edge("staging", END)
    return graph.compile()


def run_graph(
    *,
    repo: Repository,
    invoker: DefaultRoleInvoker | None = None,
    settings: Settings | None = None,
    initial: GraphState | None = None,
) -> GraphState:
    """
    Compile and invoke the LangGraph runtime (single-threaded).

    **Invariant:** the ``graph_run_id`` (and thread) must already exist in the
    repository. Call :func:`persist_graph_run_start` first. The public
    ``POST /orchestrator/runs/start`` handler persists first, then (asynchronously)
    invokes this — do not call ``run_graph`` with arbitrary IDs or you will hit
    FK errors / the guard below.

    Checkpoint ``state_json`` can grow; compaction/splitting is a later concern.
    """
    settings = settings or get_settings()
    invoker = invoker or DefaultRoleInvoker(settings=settings)
    ctx = GraphContext(repo, invoker, settings)
    app = build_compiled_graph(ctx)
    base: GraphState = {
        "iteration_index": 0,
        "max_iterations": settings.graph_max_iterations_default,
        "trigger_type": "prompt",
        "event_input": {},
    }
    if initial:
        base.update(initial)
    gid0 = base.get("graph_run_id")
    if gid0 and repo.get_graph_run(UUID(str(gid0))) is None:
        raise RuntimeError(
            "graph_run not found — call persist_graph_run_start() before run_graph() "
            "so thread and graph_run rows exist."
        )
    t_run = time.perf_counter()
    _log.info(
        "run_graph graph_run_id=%s stage=langgraph_invoke_start elapsed_ms=0.0",
        gid0,
    )
    try:
        final = app.invoke(base)
    except RoleInvocationFailed as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_u = e.thread_id
            ek = error_kind_from_detail(e.detail) or "role_invocation"
            _save_checkpoint_with_event(
                ctx,
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": ek,
                            "error_message": str(
                                e.detail.get("message", "role invocation failed")
                            ),
                            "failure": e.detail,
                            "failure_phase": e.phase,
                        }
                    },
                    context_compaction_json=None,
                ),
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.GRAPH_RUN_FAILED,
                {"phase": e.phase, "error_kind": ek},
            )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    except StagingIntegrityFailed as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_u = e.thread_id
            failure = staging_integrity_failure(
                reason=e.reason,
                message=e.message,
                details=e.detail if e.detail else None,
            )
            _save_checkpoint_with_event(
                ctx,
                CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=tid_u,
                    graph_run_id=gid_u,
                    checkpoint_kind="interrupt",
                    state_json={
                        "orchestrator_error": {
                            "error_kind": "staging_integrity",
                            "error_message": e.message,
                            "failure": failure,
                            "staging_reason": e.reason,
                        }
                    },
                    context_compaction_json=None,
                ),
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.GRAPH_RUN_FAILED,
                {
                    "error_kind": "staging_integrity",
                    "staging_reason": e.reason,
                },
            )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise
    except Exception as e:
        if gid0:
            gid_u = UUID(str(gid0))
            tid_s = base.get("thread_id")
            if tid_s:
                tid_u = UUID(str(tid_s))
                _save_checkpoint_with_event(
                    ctx,
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
                    ),
                )
                append_graph_run_event(
                    repo,
                    gid_u,
                    RunEventType.GRAPH_RUN_FAILED,
                    {"error_kind": "graph_error"},
                )
            repo.update_graph_run_status(
                gid_u,
                "failed",
                datetime.now(timezone.utc).isoformat(),
            )
        raise

    # --- Post-invoke success path (wrapped for resilience) ---
    assert isinstance(final, dict)
    gid = final.get("graph_run_id")
    if gid:
        tid_s = final.get("thread_id")
        gid_u = UUID(gid)
        tid_u = UUID(tid_s) if tid_s else None
        try:
            if tid_s:
                post = CheckpointRecord(
                    checkpoint_id=uuid4(),
                    thread_id=UUID(tid_s),
                    graph_run_id=gid_u,
                    checkpoint_kind="post_role",
                    state_json=dict(final),
                    context_compaction_json=None,
                )
                _save_checkpoint_with_event(ctx, post)
                repo.update_thread_current_checkpoint(UUID(tid_s), post.checkpoint_id)
            ended = datetime.now(timezone.utc).isoformat()
            repo.update_graph_run_status(gid_u, "completed", ended)
            repo.attach_run_snapshot(gid_u, dict(final))
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.GRAPH_RUN_COMPLETED,
                {},
                thread_id=tid_u,
            )
        except Exception as post_exc:
            _log.exception(
                "run_graph post-invoke persistence failed graph_run_id=%s exc=%s",
                gid,
                type(post_exc).__name__,
            )
            append_graph_run_event(
                repo,
                gid_u,
                RunEventType.POST_INVOKE_FAILURE,
                {"error": f"{type(post_exc).__name__}: {post_exc}"},
                thread_id=tid_u,
            )
            try:
                repo.update_graph_run_status(
                    gid_u,
                    "failed",
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                _log.exception(
                    "run_graph failed to mark run as failed graph_run_id=%s", gid
                )
            raise
    _log.info(
        "run_graph graph_run_id=%s stage=response_returning elapsed_ms=%.1f",
        final.get("graph_run_id", gid0),
        (time.perf_counter() - t_run) * 1000,
    )
    return final  # type: ignore[return-value]


def persist_graph_run_start(
    repo: Repository,
    *,
    thread_id: str | None,
    graph_run_id: str | None,
    identity_id: str | None,
    trigger_type: str,
    event_input: dict[str, Any],
) -> tuple[str, str]:
    """Ensure thread + graph_run rows exist; return (thread_id, graph_run_id)."""
    t0 = time.perf_counter()
    tid = thread_id or _uuid()
    gid = graph_run_id or _uuid()
    tid_u = UUID(tid)
    repo.ensure_thread(
        ThreadRecord(
            thread_id=tid_u,
            identity_id=UUID(identity_id) if identity_id else None,
            thread_kind="build",
            status="active",
        )
    )
    _log.info(
        "persist_graph_run_start graph_run_id=%s thread_id=%s stage=thread_resolved elapsed_ms=%.1f",
        gid,
        tid,
        (time.perf_counter() - t0) * 1000,
    )
    gr = GraphRunRecord(
        graph_run_id=UUID(gid),
        thread_id=tid_u,
        identity_id=UUID(identity_id) if identity_id else None,
        trigger_type=cast(
            Literal[
                "prompt",
                "resume",
                "schedule",
                "system",
                "autonomous_loop",
            ],
            trigger_type,
        ),
        status="running",
    )
    repo.save_graph_run(gr)
    append_graph_run_event(repo, UUID(gid), RunEventType.GRAPH_RUN_STARTED, {}, thread_id=tid_u)
    _log.info(
        "persist_graph_run_start graph_run_id=%s thread_id=%s stage=graph_run_persisted elapsed_ms=%.1f",
        gid,
        tid,
        (time.perf_counter() - t0) * 1000,
    )
    _ = event_input
    return tid, gid
