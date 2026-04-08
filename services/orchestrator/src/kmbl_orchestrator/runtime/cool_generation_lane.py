"""First-class cool generation lane: execution presets, compliance metadata, generator hints."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from kmbl_orchestrator.contracts.canvas_contract_v1 import (
    derive_canvas_contract,
    derive_mixed_lane_contract,
)
from kmbl_orchestrator.contracts.geometry_contract_v1 import (
    derive_geometry_contract,
)
from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.generator_library_policy import (
    PRIMARY_LANE_DEFAULT_LIBRARIES,
    build_generator_library_policy_payload,
    build_geometry_mode_library_policy,
)
from kmbl_orchestrator.runtime.interactive_scene_grammar import build_scene_grammar_from_identity
from kmbl_orchestrator.runtime.static_vertical_invariants import is_interactive_frontend_vertical

_log = logging.getLogger(__name__)

# execution_acknowledgment.status — generator vocabulary (case-insensitive in annotate)
EXECUTION_ACKNOWLEDGMENT_STATUSES: frozenset[str] = frozenset(
    ("executed", "downgraded", "cannot_fulfill"),
)

_LITERAL_PREVIEW_MAX_ITEMS = 10
_LITERAL_PREVIEW_MAX_CHARS = 120

COOL_GENERATION_LANE_V1 = "cool_generation_v1"

_DEFAULT_REFERENCE_PATTERNS: tuple[str, ...] = (
    "identity_led_editorial_surface",
    "oversized_typography_structure",
    "restrained_layered_depth_or_motion",
)

_DEFAULT_PATTERN_RULES: tuple[str, ...] = (
    "Use at least one real identity image at meaningful scale (not a tiny thumbnail).",
    "At least one display-scale headline (visual hierarchy, not body-sized only).",
    "Include one non-placeholder motion or interaction: CSS scroll-linked, reduced-motion "
    "fallback, or JS (no empty script block).",
    "Use identity palette or CSS variables derived from identity_brief.palette_hex when present.",
)


def build_generator_reference_doc_hints(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> dict[str, Any]:
    """Determine which agent workspace docs the generator should load for this run.

    Injected as ``kmbl_generator_reference_docs`` in
    ``summarize_execution_contract_for_generator``.  The agent reads ``required``
    unconditionally and ``recommended`` when context budget allows.
    """
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    cool = cool_generation_lane_active(event_input, build_spec)
    gs = ec.get("geometry_system")
    steps = build_spec.get("steps")
    n_steps = len(steps) if isinstance(steps, list) else 0
    habitat = ec.get("habitat_strategy")
    em = (build_spec.get("experience_mode") or "").lower()
    immersive = em in ("immersive_identity_experience", "immersive_spatial_portfolio")
    libs = ec.get("allowed_libraries") or []
    non_default_lib = set(libs) - {"three", "gsap"}

    required: list[str] = []
    recommended: list[str] = []
    reasons: list[str] = []

    if cool:
        required.append("EVALUATOR_GUIDANCE")
        reasons.append("cool_generation_lane_active=true")
    if cool or gs or immersive:
        recommended.append("REFERENCE_PATTERNS")
        reasons.append("geometry_system or immersive experience_mode or cool lane")
    if gs or immersive:
        recommended.append("GEOMETRY")
        reasons.append("geometry_system present or immersive mode")
    if non_default_lib or (isinstance(gs, dict) and gs.get("mode") not in (None, "three")):
        recommended.append("LIBRARIES")
        reasons.append("non-default library stack")
    if n_steps >= 5 or habitat:
        recommended.append("COOL_LANE_STRATEGY")
        reasons.append(f"steps={n_steps} or habitat_strategy present")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_reasons: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)

    return {
        "required": required,
        "recommended": recommended,
        "trigger_reason": "; ".join(unique_reasons) or "standard run",
    }


def cool_generation_lane_active(
    event_input: dict[str, Any],
    build_spec: dict[str, Any],
) -> bool:
    """True when this run should use cool-generation presets and compliance rules."""
    ec = build_spec.get("execution_contract")
    if isinstance(ec, dict) and ec.get("lane") == COOL_GENERATION_LANE_V1:
        return True
    if event_input.get("cool_generation_lane") is True:
        return True
    return False


def reference_pattern_to_literal_token(pattern_label: str) -> str:
    """
    Stable grep-able token for a selected reference pattern label.

    Example: ``portrait_led_editorial_hero`` → ``kmbl-pattern-portrait-led-editorial-hero``.
    """
    s = (pattern_label or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return ""
    return f"kmbl-pattern-{s}"


def literal_success_checks_preview_strings(
    literal_success_checks: Any,
    *,
    max_items: int = _LITERAL_PREVIEW_MAX_ITEMS,
    max_chars: int = _LITERAL_PREVIEW_MAX_CHARS,
) -> list[str]:
    """First N literal needles, each truncated for compact generator payload."""
    if not isinstance(literal_success_checks, list):
        return []
    out: list[str] = []
    for item in literal_success_checks[:max_items]:
        if isinstance(item, str) and item.strip():
            s = item.strip()
        elif isinstance(item, dict) and isinstance(item.get("needle"), str) and item["needle"].strip():
            s = item["needle"].strip()
        else:
            continue
        if len(s) > max_chars:
            s = s[: max_chars - 1] + "…"
        out.append(s)
    return out


def summarize_execution_contract_for_generator(build_spec: dict[str, Any]) -> dict[str, Any]:
    """Compact obligations for generator payload (avoid resending full identity blobs).

    Includes creative direction fields so the generator has rich context without
    needing to parse the full build_spec.
    """
    if not isinstance(build_spec, dict):
        return {}
    ec = build_spec.get("execution_contract")
    if not isinstance(ec, dict):
        ec = {}
    lsc = build_spec.get("literal_success_checks")
    n_lit = len(lsc) if isinstance(lsc, list) else 0
    cb = build_spec.get("creative_brief")
    cb_d = cb if isinstance(cb, dict) else {}
    out: dict[str, Any] = {
        "lane": ec.get("lane"),
        "surface_type": ec.get("surface_type"),
        "layout_mode": ec.get("layout_mode"),
        "selected_reference_patterns": ec.get("selected_reference_patterns"),
        "pattern_rules": ec.get("pattern_rules"),
        "required_sections": ec.get("required_sections"),
        "literal_success_checks_count": n_lit,
        "literal_success_checks_preview": literal_success_checks_preview_strings(lsc),
        # Creative direction — surfaced explicitly so generator does not have to dig into build_spec
        "creative_brief_mood": cb_d.get("mood"),
        "creative_brief_direction_summary": cb_d.get("direction_summary"),
        "creative_brief_color_strategy": cb_d.get("color_strategy"),
        "creative_brief_layout_concept": cb_d.get("layout_concept"),
        "creative_brief_interaction_goals": cb_d.get("interaction_goals"),
        # Identity-derived scene grammar — generator must use these to ground 3D/motion choices
        "creative_brief_scene_metaphor": cb_d.get("scene_metaphor"),
        "creative_brief_scene_metaphor_description": cb_d.get("scene_metaphor_description"),
        "creative_brief_motion_language": cb_d.get("motion_language"),
        "creative_brief_motion_language_description": cb_d.get("motion_language_description"),
        "creative_brief_material_hint": cb_d.get("material_hint"),
        "creative_brief_material_hint_description": cb_d.get("material_hint_description"),
        "creative_brief_primitive_guidance": cb_d.get("primitive_guidance"),
        "creative_brief_layout_instruction": cb_d.get("layout_instruction"),
        "creative_brief_scene_rationale": cb_d.get("scene_rationale"),
        # Allowed libraries for the generator to know what CDN imports are blessed
        "allowed_libraries": ec.get("allowed_libraries"),
        # Required interactions preview for generator awareness
        "required_interactions_count": (
            len(ec["required_interactions"])
            if isinstance(ec.get("required_interactions"), list)
            else 0
        ),
        # Geometry contract — machine-readable composition rules for 3D/interactive builds
        "geometry_system": ec.get("geometry_system"),
        # Canvas and lane-mix contracts
        "canvas_system": ec.get("canvas_system"),
        "lane_mix": ec.get("lane_mix"),
        "source_transformation_policy": ec.get("source_transformation_policy"),
    }
    if is_interactive_frontend_vertical(build_spec, {}):
        out["primary_lane_default_libraries"] = list(PRIMARY_LANE_DEFAULT_LIBRARIES)
        out["generator_library_policy"] = build_generator_library_policy_payload(ec, build_spec)
        out["escalation_lane"] = ec.get("escalation_lane")
    # Observability: which agent workspace docs should the generator load for this run
    out["kmbl_generator_reference_docs"] = build_generator_reference_doc_hints(build_spec, {})
    return out


def _is_portfolio_ia_requested(build_spec: dict[str, Any]) -> bool:
    """True when the planner explicitly requested portfolio information architecture.

    Checks site_archetype and experience_mode for explicit portfolio signals.
    Does NOT default to True — absence of signal means non-portfolio / open layout.
    """
    sa = (build_spec.get("site_archetype") or "").strip().lower()
    em = (build_spec.get("experience_mode") or "").strip().lower()
    # Explicit portfolio archetype OR experience mode that implies portfolio IA
    return sa == "portfolio" or em == "webgl_3d_portfolio"


def apply_cool_generation_lane_presets(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
    identity_brief: dict[str, Any] | None,
    structured_identity: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Merge default execution obligations and literal needles when the lane is active.

    Preserves planner-authored fields when already strong; fills gaps only.

    Key behavior:
    - For interactive lanes (interactive_frontend_app_v1) or identity-led experience
      modes (immersive_identity_experience, immersive_spatial_portfolio), do NOT inject
      portfolio section defaults (hero/proof_or_work/contact_or_cta).
    - Only inject portfolio section defaults when site_archetype is "portfolio" or
      experience_mode is "webgl_3d_portfolio" — i.e. explicit portfolio IA intent.
    - Always inject identity-derived scene grammar into the creative_brief so the
      generator has concrete, identity-grounded direction.
    """
    if not cool_generation_lane_active(event_input, build_spec):
        return build_spec, {"applied": False}

    bs = copy.deepcopy(build_spec)
    ec = bs.get("execution_contract")
    if not isinstance(ec, dict):
        ec = {}
        bs["execution_contract"] = ec
    ec.setdefault("lane", COOL_GENERATION_LANE_V1)
    ec.setdefault("surface_type", "single_page_static")
    ec.setdefault("layout_mode", "editorial_split")

    # Only inject portfolio section defaults when explicitly requested.
    # Interactive lanes and identity-led experience modes must NOT be forced into
    # hero/proof_or_work/contact_or_cta — that collapses them into portfolio shells.
    interactive_vertical = is_interactive_frontend_vertical(bs, event_input)
    portfolio_ia = _is_portfolio_ia_requested(bs)

    if not interactive_vertical and portfolio_ia:
        # Explicit portfolio IA on a static/cool lane — preserve portfolio defaults
        ec.setdefault("required_sections", ["hero", "proof_or_work", "contact_or_cta"])
    elif not interactive_vertical and not ec.get("required_sections"):
        # Static non-portfolio: neutral section default (avoids portfolio forcing)
        ec.setdefault("required_sections", ["primary_surface", "contact_or_cta"])
    # Interactive lanes: no required_sections default; planner owns that entirely

    spr = ec.get("selected_reference_patterns")
    if not (isinstance(spr, list) and len(spr) >= 1):
        ec["selected_reference_patterns"] = list(_DEFAULT_REFERENCE_PATTERNS[:3])
    else:
        ec["selected_reference_patterns"] = [str(x) for x in spr[:3]]

    pr = ec.get("pattern_rules")
    if not (isinstance(pr, list) and len(pr) >= 2):
        ec["pattern_rules"] = list(_DEFAULT_PATTERN_RULES)
    else:
        merged: list[str] = []
        seen: set[str] = set()
        for x in list(pr) + list(_DEFAULT_PATTERN_RULES):
            s = str(x).strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            merged.append(s)
        ec["pattern_rules"] = merged[:14]

    # Literal needles: planner + lane markers + first identity image URL when available
    planner_needles: list[Any] = []
    lsc = bs.get("literal_success_checks")
    if isinstance(lsc, list):
        planner_needles = list(lsc)

    extra: list[str] = []
    identity_image_needle = False
    ib = identity_brief if isinstance(identity_brief, dict) else {}
    imgs = ib.get("image_refs")
    if isinstance(imgs, list) and imgs:
        first = str(imgs[0]).strip()
        if first.lower().startswith("http"):
            extra.append(first.lower())
            identity_image_needle = True
    elif isinstance(structured_identity, dict) and not extra:
        _log.debug("cool_generation_lane: no image_refs on identity_brief; markers only")

    # kmbl-pattern-* tokens and data-kmbl-* markers removed from
    # literal_success_checks: they leaked into final user-facing HTML as
    # internal scaffolding.  Pattern selection is verified via
    # kmbl_scene_manifest_v1 (structured, never rendered to end users).

    merged_lit = _dedupe_literal_needles(planner_needles, extra)
    bs["literal_success_checks"] = merged_lit[:24]

    # Build identity-derived scene grammar and inject into creative_brief.
    # This gives the generator concrete, identity-grounded direction rather than
    # generic "identity-forward editorial" language.
    scene_grammar = build_scene_grammar_from_identity(identity_brief, structured_identity)
    scene_direction = scene_grammar.to_creative_direction()

    cb = bs.get("creative_brief")
    cb_dict = cb if isinstance(cb, dict) else {}

    # Merge: preserve planner-authored fields, add scene grammar where absent.
    merged_cb: dict[str, Any] = dict(cb_dict)
    if not merged_cb.get("mood"):
        merged_cb["mood"] = "distinctive identity-forward"
    if not merged_cb.get("direction_summary"):
        merged_cb["direction_summary"] = (
            "Cool generation lane: real identity imagery at scale, "
            "non-generic motion rooted in identity tone, and scene composition "
            "derived from the identity brief — not a tutorial scaffold."
        )

    # Inject scene grammar fields — only fill gaps (preserve planner intent).
    if not merged_cb.get("scene_metaphor"):
        merged_cb["scene_metaphor"] = scene_direction["scene_metaphor"]
        merged_cb["scene_metaphor_description"] = scene_direction["scene_metaphor_description"]
    if not merged_cb.get("motion_language"):
        merged_cb["motion_language"] = scene_direction["motion_language"]
        merged_cb["motion_language_description"] = scene_direction["motion_language_description"]
    if not merged_cb.get("material_hint"):
        merged_cb["material_hint"] = scene_direction["material_hint"]
        merged_cb["material_hint_description"] = scene_direction["material_hint_description"]
    if not merged_cb.get("primitive_guidance"):
        merged_cb["primitive_guidance"] = scene_direction["primitive_guidance"]
    if scene_direction.get("scene_rationale") and not merged_cb.get("scene_rationale"):
        merged_cb["scene_rationale"] = scene_direction["scene_rationale"]

    # For interactive/immersive lanes: add explicit anti-portfolio instruction
    em = (bs.get("experience_mode") or "").strip().lower()
    if interactive_vertical or em in (
        "immersive_identity_experience",
        "immersive_spatial_portfolio",
    ):
        merged_cb["layout_instruction"] = (
            "Do NOT produce hero/projects/about/contact portfolio structure. "
            "Use scene_metaphor and scene grammar as the organizing principle. "
            "Sections may be spatial zones, narrative beats, or experiential layers — "
            "not standard portfolio cards."
        )

    bs["creative_brief"] = merged_cb

    # Derive geometry contract and inject into execution_contract.geometry_system.
    # This gives the generator explicit, machine-readable composition rules rather
    # than only scene adjectives in the creative brief.
    geo_contract = derive_geometry_contract(identity_brief, structured_identity, bs)
    geo_dict = geo_contract.to_compact_dict()
    ec["geometry_system"] = geo_dict

    # Derive mixed-lane + canvas contracts so interactive shape is first-class.
    lane_mix = derive_mixed_lane_contract(identity_brief, structured_identity, bs)
    canvas_contract = derive_canvas_contract(identity_brief, structured_identity, bs, lane_mix)
    ec["lane_mix"] = lane_mix.to_compact_dict()
    ec["canvas_system"] = canvas_contract.to_compact_dict()

    # Source material policy: keep portfolio grounding but force transformed reuse.
    if not isinstance(ec.get("source_transformation_policy"), dict):
        literal_needles: list[str] = []
        hs = ib.get("headings_sample") if isinstance(ib.get("headings_sample"), list) else []
        for x in hs[:6]:
            s = str(x).strip()
            if len(s) >= 12:
                literal_needles.append(s[:120])
        ps = ib.get("profile_summary")
        if isinstance(ps, str) and len(ps.strip()) >= 16:
            literal_needles.append(ps.strip()[:120])
        ec["source_transformation_policy"] = {
            "text_reuse": "summarize_or_omit_by_default",
            "structure_reuse": "do_not_mirror_portfolio_order",
            "media_reuse": "allowed_if_habitat_native_transform",
            "literalness_guard": [
                "avoid_near_verbatim_source_copy",
                "avoid_portfolio_section_order_clone",
                "prefer_identity_abstraction_over_restate",
            ],
            "literal_source_needles": literal_needles[:8],
        }

    # Align allowed_libraries with geometry mode when planner didn't specify them
    if interactive_vertical:
        mode = geo_contract.mode
        al = ec.get("allowed_libraries")
        if not isinstance(al, list) or len([x for x in al if isinstance(x, str) and x.strip()]) == 0:
            mode_policy = build_geometry_mode_library_policy(mode)
            ec["allowed_libraries"] = mode_policy["primary_stack"]
            _log.info(
                "cool_generation_lane: defaulted allowed_libraries to %s for geometry_mode=%s",
                mode_policy["primary_stack"],
                mode,
            )

    meta = {
        "applied": True,
        "lane": COOL_GENERATION_LANE_V1,
        "literal_needles_count": len(bs["literal_success_checks"]),
        "identity_image_needle": identity_image_needle,
        "scene_grammar_applied": True,
        "scene_metaphor": scene_grammar.scene_metaphor,
        "motion_language": scene_grammar.motion_language,
        "portfolio_ia_sections_injected": not interactive_vertical and portfolio_ia,
        "geometry_mode": geo_contract.mode,
        "geometry_contract_applied": True,
        "canvas_contract_applied": True,
        "canvas_zone_model": canvas_contract.zone_model,
        "lane_mix_applied": True,
        "primary_lane": lane_mix.primary_lane,
        "secondary_lanes": lane_mix.secondary_lanes,
    }
    _log.info(
        "cool_generation_lane presets merged literal_needles=%s patterns=%d",
        meta["literal_needles_count"],
        len(ec.get("selected_reference_patterns") or []),
    )
    return bs, meta


