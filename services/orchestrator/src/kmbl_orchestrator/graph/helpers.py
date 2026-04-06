"""Graph helper functions — pre-graph utilities and pure logic.

Extracted from ``graph/app.py`` to reduce module size and improve navigability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.frontend_artifact_roles import is_frontend_file_artifact_role
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    CheckpointRecord,
)
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event
from kmbl_orchestrator.runtime.working_staging_read import (
    get_working_staging_for_thread_resilient,
)

_log = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid4())


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
        if not is_frontend_file_artifact_role(ref.get("role")):
            continue
        if ref.get("language") != "html":
            continue
        path = ref.get("path", "")
        content = ref.get("content", "")
        if isinstance(path, str) and path and isinstance(content, str) and content:
            file_map[path] = content
    return file_map


def _apply_html_blocks_to_candidate(
    repo: Repository,
    cand: BuildCandidateRecord,
    tid: UUID,
    *,
    graph_run_id: UUID | None = None,
) -> BuildCandidateRecord:
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

    out_role = "static_frontend_file_v1"
    if any(
        isinstance(r, dict) and r.get("role") == "interactive_frontend_app_v1"
        for r in raw_refs
    ):
        out_role = "interactive_frontend_app_v1"

    # Get the current working staging HTML for block targets
    if graph_run_id is not None:
        ws = get_working_staging_for_thread_resilient(
            repo,
            tid,
            graph_run_id=graph_run_id,
            phase="html_block_apply",
            iteration_index=0,
        )
    else:
        ws = repo.get_working_staging_for_thread(tid)
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
            "role": out_role,
            "path": path,
            "language": "html",
            "content": html_content,
            "entry_for_preview": True,
            "bundle_id": bundle_id,
        }

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


def _save_checkpoint_with_event(
    repo: Repository,
    record: CheckpointRecord,
) -> None:
    repo.save_checkpoint(record)
    append_graph_run_event(
        repo,
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


def legacy_would_route_to_planner_on_iterate(
    state: dict[str, Any],
    settings: Settings,
) -> bool:
    """Legacy pivot/stagnation policy when ``graph_replan_on_iterate_enabled`` is True."""
    rd = str(state.get("retry_direction") or "").strip()
    if rd in ("pivot_layout", "pivot_palette", "pivot_content", "fresh_start"):
        return True
    thr = int(settings.graph_replan_stagnation_threshold or 0)
    if thr > 0 and rd == "refine":
        stagnation = int((state.get("current_state") or {}).get("stagnation_count", 0))
        if stagnation >= thr:
            return True
    return False


def compute_hard_replan_reason(state: dict[str, Any]) -> str | None:
    """Deterministic replan triggers (new build_spec) — independent of pivot/stagnation heuristics."""
    ei = state.get("event_input") if isinstance(state.get("event_input"), dict) else {}
    cons = ei.get("constraints") if isinstance(ei.get("constraints"), dict) else {}
    if cons.get("kmbl_force_replan") is True:
        return "operator_force_replan"

    ev = state.get("evaluation_report") if isinstance(state.get("evaluation_report"), dict) else {}
    issues = ev.get("issues")
    if isinstance(issues, list):
        for iss in issues:
            if not isinstance(iss, dict):
                continue
            for key in ("type", "id", "criterion"):
                v = iss.get(key)
                if isinstance(v, str) and v.strip().lower() == "build_spec_invalid":
                    return "evaluator_build_spec_invalid"

    bs = state.get("build_spec") if isinstance(state.get("build_spec"), dict) else {}
    bst = (bs.get("type") or "").strip().lower()
    cv_raw = cons.get("canonical_vertical")
    if isinstance(cv_raw, str) and cv_raw.strip():
        if bst and cv_raw.strip().lower() != bst:
            return "canonical_vertical_mismatch"

    # Only when build_spec is present in state but lacks a vertical type (planner output incomplete).
    if isinstance(state.get("build_spec"), dict) and not (bs.get("type") or "").strip():
        return "no_recognized_frontend_surface"

    return None


def resolve_iterate_planner_routing(
    state: dict[str, Any],
    settings: Settings,
) -> tuple[bool, str | None, bool]:
    """Whether iterate routes to planner vs generator-only retry.

    Returns:
        (route_to_planner, replan_reason, planner_skipped_legacy_would_have_replanned)
    """
    hard = compute_hard_replan_reason(state)
    if hard:
        return True, hard, False
    legacy = legacy_would_route_to_planner_on_iterate(state, settings)
    if settings.graph_replan_on_iterate_enabled and legacy:
        return True, "legacy_pivot_or_stagnation", False
    if not settings.graph_replan_on_iterate_enabled and legacy:
        return False, None, True
    return False, None, False


def should_route_to_planner_on_iterate(
    state: dict[str, Any],
    settings: Settings,
) -> bool:
    """True when iterate should re-invoke planner (new build_spec) instead of generator-only retry.

    - **Hard replan** (evaluator build_spec_invalid, vertical mismatch, empty type, operator flag)
      always routes to planner when iterate.
    - **Legacy** (pivot / stagnation) only when ``graph_replan_on_iterate_enabled`` is True.

    See ``docs/OPERATOR_LOOP_AND_IDENTITY.md``.
    """
    route, _, _ = resolve_iterate_planner_routing(state, settings)
    return route


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
