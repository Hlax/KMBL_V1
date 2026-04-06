"""
``payload_budget_governor_v1`` — deterministic, budget-aware trimming of role payloads before LLM invoke.

Does not touch persisted artifacts or DB rows; only mutates a deep-copied outbound dict.
Trim decisions are recorded for ``kmbl_payload_telemetry_v1`` (via ``merge_governor_report_into_telemetry``).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

RoleGov = Literal["planner", "generator", "evaluator"]

GOVERNOR_VERSION: int = 1

# Serialized JSON char budgets (rough proxy for prompt size). Tune per deployment if needed.
DEFAULT_CHAR_BUDGET: dict[RoleGov, int] = {
    "planner": 180_000,
    "generator": 220_000,
    "evaluator": 160_000,
}

REF_CARD_KEYS: tuple[str, ...] = (
    "kmbl_implementation_reference_cards",
    "kmbl_inspiration_reference_cards",
    "kmbl_planner_observed_reference_cards",
)


def _measure_chars(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def merge_governor_report_into_telemetry(
    telemetry: dict[str, Any],
    governor_report: dict[str, Any],
) -> dict[str, Any]:
    """Attach compact governor audit under ``payload_governor_v1`` (no raw prompts)."""
    out = dict(telemetry)
    ini = int(governor_report.get("initial_payload_char_count") or 0)
    fin = int(governor_report.get("final_payload_char_count") or 0)
    out["payload_governor_v1"] = {
        "governor_version": governor_report.get("governor_version"),
        "role": governor_report.get("role"),
        "budget_target_chars": governor_report.get("budget_target_chars"),
        "initial_payload_char_count": ini,
        "final_payload_char_count": fin,
        "was_trimmed": bool(governor_report.get("was_trimmed")),
        "trimmed_sections": list(governor_report.get("trimmed_sections") or [])[:48],
        "dropped_reference_count": int(governor_report.get("dropped_reference_count") or 0),
        "dropped_snippet_count": int(governor_report.get("dropped_snippet_count") or 0),
        "dropped_observed_reference_count": int(
            governor_report.get("dropped_observed_reference_count") or 0
        ),
        "chars_saved_by_governor_trim": max(0, ini - fin),
    }
    notes = str(telemetry.get("payload_budget_notes") or "").strip()
    gov_note = "governor_trim" if governor_report.get("was_trimmed") else "governor_ok"
    merged_notes = ";".join(x for x in (notes, gov_note) if x)[:200]
    if merged_notes:
        out["payload_budget_notes"] = merged_notes
    return out


def _cap_list(
    payload: dict[str, Any],
    key: str,
    max_len: int,
    log: list[str],
    dropped_ref: list[int],
    dropped_obs: list[int],
) -> None:
    v = payload.get(key)
    if not isinstance(v, list) or len(v) <= max_len:
        return
    before = len(v)
    payload[key] = v[:max_len]
    dropped = before - max_len
    dropped_ref[0] += dropped
    if "observed" in key:
        dropped_obs[0] += dropped
    log.append(f"{key}:{before}->{max_len}")


def _truncate_strings_in_obj(
    obj: Any,
    max_len: int,
    log: list[str],
    path: str = "",
) -> None:
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and len(v) > max_len:
                obj[k] = v[: max_len - 20] + "\n…[kmbl_truncated]…"
                log.append(f"truncate_str:{p}:{max_len}")
            else:
                _truncate_strings_in_obj(v, max_len, log, p)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _truncate_strings_in_obj(item, max_len, log, f"{path}[{i}]")


def _trim_crawl_context(cc: dict[str, Any], log: list[str], *, next_urls: int, top_each: int) -> None:
    nu = cc.get("next_urls_to_crawl")
    if isinstance(nu, list) and len(nu) > next_urls:
        before = len(nu)
        cc["next_urls_to_crawl"] = nu[:next_urls]
        log.append(f"crawl_context.next_urls_to_crawl:{before}->{next_urls}")
    for key in ("top_identity_pages", "top_inspiration_pages", "recent_page_summaries"):
        seq = cc.get(key)
        if isinstance(seq, list) and len(seq) > top_each:
            before = len(seq)
            cc[key] = seq[:top_each]
            log.append(f"crawl_context.{key}:{before}->{top_each}")


def _clip_evaluator_snippets(
    sn: dict[str, Any],
    *,
    max_entry: int,
    max_script: int,
    max_shader: int,
    max_scripts: int,
    max_shaders: int,
    log: list[str],
    dropped_snip: list[int],
) -> None:
    def clip_text(d: dict[str, Any], field: str, lim: int) -> None:
        t = d.get(field)
        if isinstance(t, str) and len(t) > lim:
            d[field] = t[: max(lim - 25, 40)] + "\n…[kmbl_snip_truncated]…"
            dropped_snip[0] += 1

    eh = sn.get("entry_html")
    if isinstance(eh, dict):
        clip_text(eh, "text", max_entry)
    elif isinstance(eh, str) and len(eh) > max_entry:
        sn["entry_html"] = eh[: max(max_entry - 25, 40)] + "\n…[kmbl_snip_truncated]…"
        dropped_snip[0] += 1

    for key, lim, mcount in (
        ("scripts", max_script, max_scripts),
        ("shaders", max_shader, max_shaders),
    ):
        seq = sn.get(key)
        if not isinstance(seq, list):
            continue
        before = len(seq)
        if before > mcount:
            sn[key] = seq[:mcount]
            log.append(f"snippets.{key}:{before}->{mcount}")
            dropped_snip[0] += before - mcount
        for item in sn[key]:
            if isinstance(item, dict):
                clip_text(item, "text", lim)


def _progressive_ref_caps(
    payload: dict[str, Any],
    cap: int,
    log: list[str],
    dropped_ref: list[int],
    dropped_obs: list[int],
) -> None:
    for key in REF_CARD_KEYS:
        _cap_list(payload, key, cap, log, dropped_ref, dropped_obs)


def _govern_planner(
    payload: dict[str, Any],
    budget: int,
    log: list[str],
    dropped_ref: list[int],
    dropped_obs: list[int],
) -> None:
    # Reference cards: shrink deterministically (observed first is most volatile).
    for cap in (16, 12, 8, 6, 4, 3, 2, 1, 0):
        if _measure_chars(payload) <= budget:
            return
        _cap_list(
            payload,
            "kmbl_planner_observed_reference_cards",
            cap,
            log,
            dropped_ref,
            dropped_obs,
        )
        if _measure_chars(payload) <= budget:
            return
        _cap_list(payload, "kmbl_inspiration_reference_cards", cap, log, dropped_ref, dropped_obs)
        if _measure_chars(payload) <= budget:
            return
        _cap_list(
            payload,
            "kmbl_implementation_reference_cards",
            cap,
            log,
            dropped_ref,
            dropped_obs,
        )

    cc = payload.get("crawl_context")
    if isinstance(cc, dict):
        for nu, tp in ((24, 12), (16, 8), (10, 5), (6, 3), (4, 2)):
            if _measure_chars(payload) <= budget:
                return
            _trim_crawl_context(cc, log, next_urls=nu, top_each=tp)

    for mlen in (6000, 4000, 2500, 1500, 900):
        if _measure_chars(payload) <= budget:
            return
        mc = payload.get("memory_context")
        if isinstance(mc, dict):
            _truncate_strings_in_obj(mc, mlen, log)
        css = payload.get("current_state_summary")
        if isinstance(css, dict):
            _truncate_strings_in_obj(css, mlen, log)

    rc = payload.get("replan_context")
    if isinstance(rc, dict):
        per = rc.get("prior_evaluation_report")
        if isinstance(per, dict):
            issues = per.get("issues")
            if isinstance(issues, list) and len(issues) > 6:
                before = len(issues)
                per["issues"] = issues[:6]
                log.append(f"replan_context.prior_evaluation_report.issues:{before}->6")
            summ = per.get("summary")
            if isinstance(summ, str) and len(summ) > 1200:
                per["summary"] = summ[:1100] + "…[kmbl_truncated]"
                log.append("replan_context.prior_evaluation_report.summary:truncated")

    for cap in (5, 3, 1, 0):
        if _measure_chars(payload) <= budget:
            return
        ui = payload.get("user_interrupts")
        if isinstance(ui, list) and len(ui) > cap:
            before = len(ui)
            payload["user_interrupts"] = ui[:cap]
            log.append(f"user_interrupts:{before}->{cap}")

    ic = payload.get("identity_context")
    if isinstance(ic, dict):
        for mlen in (3000, 1500, 800):
            if _measure_chars(payload) <= budget:
                return
            _truncate_strings_in_obj(ic, mlen, log)

    wsf = payload.get("working_staging_facts")
    if isinstance(wsf, dict):
        for mlen in (2500, 1200):
            if _measure_chars(payload) <= budget:
                return
            _truncate_strings_in_obj(wsf, mlen, log)

    # Last resort: drop bulky optional blobs (planner can still use structured_identity / event_input).
    if _measure_chars(payload) > budget and isinstance(payload.get("crawl_context"), dict):
        payload["crawl_context"] = None
        log.append("crawl_context:removed")
    if _measure_chars(payload) > budget and isinstance(payload.get("memory_context"), dict):
        payload["memory_context"] = {}
        log.append("memory_context:cleared")


def _govern_generator(
    payload: dict[str, Any],
    budget: int,
    log: list[str],
    dropped_ref: list[int],
    dropped_obs: list[int],
    dropped_snip: list[int],
) -> None:
    for cap in (16, 10, 6, 4, 2, 1, 0):
        if _measure_chars(payload) <= budget:
            return
        _progressive_ref_caps(payload, cap, log, dropped_ref, dropped_obs)

    ilc = payload.get("kmbl_interactive_lane_context")
    if isinstance(ilc, dict):
        notes = ilc.get("preview_pipeline_notes")
        if isinstance(notes, list):
            for ncap in (8, 5, 3, 2, 1, 0):
                if _measure_chars(payload) <= budget:
                    return
                if len(notes) > ncap:
                    before = len(notes)
                    ilc["preview_pipeline_notes"] = notes[:ncap]
                    log.append(f"interactive_lane.preview_pipeline_notes:{before}->{ncap}")
                    notes = ilc["preview_pipeline_notes"]

    for mlen in (5000, 3000, 1800, 1000):
        if _measure_chars(payload) <= budget:
            return
        cws = payload.get("current_working_state")
        if isinstance(cws, dict):
            _truncate_strings_in_obj(cws, mlen, log)
        wsf = payload.get("working_staging_facts")
        if isinstance(wsf, dict):
            _truncate_strings_in_obj(wsf, mlen, log)

    ifeed = payload.get("iteration_feedback")
    if isinstance(ifeed, dict):
        for mlen in (4000, 2000, 1000):
            if _measure_chars(payload) <= budget:
                return
            _truncate_strings_in_obj(ifeed, mlen, log)

    hints = payload.get("spatial_translation_hints")
    if isinstance(hints, list) and len(hints) > 12:
        before = len(hints)
        payload["spatial_translation_hints"] = hints[:12]
        log.append(f"spatial_translation_hints:{before}->12")

    ib = payload.get("identity_brief")
    if isinstance(ib, dict):
        for mlen in (2500, 1200):
            if _measure_chars(payload) <= budget:
                return
            for key in ("short_bio", "headings_sample"):
                val = ib.get(key)
                if isinstance(val, str) and len(val) > mlen:
                    ib[key] = val[: mlen - 20] + "…[kmbl_truncated]…"
                    log.append(f"identity_brief.{key}:truncated")

    if _measure_chars(payload) > budget and isinstance(ilc, dict):
        payload["kmbl_interactive_lane_context"] = None
        log.append("kmbl_interactive_lane_context:removed")


def _govern_evaluator(
    payload: dict[str, Any],
    budget: int,
    log: list[str],
    dropped_ref: list[int],
    dropped_obs: list[int],
    dropped_snip: list[int],
) -> None:
    for cap in (14, 10, 6, 4, 2, 1, 0):
        if _measure_chars(payload) <= budget:
            return
        _progressive_ref_caps(payload, cap, log, dropped_ref, dropped_obs)

    hints = payload.get("kmbl_library_compliance_hints")
    if isinstance(hints, list):
        for ncap in (12, 8, 5, 3, 2, 1, 0):
            if _measure_chars(payload) <= budget:
                return
            if len(hints) > ncap:
                before = len(hints)
                payload["kmbl_library_compliance_hints"] = hints[:ncap]
                log.append(f"kmbl_library_compliance_hints:{before}->{ncap}")
                hints = payload["kmbl_library_compliance_hints"]

    prev = payload.get("previous_evaluation_report")
    if isinstance(prev, dict):
        issues = prev.get("issues")
        if isinstance(issues, list) and len(issues) > 8:
            before = len(issues)
            prev["issues"] = issues[:8]
            log.append(f"previous_evaluation_report.issues:{before}->8")
        summ = prev.get("summary")
        if isinstance(summ, str) and len(summ) > 2000:
            prev["summary"] = summ[:1900] + "…[kmbl_truncated]"
            log.append("previous_evaluation_report.summary:truncated")

    ile = payload.get("kmbl_interactive_lane_expectations")
    if isinstance(ile, dict):
        for key in REF_CARD_KEYS:
            _cap_list(ile, key, 6, log, dropped_ref, dropped_obs)

    for mlen in (3000, 2000, 1200):
        if _measure_chars(payload) <= budget:
            return
        wsf = payload.get("working_staging_facts")
        if isinstance(wsf, dict):
            _truncate_strings_in_obj(wsf, mlen, log)
        urc = payload.get("user_rating_context")
        if isinstance(urc, dict):
            _truncate_strings_in_obj(urc, mlen, log)

    # Snippet tiers: preserve kmbl_build_candidate_summary_v1; only shrink snippet dicts.
    bc = payload.get("build_candidate") if isinstance(payload.get("build_candidate"), dict) else {}
    snippet_targets: list[dict[str, Any]] = []
    s1 = bc.get("kmbl_evaluator_artifact_snippets_v1")
    if isinstance(s1, dict):
        snippet_targets.append(s1)
    s2 = payload.get("kmbl_evaluator_artifact_snippets_v1")
    if isinstance(s2, dict) and s2 not in snippet_targets:
        snippet_targets.append(s2)
    tiers = (
        (2200, 1600, 650, 2, 3),
        (1500, 1100, 450, 2, 2),
        (1000, 750, 320, 1, 2),
        (650, 500, 250, 1, 1),
        (420, 320, 180, 1, 1),
        (280, 200, 120, 1, 1),
    )
    for me, ms, mh, nscr, nsh in tiers:
        if _measure_chars(payload) <= budget:
            break
        for sn in snippet_targets:
            _clip_evaluator_snippets(
                sn,
                max_entry=me,
                max_script=ms,
                max_shader=mh,
                max_scripts=nscr,
                max_shaders=nsh,
                log=log,
                dropped_snip=dropped_snip,
            )

    if _measure_chars(payload) > budget and isinstance(ile, dict):
        payload["kmbl_interactive_lane_expectations"] = None
        log.append("kmbl_interactive_lane_expectations:removed")


def apply_payload_budget_governor_v1(
    role: RoleGov,
    payload: dict[str, Any],
    *,
    budget_target_chars: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Return (governed_payload, governor_report).

    ``governor_report`` is safe to persist (counts, labels, no prompt bodies).
    """
    out = copy.deepcopy(payload)
    budget = budget_target_chars if budget_target_chars is not None else DEFAULT_CHAR_BUDGET[role]
    initial = _measure_chars(out)
    log: list[str] = []
    dropped_ref = [0]
    dropped_obs = [0]
    dropped_snip = [0]

    if initial <= budget:
        report = {
            "governor_version": GOVERNOR_VERSION,
            "role": role,
            "budget_target_chars": budget,
            "initial_payload_char_count": initial,
            "final_payload_char_count": initial,
            "was_trimmed": False,
            "trimmed_sections": [],
            "dropped_reference_count": 0,
            "dropped_snippet_count": 0,
            "dropped_observed_reference_count": 0,
        }
        return out, report

    if role == "planner":
        _govern_planner(out, budget, log, dropped_ref, dropped_obs)
    elif role == "generator":
        _govern_generator(out, budget, log, dropped_ref, dropped_obs, dropped_snip)
    else:
        _govern_evaluator(out, budget, log, dropped_ref, dropped_obs, dropped_snip)

    final = _measure_chars(out)
    report = {
        "governor_version": GOVERNOR_VERSION,
        "role": role,
        "budget_target_chars": budget,
        "initial_payload_char_count": initial,
        "final_payload_char_count": final,
        "was_trimmed": True,
        "trimmed_sections": log[:48],
        "dropped_reference_count": dropped_ref[0],
        "dropped_snippet_count": dropped_snip[0],
        "dropped_observed_reference_count": dropped_obs[0],
    }
    return out, report
