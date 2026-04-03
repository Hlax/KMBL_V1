"""Cross-run memory orchestration: reads, writes, planner bias."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import IdentityCrossRunMemoryRecord
from kmbl_orchestrator.identity.profile import (
    StructuredIdentityProfile,
    derive_experience_mode_with_confidence,
)
from kmbl_orchestrator.memory.guardrails import (
    cap_delta_negative,
    cap_delta_positive,
    clamp_strength,
    merge_histogram,
)
from kmbl_orchestrator.memory.keys import (
    KEY_AGGREGATE_RUN_OUTCOME,
    KEY_AESTHETIC_TASTE,
    KEY_LIKELY_EXPERIENCE_MODE,
    KEY_PREFERRED_EXPERIENCE_MODE,
    KEY_VISUAL_STYLE_HINTS,
)
from kmbl_orchestrator.memory.models import MemoryReadTrace, MemoryWriteTrace
from kmbl_orchestrator.memory.taste import build_taste_profile, taste_summary_to_prompt_hints
from kmbl_orchestrator.persistence.repository import Repository
from kmbl_orchestrator.runtime.run_events import RunEventType, append_graph_run_event

_log = logging.getLogger(__name__)


def load_cross_run_memory_context(
    repo: Repository,
    *,
    identity_id: UUID,
    settings: Settings,
    graph_run_id: UUID | None = None,
) -> tuple[dict[str, Any], MemoryReadTrace]:
    """Build structured memory_context.cross_run for planner/generator."""
    rows = repo.list_identity_cross_run_memory(
        identity_id, limit=settings.memory_max_keys_per_identity
    )
    trace = MemoryReadTrace(
        identity_id=str(identity_id),
        memory_keys_read=[r.memory_key for r in rows],
        categories=sorted({r.category for r in rows}),
        provenance_notes=[r.provenance for r in rows[:20]],
    )
    taste = build_taste_profile(rows, settings)
    items = [
        {
            "memory_key": r.memory_key,
            "category": r.category,
            "strength": r.strength,
            "provenance": r.provenance,
            "payload_summary": _payload_summary(r.payload_json),
        }
        for r in rows[:40]
    ]
    cross: dict[str, Any] = {
        "taste_summary": taste.model_dump(),
        "prompt_hints": taste_summary_to_prompt_hints(taste),
        "items": items,
        "read_trace": trace.model_dump(),
    }
    if graph_run_id:
        cross["graph_run_id"] = str(graph_run_id)
    return cross, trace


def _payload_summary(pj: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "experience_mode",
        "run_count",
        "last_eval_status",
        "themes",
        "tone",
    )
    return {k: pj[k] for k in keys if k in pj}


def maybe_write_identity_derived_memory(
    repo: Repository,
    *,
    identity_id: UUID,
    structured_identity: dict[str, Any] | None,
    settings: Settings,
    graph_run_id: UUID | None,
) -> MemoryWriteTrace | None:
    """Persist stable identity tendencies when extraction confidence is high enough."""
    if not structured_identity:
        return None
    si = StructuredIdentityProfile.model_validate(structured_identity)
    mode_result = derive_experience_mode_with_confidence(si)
    conf = float(mode_result["experience_confidence"])
    if conf < settings.memory_identity_derive_min_confidence:
        return None
    mode = str(mode_result["experience_mode"])
    now = datetime.now(timezone.utc).isoformat()
    existing = repo.get_identity_cross_run_memory(
        identity_id, "identity_derived", KEY_LIKELY_EXPERIENCE_MODE
    )
    base_strength = 0.35 if existing is None else clamp_strength(
        existing.strength + cap_delta_positive(0.04)
    )
    payload: dict[str, Any] = {
        "experience_mode": mode,
        "extraction_confidence": conf,
        "themes": (si.themes or [])[:8],
        "tone": (si.tone or [])[:8],
        "visual_tendencies": (si.visual_tendencies or [])[:8],
    }
    rec = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=existing.identity_cross_run_memory_id if existing else uuid4(),
        identity_id=identity_id,
        category="identity_derived",
        memory_key=KEY_LIKELY_EXPERIENCE_MODE,
        payload_json=payload,
        strength=base_strength,
        provenance="identity extraction: derive_experience_mode_with_confidence above threshold",
        source_graph_run_id=graph_run_id,
        operator_signal=None,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(rec)

    v_existing = repo.get_identity_cross_run_memory(
        identity_id, "identity_derived", KEY_VISUAL_STYLE_HINTS
    )
    vpayload = {
        "themes": (si.themes or [])[:10],
        "tone": (si.tone or [])[:10],
        "visual_tendencies": (si.visual_tendencies or [])[:10],
    }
    vrec = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=v_existing.identity_cross_run_memory_id if v_existing else uuid4(),
        identity_id=identity_id,
        category="identity_derived",
        memory_key=KEY_VISUAL_STYLE_HINTS,
        payload_json=vpayload,
        strength=clamp_strength(0.3 if v_existing is None else v_existing.strength + 0.02),
        provenance="identity extraction: structured themes/tone/visual_tendencies",
        source_graph_run_id=graph_run_id,
        operator_signal=None,
        created_at=v_existing.created_at if v_existing else now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(vrec)

    return MemoryWriteTrace(
        identity_id=str(identity_id),
        memory_keys_written=[KEY_LIKELY_EXPERIENCE_MODE, KEY_VISUAL_STYLE_HINTS],
        categories=["identity_derived"],
        source_graph_run_id=str(graph_run_id) if graph_run_id else None,
        provenance_notes=[rec.provenance],
    )


def record_run_outcome_memory(
    repo: Repository,
    *,
    graph_run_id: UUID,
    settings: Settings,
    final_state: dict[str, Any],
) -> MemoryWriteTrace | None:
    """Merge compact run outcome into aggregate_run_outcome."""
    gr = repo.get_graph_run(graph_run_id)
    if gr is None or gr.identity_id is None:
        return None
    identity_id = gr.identity_id
    bs = repo.get_latest_build_spec_for_graph_run(graph_run_id)
    ev = repo.get_latest_evaluation_report_for_graph_run(graph_run_id)
    invocations = repo.list_role_invocations_for_graph_run(graph_run_id)
    gen_invs = [r for r in invocations if r.role_type == "generator"]
    events = repo.list_graph_run_events(graph_run_id, limit=500)
    rescue_n = sum(1 for e in events if e.event_type == RunEventType.NORMALIZATION_RESCUE)
    move_types: list[str] = []
    for gi in gen_invs:
        rm = gi.routing_metadata_json or {}
        mt = rm.get("move_type")
        if isinstance(mt, str):
            move_types.append(mt)

    spec = (bs.spec_json if bs else {}) or {}
    if not isinstance(spec, dict):
        spec = {}
    raw_pl = (bs.raw_payload_json if bs else None) or {}
    md = raw_pl.get("_kmbl_planner_metadata") if isinstance(raw_pl, dict) else {}
    if not isinstance(md, dict):
        md = {}
    exp_mode = spec.get("experience_mode")
    if not isinstance(exp_mode, str):
        exp_mode = "flat_standard"
    exp_conf = md.get("experience_confidence")
    try:
        exp_conf_f = float(exp_conf) if exp_conf is not None else 0.4
    except (TypeError, ValueError):
        exp_conf_f = 0.4

    eval_status = ev.status if ev else "unknown"
    align = ev.alignment_score if ev else None
    iter_idx = final_state.get("iteration_index")
    decision = final_state.get("decision")

    existing = repo.get_identity_cross_run_memory(
        identity_id, "run_outcome", KEY_AGGREGATE_RUN_OUTCOME
    )
    now = datetime.now(timezone.utc).isoformat()
    prev: dict[str, Any] = dict(existing.payload_json) if existing else {}
    run_count = int(prev.get("run_count") or 0) + 1
    hist = prev.get("mutation_style_histogram") or {}
    if not isinstance(hist, dict):
        hist = {}
    for mt in move_types:
        hist = merge_histogram(hist, mt, 1.0)

    avoid_patterns: list[str] = list(prev.get("avoid_patterns") or [])
    if eval_status in ("fail", "blocked"):
        delta = cap_delta_negative(-0.08)
        if "rewrite_thrash" not in avoid_patterns and int(iter_idx or 0) >= 3:
            avoid_patterns.append("rewrite_thrash")
    else:
        delta = cap_delta_positive(0.06)

    base_s = 0.25 if existing is None else existing.strength
    new_strength = clamp_strength(base_s + delta)

    payload: dict[str, Any] = {
        "run_count": run_count,
        "last_experience_mode": exp_mode,
        "last_experience_confidence": exp_conf_f,
        "last_eval_status": eval_status,
        "last_alignment_score": align,
        "last_iteration_index": iter_idx,
        "last_decision": decision,
        "normalization_rescue_count_run": rescue_n,
        "mutation_style_histogram": hist,
        "avoid_patterns": avoid_patterns[:20],
    }

    rec = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=existing.identity_cross_run_memory_id if existing else uuid4(),
        identity_id=identity_id,
        category="run_outcome",
        memory_key=KEY_AGGREGATE_RUN_OUTCOME,
        payload_json=payload,
        strength=new_strength,
        provenance="run outcome merge: build_spec + evaluation_report + generator routing signals",
        source_graph_run_id=graph_run_id,
        operator_signal=None,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(rec)
    return MemoryWriteTrace(
        identity_id=str(identity_id),
        memory_keys_written=[KEY_AGGREGATE_RUN_OUTCOME],
        categories=["run_outcome"],
        source_graph_run_id=str(graph_run_id),
        provenance_notes=[rec.provenance],
    )


def record_operator_memory_from_staging_approval(
    repo: Repository,
    *,
    identity_id: UUID,
    graph_run_id: UUID | None,
    staging_snapshot_id: UUID,
    settings: Settings,
) -> MemoryWriteTrace | None:
    """Boost operator_confirmed preferences when staging is approved."""
    now = datetime.now(timezone.utc).isoformat()
    bs: Any = None
    if graph_run_id is not None:
        bs = repo.get_latest_build_spec_for_graph_run(graph_run_id)
    spec = (bs.spec_json if bs else {}) or {}
    if not isinstance(spec, dict):
        spec = {}
    mode = spec.get("experience_mode")
    if not isinstance(mode, str) or not mode.strip():
        mode = "flat_standard"

    existing_pref = repo.get_identity_cross_run_memory(
        identity_id, "operator_confirmed", KEY_PREFERRED_EXPERIENCE_MODE
    )
    base = 0.55 if existing_pref is None else clamp_strength(
        max(existing_pref.strength, 0.55) + 0.12
    )
    rec = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=existing_pref.identity_cross_run_memory_id if existing_pref else uuid4(),
        identity_id=identity_id,
        category="operator_confirmed",
        memory_key=KEY_PREFERRED_EXPERIENCE_MODE,
        payload_json={
            "experience_mode": mode.strip(),
            "staging_snapshot_id": str(staging_snapshot_id),
        },
        strength=clamp_strength(base),
        provenance="operator approved staging snapshot",
        source_graph_run_id=graph_run_id,
        operator_signal="staging_approved",
        created_at=existing_pref.created_at if existing_pref else now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(rec)
    _ = settings  # reserved for future caps
    return MemoryWriteTrace(
        identity_id=str(identity_id),
        memory_keys_written=[KEY_PREFERRED_EXPERIENCE_MODE],
        categories=["operator_confirmed"],
        source_graph_run_id=str(graph_run_id) if graph_run_id else None,
        provenance_notes=[rec.provenance],
    )


def record_operator_memory_from_publication(
    repo: Repository,
    *,
    identity_id: UUID,
    graph_run_id: UUID | None,
    staging_snapshot_id: UUID,
    settings: Settings,
) -> MemoryWriteTrace | None:
    """Stronger operator signal on publication."""
    now = datetime.now(timezone.utc).isoformat()
    bs: Any = None
    if graph_run_id is not None:
        bs = repo.get_latest_build_spec_for_graph_run(graph_run_id)
    spec = (bs.spec_json if bs else {}) or {}
    if not isinstance(spec, dict):
        spec = {}
    mode = spec.get("experience_mode")
    if not isinstance(mode, str) or not mode.strip():
        mode = "flat_standard"

    existing_pref = repo.get_identity_cross_run_memory(
        identity_id, "operator_confirmed", KEY_PREFERRED_EXPERIENCE_MODE
    )
    base = 0.75 if existing_pref is None else clamp_strength(
        max(existing_pref.strength, 0.75) + 0.08
    )
    rec = IdentityCrossRunMemoryRecord(
        identity_cross_run_memory_id=existing_pref.identity_cross_run_memory_id if existing_pref else uuid4(),
        identity_id=identity_id,
        category="operator_confirmed",
        memory_key=KEY_PREFERRED_EXPERIENCE_MODE,
        payload_json={
            "experience_mode": mode.strip(),
            "staging_snapshot_id": str(staging_snapshot_id),
            "publication_mark": True,
        },
        strength=clamp_strength(base),
        provenance="operator published from approved staging",
        source_graph_run_id=graph_run_id,
        operator_signal="publication_created",
        created_at=existing_pref.created_at if existing_pref else now,
        updated_at=now,
    )
    repo.upsert_identity_cross_run_memory(rec)

    snap = repo.get_staging_snapshot(staging_snapshot_id)
    pj = snap.snapshot_payload_json if snap else {}
    themes: list[str] = []
    if isinstance(pj, dict):
        ev = pj.get("evaluation")
        if isinstance(ev, dict):
            th = ev.get("themes") or ev.get("tone_keywords")
            if isinstance(th, list):
                themes = [str(x) for x in th[:8] if isinstance(x, str)]

    if themes:
        aest = repo.get_identity_cross_run_memory(
            identity_id, "operator_confirmed", KEY_AESTHETIC_TASTE
        )
        arec = IdentityCrossRunMemoryRecord(
            identity_cross_run_memory_id=aest.identity_cross_run_memory_id if aest else uuid4(),
            identity_id=identity_id,
            category="operator_confirmed",
            memory_key=KEY_AESTHETIC_TASTE,
            payload_json={"themes": themes},
            strength=clamp_strength(0.6 if aest is None else aest.strength + 0.05),
            provenance="publication: themes from staging snapshot evaluation payload when present",
            source_graph_run_id=graph_run_id,
            operator_signal="publication_created",
            created_at=aest.created_at if aest else now,
            updated_at=now,
        )
        repo.upsert_identity_cross_run_memory(arec)

    _ = settings
    keys = [KEY_PREFERRED_EXPERIENCE_MODE]
    if themes:
        keys.append(KEY_AESTHETIC_TASTE)
    return MemoryWriteTrace(
        identity_id=str(identity_id),
        memory_keys_written=keys,
        categories=["operator_confirmed"],
        source_graph_run_id=str(graph_run_id) if graph_run_id else None,
        provenance_notes=["publication snapshot created"],
    )


def append_memory_event(
    repo: Repository,
    *,
    graph_run_id: UUID,
    thread_id: UUID | None,
    kind: str,
    payload: dict[str, Any],
) -> None:
    et = (
        RunEventType.CROSS_RUN_MEMORY_LOADED
        if kind == "loaded"
        else RunEventType.CROSS_RUN_MEMORY_UPDATED
    )
    append_graph_run_event(repo, graph_run_id, et, payload, thread_id=thread_id)


def memory_bias_for_experience_mode(
    *,
    structured_identity: dict[str, Any] | None,
    taste_summary: dict[str, Any],
    settings: Settings,
) -> tuple[str | None, str | None]:
    """
    If identity confidence is low and operator/taste strongly prefers a mode, return (mode, reason).
    Otherwise (None, None).
    """
    si = structured_identity or {}
    profile = StructuredIdentityProfile.model_validate(si) if si else StructuredIdentityProfile()
    mr = derive_experience_mode_with_confidence(profile)
    ident_conf = float(mr["experience_confidence"])
    if ident_conf > settings.memory_bias_max_identity_confidence:
        return None, None

    ts = taste_summary or {}
    op_mode = ts.get("operator_confirmed_experience_mode")
    op_st = ts.get("operator_confirmed_strength")
    if isinstance(op_mode, str) and op_mode.strip():
        try:
            op_sf = float(op_st) if op_st is not None else 0.8
        except (TypeError, ValueError):
            op_sf = 0.8
        if op_sf >= settings.memory_bias_min_taste_strength:
            return op_mode.strip(), "operator_confirmed_experience_mode"

    fav = ts.get("favored_experience_modes") or []
    if isinstance(fav, list) and fav:
        first = fav[0]
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            mode, eff = first[0], first[1]
            if isinstance(mode, str) and mode.strip():
                try:
                    eff_f = float(eff)
                except (TypeError, ValueError):
                    eff_f = 0.0
                if eff_f >= settings.memory_bias_min_taste_strength:
                    return mode.strip(), "taste_aggregate"

    return None, None
