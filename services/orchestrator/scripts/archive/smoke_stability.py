"""
Gallery smoke stability evaluation — compact checklist + verdict + failure bucket.

Used by smoke_common when --validate-stability is set. Not a heavyweight harness.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Final, Literal

_ORCH = Path(__file__).resolve().parents[1]


def _ensure_src_path() -> None:
    src = _ORCH / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


# Primary buckets for failed runs (single layer to fix first).
FAILURE_CATEGORIES: Final[tuple[str, ...]] = (
    "planner_formatting_contract",
    "generator_formatting_contract",
    "evaluator_formatting_contract",
    "supabase_transport_persistence",
    "checkpoint_idempotency",
    "staging_construction",
    "run_detail_read_model",
    "control_plane_ui_only",
    "unknown",
)

StabilityVerdict = Literal["pass", "partial", "fail"]


def _role_statuses(detail_json: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not detail_json:
        return out
    for inv in detail_json.get("role_invocations") or []:
        if not isinstance(inv, dict):
            continue
        rt = inv.get("role_type")
        st = inv.get("status")
        if isinstance(rt, str) and isinstance(st, str):
            out[rt] = st
    return out


def classify_failure(
    *,
    final_status: dict[str, Any] | None,
    detail_json: dict[str, Any] | None,
) -> str:
    """Single primary bucket for a failed terminal run."""
    if not final_status or final_status.get("status") != "failed":
        return "unknown"

    text = ""
    for key in ("error_message", "failure_phase"):
        v = final_status.get(key)
        if v is not None:
            text += f" {v!s}"
    fail = final_status.get("failure")
    if isinstance(fail, dict):
        for k in ("message", "error_kind", "error_type"):
            v = fail.get(k)
            if v is not None:
                text += f" {v!s}"
    text_l = text.lower()

    if "23505" in text or "checkpoint_pkey" in text_l or "duplicate key" in text_l:
        return "checkpoint_idempotency"
    if "remoteprotocolerror" in text_l or "server disconnected" in text_l:
        return "supabase_transport_persistence"
    if "staging" in text_l and "integrity" in text_l:
        return "staging_construction"

    rs = _role_statuses(detail_json)
    if rs.get("planner") == "failed":
        return "planner_formatting_contract"
    if rs.get("generator") == "failed":
        return "generator_formatting_contract"
    if rs.get("evaluator") == "failed":
        return "evaluator_formatting_contract"

    phase = str(final_status.get("failure_phase") or "").lower()
    if phase == "planner":
        return "planner_formatting_contract"
    if phase == "generator":
        return "generator_formatting_contract"
    if phase == "evaluator":
        return "evaluator_formatting_contract"

    if "invalid json" in text_l or "contract" in text_l:
        if "planner" in text_l:
            return "planner_formatting_contract"
        if "generator" in text_l:
            return "generator_formatting_contract"
        if "evaluator" in text_l:
            return "evaluator_formatting_contract"

    return "unknown"


def evaluate_gallery_stability(
    *,
    preset: str,
    start_body: dict[str, Any],
    final_status: dict[str, Any] | None,
    detail_json: dict[str, Any] | None,
    detail_http_status: int | None,
    staging_payload: dict[str, Any] | None,
    staging_fetch_attempted: bool,
    poll_status_codes: list[int],
    log_text: str | None,
) -> dict[str, Any]:
    """
    Build checklist booleans, verdict, optional failure category, notes.

    ``staging_fetch_attempted`` is True when we had a staging_snapshot_id and called the staging API.
    """
    _ensure_src_path()
    from kmbl_orchestrator.runtime.scenario_visibility import (
        gallery_strip_visibility_from_staging_payload,
    )

    is_varied = preset == "seeded_gallery_strip_varied_v1"
    is_gallery = "gallery_strip" in preset

    terminal = (final_status or {}).get("status")
    ei = start_body.get("effective_event_input")
    variation_ok = True
    if is_varied:
        variation_ok = (
            isinstance(ei, dict)
            and isinstance(ei.get("variation"), dict)
            and ei["variation"].get("run_nonce") is not None
        )

    rs = _role_statuses(detail_json)
    roles_ok = (
        rs.get("planner") == "completed"
        and rs.get("generator") == "completed"
        and rs.get("evaluator") == "completed"
    )

    sid = None
    if detail_json and isinstance(detail_json.get("associated_outputs"), dict):
        sid = detail_json["associated_outputs"].get("staging_snapshot_id")
    if not sid and final_status:
        snap = final_status.get("snapshot")
        if isinstance(snap, dict):
            sid = snap.get("staging_snapshot_id")
    staging_present = isinstance(sid, str) and bool(sid)

    detail_ok = detail_http_status == 200
    poll_has_500 = 500 in poll_status_codes

    gv = gallery_strip_visibility_from_staging_payload(staging_payload) if staging_payload else {}
    strip_detected = bool(gv.get("has_gallery_strip"))
    n_items = int(gv.get("gallery_strip_item_count") or 0)
    # Items present; keys/refs optional while image URLs may still be placeholders.
    artifact_linkage_ok = strip_detected and n_items > 0

    log_t = log_text or ""
    retry_observed = "retry attempt=" in log_t and (
        "RemoteProtocolError" in log_t or "err=RemoteProtocolError" in log_t
    )
    recovered_from_retry = retry_observed and terminal == "completed"

    checklist: dict[str, Any] = {
        "preset": preset,
        "final_status": terminal,
        "planner_generator_evaluator_completed": roles_ok,
        "staging_snapshot_present": staging_present,
        "variation_inputs_visible": variation_ok if is_varied else True,
        "run_detail_fetch_ok": detail_ok,
        "poll_no_500": not poll_has_500,
        "gallery_strip_detected": strip_detected,
        "artifact_linkage_coherent": artifact_linkage_ok,
        "retry_errors_recovered": recovered_from_retry or not retry_observed,
    }

    failure_category: str | None = None
    if terminal == "failed":
        failure_category = classify_failure(
            final_status=final_status,
            detail_json=detail_json,
        )

    notes: list[str] = []
    if staging_present and staging_fetch_attempted and staging_payload is None:
        notes.append("staging_snapshot_id present but staging payload GET failed or empty")
    if poll_has_500 and terminal == "completed":
        notes.append("poll saw HTTP 500 at least once but run completed (transient read path)")
    if retry_observed and not recovered_from_retry:
        notes.append("Supabase transport retries logged but run did not complete")

    if not is_gallery:
        stability_check: StabilityVerdict = "fail" if terminal != "completed" else "pass"
        return {
            "checklist": checklist,
            "stability_check": stability_check,
            "failure_category": failure_category,
            "notes": notes,
        }

    if terminal == "failed":
        return {
            "checklist": checklist,
            "stability_check": "fail",
            "failure_category": failure_category or "unknown",
            "notes": notes,
        }

    if terminal != "completed":
        return {
            "checklist": checklist,
            "stability_check": "fail",
            "failure_category": None,
            "notes": notes
            + (["terminal status not completed"] if terminal else ["no terminal status"]),
        }

    # completed — gallery presets
    strict_pass = (
        roles_ok
        and staging_present
        and detail_ok
        and strip_detected
        and artifact_linkage_ok
        and (variation_ok if is_varied else True)
        and not poll_has_500
        and (staging_payload is not None or not staging_fetch_attempted)
    )

    soft_partial = (
        poll_has_500
        or (staging_fetch_attempted and staging_payload is None and staging_present)
        or not strip_detected
        or not artifact_linkage_ok
        or (is_varied and not variation_ok)
        or not roles_ok
    )

    if strict_pass:
        verdict: StabilityVerdict = "pass"
    elif soft_partial and terminal == "completed":
        verdict = "partial"
    else:
        verdict = "fail"

    return {
        "checklist": checklist,
        "stability_check": verdict,
        "failure_category": failure_category,
        "notes": notes,
    }


def print_stability_report(result: dict[str, Any]) -> None:
    """Compact stdout block."""
    print()
    print("========== STABILITY VALIDATION ==========")
    cl = result.get("checklist") or {}
    if "preset" in cl:
        print(f"  preset: {cl['preset']}")
    for k, v in cl.items():
        if k == "preset":
            continue
        print(f"  {k}: {v}")
    print(f"  stability_check: {result.get('stability_check')}")
    fc = result.get("failure_category")
    if fc:
        print(f"  failure_category: {fc}")
    for n in result.get("notes") or []:
        print(f"  note: {n}")
    print("  failure_buckets_ref: " + ", ".join(FAILURE_CATEGORIES))
    print("==========================================")
    print()


def stability_exit_code(result: dict[str, Any]) -> int:
    """Non-zero if validate-stability should fail the process."""
    v = result.get("stability_check")
    if v == "fail":
        return 1
    return 0
