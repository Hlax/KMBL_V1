"""Reduce generator invoke payload size on iteration >= 1 (locked spec + evaluator feedback)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


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
        for k in (
            "kmbl_implementation_reference_cards",
            "kmbl_inspiration_reference_cards",
            "kmbl_planner_observed_reference_cards",
        ):
            payload[k] = []

    after = len(json.dumps(payload, ensure_ascii=False, default=str))
    return max(0, before - after)
