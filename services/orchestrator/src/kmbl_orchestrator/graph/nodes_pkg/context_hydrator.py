"""context_hydrator node — hydrate identity context, identity brief, and event input."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from kmbl_orchestrator.graph.state import GraphState
from kmbl_orchestrator.runtime.interrupt_checks import raise_if_interrupt_requested
from kmbl_orchestrator.identity.brief import build_identity_brief_from_repo
from kmbl_orchestrator.identity.crawl_state import (
    build_crawl_context_for_planner,
    get_or_create_crawl_state,
)
from kmbl_orchestrator.identity.sanitize import sanitize_identity_brief_payload
from kmbl_orchestrator.identity.hydrate import build_planner_identity_context
from kmbl_orchestrator.identity.profile import extract_structured_identity
from kmbl_orchestrator.memory.ops import (
    append_memory_event,
    load_cross_run_memory_context,
    maybe_write_identity_derived_memory,
)
from kmbl_orchestrator.runtime.run_events import (
    RunEventType,
    append_graph_run_event,
)
from kmbl_orchestrator.runtime.session_staging_links import (
    merge_session_staging_into_event_input,
)

if TYPE_CHECKING:
    from kmbl_orchestrator.graph.app import GraphContext

_log = logging.getLogger(__name__)


def context_hydrator(ctx: "GraphContext", state: GraphState) -> dict[str, Any]:
    """Hydrate identity context, identity brief, structured identity, and event input for the run."""
    raise_if_interrupt_requested(
        ctx.repo,
        UUID(str(state["graph_run_id"])),
        UUID(str(state["thread_id"])),
    )
    iid_raw = state.get("identity_id")
    identity_brief_payload: dict[str, Any] | None = None
    structured_identity_payload: dict[str, Any] | None = None
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
                identity_brief_payload = sanitize_identity_brief_payload(
                    brief.to_generator_payload()
                )

            # Build structured identity profile for intent-driven planning.
            # This provides themes, tone, visual_tendencies, content_types, complexity
            # that inform experience_mode derivation and downstream evaluation.
            seed_data: dict[str, Any] = {}
            profile_data: dict[str, Any] = {}
            profile = ctx.repo.get_identity_profile(iid_uuid)
            sources = ctx.repo.list_identity_sources(iid_uuid)
            if sources:
                latest = sources[0]
                seed_data = dict(latest.metadata_json or {})
                seed_data["raw_text"] = latest.raw_text or ""
            if profile:
                profile_data = dict(profile.facets_json or {})

            structured = extract_structured_identity(
                seed_data=seed_data,
                profile_data=profile_data,
                identity_brief=identity_brief_payload,
            )
            structured_identity_payload = structured.to_dict()
        except Exception as exc:
            _log.warning(
                "identity_context hydration failed identity_id=%s exc_type=%s exc=%s",
                iid_raw,
                type(exc).__name__,
                str(exc)[:200],
            )
            ic = {}
            identity_brief_payload = None
            structured_identity_payload = None
    else:
        ic = state.get("identity_context") or {}
        # Emit visibility event when running without identity — the graph will proceed
        # with empty identity context, but operators should see this explicitly.
        _gid_raw = state.get("graph_run_id")
        _tid_raw = state.get("thread_id")
        if _gid_raw:
            append_graph_run_event(
                ctx.repo,
                UUID(str(_gid_raw)),
                RunEventType.CONTEXT_IDENTITY_ABSENT,
                {
                    "message": "No identity_id provided; identity_brief and structured_identity will be None",
                },
                thread_id=UUID(str(_tid_raw)) if _tid_raw else None,
            )
    # If identity_brief was already set in state (e.g. resume), keep it
    if identity_brief_payload is None:
        identity_brief_payload = state.get("identity_brief")
    if identity_brief_payload is not None:
        identity_brief_payload = sanitize_identity_brief_payload(
            dict(identity_brief_payload) if isinstance(identity_brief_payload, dict) else {}
        )
    if structured_identity_payload is None:
        structured_identity_payload = state.get("structured_identity")

    gid = state.get("graph_run_id")
    tid = state.get("thread_id")
    ei = merge_session_staging_into_event_input(
        ctx.settings,
        state.get("event_input") if isinstance(state.get("event_input"), dict) else None,
        graph_run_id=str(gid) if gid else None,
        thread_id=str(tid) if tid else None,
    )
    base_mc: dict[str, Any] = dict(state.get("memory_context") or {})
    if iid_raw:
        try:
            iid_u = UUID(str(iid_raw))
            gid_u = UUID(str(gid)) if gid else None
            tid_u = UUID(str(tid)) if tid else None
            cross, trace = load_cross_run_memory_context(
                ctx.repo,
                identity_id=iid_u,
                settings=ctx.settings,
                graph_run_id=gid_u,
            )
            base_mc["cross_run"] = cross
            id_write = maybe_write_identity_derived_memory(
                ctx.repo,
                identity_id=iid_u,
                structured_identity=structured_identity_payload,
                settings=ctx.settings,
                graph_run_id=gid_u,
            )
            if gid_u is not None:
                append_memory_event(
                    ctx.repo,
                    graph_run_id=gid_u,
                    thread_id=tid_u,
                    kind="loaded",
                    payload={
                        "memory_keys_read": trace.memory_keys_read,
                        "categories": trace.categories,
                    },
                )
                if id_write is not None:
                    append_memory_event(
                        ctx.repo,
                        graph_run_id=gid_u,
                        thread_id=tid_u,
                        kind="updated",
                        payload={
                            "memory_keys_written": id_write.memory_keys_written,
                            "categories": id_write.categories,
                            "phase": "identity_derived",
                        },
                    )
        except Exception as exc:
            _log.warning(
                "cross_run_memory hydration failed identity_id=%s exc_type=%s exc=%s",
                iid_raw,
                type(exc).__name__,
                str(exc)[:200],
            )
    # Hydrate crawl state for cross-session crawl resumption
    crawl_context: dict[str, Any] | None = None
    if iid_raw:
        try:
            iid_u = UUID(str(iid_raw))
            _identity_url = ei.get("identity_url") if isinstance(ei, dict) else None
            if isinstance(_identity_url, str) and _identity_url.strip():
                crawl_st = get_or_create_crawl_state(
                    ctx.repo, iid_u, _identity_url.strip()
                )
                crawl_context = build_crawl_context_for_planner(crawl_st)
        except Exception as exc:
            _log.warning(
                "crawl_state hydration failed identity_id=%s exc=%s",
                iid_raw,
                str(exc)[:200],
            )

    out: dict[str, Any] = {
        "identity_context": ic,
        "memory_context": base_mc,
        "current_state": state.get("current_state") or {},
        "compacted_context": state.get("compacted_context") or {},
        "event_input": ei,
    }
    if identity_brief_payload is not None and identity_brief_payload:
        out["identity_brief"] = identity_brief_payload
    if structured_identity_payload is not None:
        out["structured_identity"] = structured_identity_payload
    if crawl_context is not None:
        out["event_input"] = dict(out.get("event_input") or {})
        out["event_input"]["crawl_context"] = crawl_context
    return out
