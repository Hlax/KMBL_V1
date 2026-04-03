"""Graph helper functions — pre-graph utilities and pure logic.

Extracted from ``graph/app.py`` to reduce module size and improve navigability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    CheckpointRecord,
)
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

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
    repo: Repository,
    cand: BuildCandidateRecord,
    tid: UUID,
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

    # Get the current working staging HTML for block targets
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
            "role": "static_frontend_file_v1",
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


def should_route_to_planner_on_iterate(
    state: dict[str, Any],
    settings: Settings,
) -> bool:
    """True when iterate should re-invoke planner (new build_spec) instead of generator-only retry.

    - Pivot / fresh_start directions always replan when enabled.
    - Refine + high stagnation replans when ``graph_replan_stagnation_threshold`` > 0.

    See ``docs/OPERATOR_LOOP_AND_IDENTITY.md``.
    """
    if not settings.graph_replan_on_iterate_enabled:
        return False
    rd = str(state.get("retry_direction") or "").strip()
    if rd in ("pivot_layout", "pivot_palette", "pivot_content", "fresh_start"):
        return True
    thr = int(settings.graph_replan_stagnation_threshold or 0)
    if thr > 0 and rd == "refine":
        stagnation = int((state.get("current_state") or {}).get("stagnation_count", 0))
        if stagnation >= thr:
            return True
    return False


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
