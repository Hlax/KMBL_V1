"""
Compact LLM payload size telemetry (chars/bytes, section counts) — no raw prompt dumps.

Persisted on ``role_invocation.routing_metadata_json`` under ``kmbl_payload_telemetry_v1``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

RoleTelemetry = Literal["planner", "generator", "evaluator"]

TELEMETRY_VERSION: int = 1

EXECUTION_CONTRACT_GUARDRAILS_V1: dict[str, int] = {
    "execution_contract": 14_000,
    "geometry_system": 4_500,
    "canvas_system": 3_000,
    "lane_mix": 2_000,
    "source_transformation_policy": 2_500,
}


def _json_sizes(payload: dict[str, Any]) -> tuple[int, int]:
    s = json.dumps(payload, ensure_ascii=False, default=str)
    return len(s), len(s.encode("utf-8"))


def _artifact_inline_content_chars(artifacts: list[Any]) -> int:
    n = 0
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        c = a.get("content")
        if isinstance(c, str):
            n += len(c)
    return n


def _full_refs_content_chars(refs: list[dict[str, Any]]) -> int:
    return _artifact_inline_content_chars(refs)


def _snippet_non_empty_count(snippets: dict[str, Any] | None) -> int:
    if not isinstance(snippets, dict):
        return 0
    n = 0
    eh = snippets.get("entry_html")
    if isinstance(eh, str) and eh.strip():
        n += 1
    elif isinstance(eh, dict) and str(eh.get("text") or "").strip():
        n += 1
    for key in ("scripts", "shaders"):
        seq = snippets.get(key)
        if isinstance(seq, list):
            for x in seq:
                if isinstance(x, dict) and str(x.get("text") or "").strip():
                    n += 1
                elif x:
                    n += 1
    return n


def _reference_card_count(payload: dict[str, Any]) -> int:
    keys = (
        "kmbl_implementation_reference_cards",
        "kmbl_inspiration_reference_cards",
        "kmbl_planner_observed_reference_cards",
    )
    total = 0
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            total += len(v)
    return total


def build_payload_telemetry_v1(
    role: RoleTelemetry,
    payload: dict[str, Any],
    *,
    full_artifact_refs_for_compare: list[dict[str, Any]] | None = None,
    payload_budget_notes: str | None = None,
) -> dict[str, Any]:
    """
    Build bounded telemetry dict for ``routing_metadata_json``.

    When ``full_artifact_refs_for_compare`` is set (evaluator path), estimates content-char delta
    vs inline ``build_candidate.artifact_outputs`` (rough; ignores JSON escaping overhead).
    """
    chars, bytes_n = _json_sizes(payload)
    bc = payload.get("build_candidate") if isinstance(payload.get("build_candidate"), dict) else {}
    ao = bc.get("artifact_outputs") if isinstance(bc.get("artifact_outputs"), list) else []
    artifact_output_count = len(ao)
    has_summary = isinstance(bc.get("kmbl_build_candidate_summary_v1"), dict)
    has_summary_v2 = isinstance(bc.get("kmbl_build_candidate_summary_v2"), dict)
    snippets = bc.get("kmbl_evaluator_artifact_snippets_v1")
    snippet_count = _snippet_non_empty_count(snippets if isinstance(snippets, dict) else None)
    omitted = sum(
        1 for x in ao if isinstance(x, dict) and x.get("content_omitted") is True
    )
    inline_chars = _artifact_inline_content_chars(ao)
    full_chars = (
        _full_refs_content_chars(full_artifact_refs_for_compare)
        if full_artifact_refs_for_compare
        else None
    )
    estimated_saved: int | None = None
    summary_replaced = False
    if full_chars is not None and has_summary and artifact_output_count > 0:
        summary_replaced = omitted > 0 or (full_chars > inline_chars)
        estimated_saved = max(0, full_chars - inline_chars)

    notes_parts: list[str] = []
    if payload_budget_notes:
        notes_parts.append(payload_budget_notes.strip())
    if role == "planner" and isinstance(payload.get("replan_context"), dict):
        notes_parts.append("replan_context")
    ref_n = _reference_card_count(payload)

    # Cheap heuristic (~4 chars/token for Latin text); not a real tokenizer.
    rough_token_estimate = max(1, chars // 4)

    ec_sizes: dict[str, int] = {}
    ec_guardrail: dict[str, Any] = {}
    bs = payload.get("build_spec") if isinstance(payload.get("build_spec"), dict) else None
    if isinstance(bs, dict):
        ec = bs.get("execution_contract") if isinstance(bs.get("execution_contract"), dict) else {}
        if ec:
            ec_sizes["execution_contract"] = _json_sizes(ec)[0]
            for key in ("geometry_system", "canvas_system", "lane_mix", "source_transformation_policy"):
                sec = ec.get(key)
                if isinstance(sec, dict):
                    ec_sizes[key] = _json_sizes(sec)[0]
    if ec_sizes:
        over = sorted([
            key
            for key, budget in EXECUTION_CONTRACT_GUARDRAILS_V1.items()
            if int(ec_sizes.get(key) or 0) > budget
        ])
        ec_guardrail = {
            "guardrail_version": 1,
            "section_char_counts": ec_sizes,
            "section_char_budgets": dict(EXECUTION_CONTRACT_GUARDRAILS_V1),
            "over_budget_sections": over,
            "within_budget": len(over) == 0,
        }

    out: dict[str, Any] = {
        "telemetry_version": TELEMETRY_VERSION,
        "role": role,
        "payload_char_count": chars,
        "payload_byte_count": bytes_n,
        "rough_token_estimate": rough_token_estimate,
        "has_build_candidate_summary": has_summary,
        "has_build_candidate_summary_v2": has_summary_v2,
        "artifact_first_payload": bool(has_summary_v2),
        "snippet_non_empty_count": snippet_count,
        "reference_card_count": ref_n,
        "artifact_output_count": artifact_output_count,
        "artifact_outputs_content_omitted_count": omitted,
        "summary_replaced_full_artifacts": summary_replaced,
        "artifact_outputs_inline_content_char_count": inline_chars,
    }
    if ec_guardrail:
        out["execution_contract_size_guardrails_v1"] = ec_guardrail
    if full_chars is not None:
        out["full_artifact_content_char_count"] = full_chars
    if estimated_saved is not None:
        out["estimated_content_chars_saved_vs_full_inline"] = estimated_saved
    if notes_parts:
        out["payload_budget_notes"] = ";".join(notes_parts)[:200]
    return out
