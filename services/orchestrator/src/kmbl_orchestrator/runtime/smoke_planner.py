"""
Local smoke path: one planner HTTP round-trip + persist, no generator/evaluator/staging.

Enable with ORCHESTRATOR_SMOKE_PLANNER_ONLY=true to isolate KiloClaw connectivity and
contract validation without the full LangGraph chain.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.persistence_validate import validate_role_output_for_persistence
from kmbl_orchestrator.contracts.planner_normalize import (
    compact_planner_wire_output,
    normalize_build_spec_for_persistence,
)
from kmbl_orchestrator.domain import CheckpointRecord
from kmbl_orchestrator.identity.hydrate import build_planner_identity_context
from kmbl_orchestrator.normalize import normalize_planner_output
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

_log = logging.getLogger(__name__)


def run_smoke_planner_only(
    *,
    repo: Repository,
    invoker: DefaultRoleInvoker,
    settings: Settings,
    thread_id: str,
    graph_run_id: str,
    event_input: dict[str, Any],
) -> None:
    gid = UUID(graph_run_id)
    tid = UUID(thread_id)
    t0 = time.perf_counter()
    _log.info(
        "smoke_planner_only graph_run_id=%s stage=enter elapsed_ms=0.0",
        graph_run_id,
    )
    append_graph_run_event(
        repo,
        gid,
        RunEventType.PLANNER_INVOCATION_STARTED,
        {"mode": "smoke_planner_only"},
    )
    _log.info(
        "smoke_planner_only graph_run_id=%s stage=planner_invocation_start elapsed_ms=0.0",
        graph_run_id,
    )

    th = repo.get_thread(tid)
    iid = th.identity_id if th else None
    ic = build_planner_identity_context(repo, iid)
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "identity_context": ic,
        "memory_context": {},
        "event_input": event_input or {},
        "current_state_summary": {},
    }
    t_inv = time.perf_counter()
    inv, raw = invoker.invoke(
        graph_run_id=gid,
        thread_id=tid,
        role_type="planner",
        provider_config_key=settings.kiloclaw_planner_config_key,
        input_payload=payload,
        iteration_index=0,
    )
    _log.info(
        "smoke_planner_only graph_run_id=%s stage=planner_invocation_finished elapsed_ms=%.1f",
        graph_run_id,
        (time.perf_counter() - t_inv) * 1000,
    )

    if inv.status == "failed":
        repo.save_role_invocation(inv)
        append_graph_run_event(
            repo,
            gid,
            RunEventType.GRAPH_RUN_FAILED,
            {"mode": "smoke_planner_only", "phase": "planner", "detail": raw},
        )
        repo.update_graph_run_status(gid, "failed", datetime.now(timezone.utc).isoformat())
        _log.error(
            "smoke_planner_only graph_run_id=%s stage=planner_http_or_contract_failed total_elapsed_ms=%.1f",
            graph_run_id,
            (time.perf_counter() - t0) * 1000,
        )
        return

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
        msg = "Persist-time validation failed" if isinstance(e, ValidationError) else str(e)
        detail = contract_validation_failure(
            phase="planner",
            message=msg,
            pydantic_errors=pe,
        )
        ended = datetime.now(timezone.utc).isoformat()
        failed = inv.model_copy(
            update={
                "output_payload_json": detail,
                "status": "failed",
                "ended_at": ended,
            }
        )
        repo.save_role_invocation(failed)
        append_graph_run_event(
            repo,
            gid,
            RunEventType.GRAPH_RUN_FAILED,
            {"mode": "smoke_planner_only", "phase": "planner_persist_validation", "detail": detail},
        )
        repo.update_graph_run_status(gid, "failed", ended)
        _log.error(
            "smoke_planner_only graph_run_id=%s stage=planner_output_validation_failed total_elapsed_ms=%.1f",
            graph_run_id,
            (time.perf_counter() - t0) * 1000,
        )
        return

    repo.save_role_invocation(inv)
    spec = normalize_planner_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        planner_invocation_id=inv.role_invocation_id,
    )
    spec = spec.model_copy(update={"raw_payload_json": raw})
    repo.save_build_spec(spec)

    snap: dict[str, Any] = {
        "graph_run_id": graph_run_id,
        "thread_id": thread_id,
        "iteration_index": 0,
        "build_spec": raw.get("build_spec"),
        "build_spec_id": str(spec.build_spec_id),
        "smoke_planner_only": True,
    }
    repo.attach_run_snapshot(gid, snap)
    repo.save_checkpoint(
        CheckpointRecord(
            checkpoint_id=uuid4(),
            thread_id=tid,
            graph_run_id=gid,
            checkpoint_kind="post_role",
            state_json=snap,
            context_compaction_json=None,
        )
    )
    ended = datetime.now(timezone.utc).isoformat()
    repo.update_graph_run_status(gid, "completed", ended)
    append_graph_run_event(
        repo,
        gid,
        RunEventType.PLANNER_INVOCATION_COMPLETED,
        {"build_spec_id": str(spec.build_spec_id), "mode": "smoke_planner_only"},
    )
    append_graph_run_event(
        repo,
        gid,
        RunEventType.GRAPH_RUN_COMPLETED,
        {"mode": "smoke_planner_only"},
    )
    _log.info(
        "smoke_planner_only graph_run_id=%s stage=response_returning status=completed total_elapsed_ms=%.1f",
        graph_run_id,
        (time.perf_counter() - t0) * 1000,
    )