def _dedupe_literal_needles(planner_part: list[Any], extras: list[str]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []

    def _key(item: Any) -> str | None:
        if isinstance(item, str) and item.strip():
            return item.strip().lower()
        if isinstance(item, dict):
            n = item.get("needle")
            if isinstance(n, str) and n.strip():
                return n.strip().lower()
        return None

    for item in planner_part:
        k = _key(item)
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    for s in extras:
        sl = s.strip().lower()
        if sl and sl not in seen:
            seen.add(sl)
            out.append(s)
    return out


def annotate_cool_lane_generator_compliance(
    raw: dict[str, Any],
    *,
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> dict[str, Any]:
    """
    Tag generator JSON when cool lane is active but the model did not report execution status.

    Structured failure path (contract_failure) is left untouched.
    """
    if not cool_generation_lane_active(event_input, build_spec):
        return raw
    cf = raw.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and str(cf.get("code", "")).strip():
        return raw

    out = dict(raw)
    ea = out.get("execution_acknowledgment")
    if isinstance(ea, dict):
        status = ea.get("status")
        if isinstance(status, str) and status.strip():
            st = status.strip().lower()
            if st in EXECUTION_ACKNOWLEDGMENT_STATUSES:
                out["_kmbl_compliance"] = {
                    "cool_generation_lane": True,
                    "acknowledged": True,
                    "status": st,
                    "ambition_downgrades": ea.get("ambition_downgrades"),
                    "rules_attempted": ea.get("rules_attempted"),
                    "rules_skipped": ea.get("rules_skipped"),
                }
                return out
            out["_kmbl_compliance"] = {
                "cool_generation_lane": True,
                "invalid_execution_acknowledgment_status": True,
                "reason": (
                    "execution_acknowledgment.status must be one of: "
                    + ", ".join(sorted(EXECUTION_ACKNOWLEDGMENT_STATUSES))
                ),
                "received_status": status.strip(),
            }
            return out

    out["_kmbl_compliance"] = {
        "cool_generation_lane": True,
        "silent_acknowledgment": True,
        "reason": "execution_acknowledgment missing or status empty for cool_generation_v1 lane",
    }
    return out


def apply_cool_lane_execution_acknowledgment_gates(
    report: EvaluationReportRecord,
    *,
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """
    Downgrade pass→partial when cool lane acknowledgment is missing, silent, or invalid.

    Literal substring checks still apply separately.
    """
    comp = build_candidate.get("_kmbl_compliance") or {}
    if report.status not in ("pass", "partial"):
        return report

    if comp.get("silent_acknowledgment"):
        issues = list(report.issues_json or [])
        issues.append({
            "severity": "medium",
            "category": "cool_lane_silent_acknowledgment",
            "message": (
                comp.get("reason")
                or "Cool generation lane requires execution_acknowledgment.status when emitting artifacts."
            ),
        })
        m = dict(report.metrics_json or {})
        m["cool_lane_silent_acknowledgment"] = True
        return report.model_copy(
            update={
                "status": "partial",
                "issues_json": issues,
                "metrics_json": m,
            },
        )

    if comp.get("invalid_execution_acknowledgment_status"):
        issues = list(report.issues_json or [])
        issues.append({
            "severity": "medium",
            "category": "cool_lane_invalid_execution_acknowledgment_status",
            "message": comp.get("reason")
            or "execution_acknowledgment.status must be executed, downgraded, or cannot_fulfill.",
        })
        m = dict(report.metrics_json or {})
        m["cool_lane_invalid_execution_acknowledgment_status"] = True
        if comp.get("received_status") is not None:
            m["cool_lane_received_acknowledgment_status"] = comp.get("received_status")
        return report.model_copy(
            update={
                "status": "partial",
                "issues_json": issues,
                "metrics_json": m,
            },
        )

    return report


def apply_cool_lane_silent_acknowledgment_gate(
    report: EvaluationReportRecord,
    *,
    build_candidate: dict[str, Any],
) -> EvaluationReportRecord:
    """Backward-compatible alias for ``apply_cool_lane_execution_acknowledgment_gates``."""
    return apply_cool_lane_execution_acknowledgment_gates(
        report,
        build_candidate=build_candidate,
    )


__all__ = [
    "COOL_GENERATION_LANE_V1",
    "EXECUTION_ACKNOWLEDGMENT_STATUSES",
    "annotate_cool_lane_generator_compliance",
    "apply_cool_generation_lane_presets",
    "apply_cool_lane_execution_acknowledgment_gates",
    "apply_cool_lane_silent_acknowledgment_gate",
    "build_generator_reference_doc_hints",
    "cool_generation_lane_active",
    "literal_success_checks_preview_strings",
    "reference_pattern_to_literal_token",
    "summarize_execution_contract_for_generator",
    "_is_portfolio_ia_requested",
]
