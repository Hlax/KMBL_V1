"""Reduce generator invoke payload size on iteration >= 1 (locked spec + evaluator feedback)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Keys retained in the slim build_spec sent to the generator on iterations > 0.
# Everything else is redundant once the spec is locked — the digest proves identity.
_BUILD_SPEC_ITERATION_KEYS = frozenset({
    "experience_mode",
    "surface_type",
    "canonical_vertical",
    "success_criteria",
    "literal_success_checks",
    "cool_generation_lane",
    "interaction_model",
    "motion_spec",
    "required_libraries",
    "library_hints",
    "machine_constraints",
    "execution_contract",
    "creative_brief",
    "site_archetype",
})

# Keys retained in prior_build_spec sent to the planner on replan (iteration > 0).
# The planner needs enough context to understand what it planned last time and why
# it needs to change — but not the full creative/crawl blob, which can be very large.
_PLANNER_REPLAN_SPEC_KEYS = frozenset({
    "experience_mode",
    "surface_type",
    "canonical_vertical",
    "site_archetype",
    "success_criteria",
    "evaluation_targets",
    "literal_success_checks",
    "cool_generation_lane",
    "interaction_model",
    "selected_urls",
    "required_libraries",
    "library_hints",
    "machine_constraints",
    "execution_contract",
    "creative_brief",
})


def build_spec_digest(build_spec: dict[str, Any]) -> str:
    raw = json.dumps(build_spec, sort_keys=True, default=str).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def compact_generator_event_input(ei: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("kmbl_session_staging", "identity_url", "constraints", "scenario"):
        if k in ei:
            out[k] = ei[k]
    cc = ei.get("crawl_context")
    if isinstance(cc, dict):
        out["crawl_context_compact"] = {
            "visited_count": cc.get("visited_count"),
            "extracted_fact_digest": cc.get("extracted_fact_digest"),
            "crawl_phase": cc.get("crawl_phase"),
            "grounding_available": cc.get("grounding_available"),
        }
    return out


def compact_structured_identity(si: dict[str, Any]) -> dict[str, Any]:
    return {
        "themes": (si.get("themes") or [])[:6],
        "tone": si.get("tone"),
        "visual_tendencies": (si.get("visual_tendencies") or [])[:8],
        "notable_entities": (si.get("notable_entities") or [])[:6],
        "complexity": si.get("complexity"),
        "_kmbl_compacted": True,
    }


def compact_crawl_context_for_replan(
    crawl_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a compact crawl-context summary for planner replan payloads.

    On iteration > 0, the planner needs to know what's been crawled (counts,
    phase, exhaustion) but not the full per-page summaries, which can be very
    large.  The planner already incorporated crawl content into the prior
    build_spec during iteration 0.
    """
    if not isinstance(crawl_context, dict):
        return crawl_context
    return {
        "visited_count": crawl_context.get("visited_count"),
        "extracted_fact_digest": crawl_context.get("extracted_fact_digest"),
        "crawl_phase": crawl_context.get("crawl_phase"),
        "grounding_available": crawl_context.get("grounding_available"),
        "crawl_exhausted": crawl_context.get("crawl_exhausted"),
        "next_urls_count": len(crawl_context.get("next_urls") or []),
        "_kmbl_compacted": True,
    }


def compact_previous_evaluation_report_for_llm(
    prev_ev: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a slim copy of a prior evaluation report safe for LLM context.

    Strips orchestrator-internal fields (metrics_json blob, raw artifact refs,
    alignment_signals) that the evaluator LLM never uses but that can be very
    large on subsequent iterations.  Only status, summary, a capped issues list,
    and alignment_score are kept.
    """
    if not isinstance(prev_ev, dict):
        return prev_ev
    issues = prev_ev.get("issues")
    return {
        "status": prev_ev.get("status"),
        "summary": prev_ev.get("summary"),
        "issues": issues[:5] if isinstance(issues, list) else [],
        "alignment_score": prev_ev.get("alignment_score"),
        "_kmbl_compacted": True,
    }


def compact_scene_fingerprint_for_prior(
    build_candidate_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Extract compact scene fingerprint data from prior iteration's summary.

    Used to inject prior_candidate_fingerprint into next-iteration payloads so the
    evaluator evolution gate cannot silently skip.  Returns None when summary absent.
    """
    if not isinstance(build_candidate_summary, dict):
        return None
    fp_data = build_candidate_summary.get("scene_fingerprint_data")
    if isinstance(fp_data, dict) and fp_data.get("scene_fingerprint"):
        return fp_data
    # Fallback: minimal fingerprint from basic summary fields
    libs = build_candidate_summary.get("libraries_detected")
    outline = build_candidate_summary.get("sections_or_modules") or {}
    if libs or outline:
        return {
            "scene_fingerprint": "",  # Will be compared by field values
            "library_stack": libs or [],
            "h1_text": outline.get("h1_text", ""),
            "geometry_mode": (build_candidate_summary.get("experience_summary") or {}).get(
                "experience_mode", ""
            ),
        }
    return None


def apply_iteration_compaction(payload: dict[str, Any], iteration: int) -> int:
    """Mutates ``payload`` for iteration >= 1; returns approximate JSON chars saved."""
    if iteration <= 0:
        return 0
    before = len(json.dumps(payload, ensure_ascii=False, default=str))

    ei = payload.get("event_input")
    if isinstance(ei, dict):
        payload["event_input"] = compact_generator_event_input(ei)

    si = payload.get("structured_identity")
    if isinstance(si, dict):
        payload["structured_identity"] = compact_structured_identity(si)

    bs = payload.get("build_spec")
    if isinstance(bs, dict):
        payload["kmbl_locked_build_spec_digest"] = build_spec_digest(bs)
        payload["build_spec"] = {k: v for k, v in bs.items() if k in _BUILD_SPEC_ITERATION_KEYS}

    if "kmbl_interactive_lane_context" in payload:
        ilc = payload.get("kmbl_interactive_lane_context")
        if isinstance(ilc, dict):
            payload["kmbl_interactive_lane_context"] = {
                "lane": ilc.get("lane"),
                "experience_mode": ilc.get("experience_mode"),
                "heavy_webgl_product_mode_requested": ilc.get("heavy_webgl_product_mode_requested"),
                "generator_library_policy": ilc.get("generator_library_policy"),
                "preview_pipeline": ilc.get("preview_pipeline"),
                "iteration_compact": True,
            }
        # Retain a small subset of reference cards on iteration >= 1 so the generator
        # keeps implementation context for iteration; full list is too large.
        _REFERENCE_CARD_CAP = 3
        for k in (
            "kmbl_implementation_reference_cards",
            "kmbl_inspiration_reference_cards",
            "kmbl_planner_observed_reference_cards",
        ):
            cards = payload.get(k)
            if isinstance(cards, list) and len(cards) > _REFERENCE_CARD_CAP:
                payload[k] = cards[:_REFERENCE_CARD_CAP]

    after = len(json.dumps(payload, ensure_ascii=False, default=str))
    return max(0, before - after)
