"""context_hydrator node — hydrate identity context, identity brief, and event input."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.identity.brief import build_identity_brief_from_repo
from kmbl_orchestrator.identity.hydrate import build_planner_identity_context
from kmbl_orchestrator.runtime.session_staging_links import (
    merge_session_staging_into_event_input,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def context_hydrator(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Hydrate identity context, identity brief, and event input for the run."""
    raise_if_interrupt_requested(
        ctx.repo,
        UUID(str(state["graph_run_id"])),
        UUID(str(state["thread_id"])),
    )
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
        except Exception as exc:
            _log.warning(
                "identity_context hydration failed identity_id=%s exc_type=%s exc=%s",
                iid_raw,
                type(exc).__name__,
                str(exc)[:200],
            )
            ic = {}
            identity_brief_payload = None
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
