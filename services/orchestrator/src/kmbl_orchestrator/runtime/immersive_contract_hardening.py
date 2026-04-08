"""Harden immersive planner outputs away from generic portfolio-shell defaults."""

from __future__ import annotations

import copy
import re
from typing import Any

from kmbl_orchestrator.runtime.static_vertical_invariants import is_interactive_frontend_vertical

_IMMERSIVE_EXPERIENCE_MODES = {
    "immersive_identity_experience",
    "immersive_spatial_portfolio",
}

_PORTFOLIO_TERMS_RE = re.compile(
    r"\b(hero|portfolio|projects?|case[ -]?stud(?:y|ies)|about|timeline|contact|services|testimonials?)\b",
    re.IGNORECASE,
)

_PORTFOLIO_SECTION_TOKENS = {
    "hero",
    "hero_scene",
    "projects",
    "projects_grid",
    "case_studies",
    "about",
    "about_timeline",
    "contact",
    "contact_cta",
    "services",
    "testimonials",
}


def harden_immersive_planner_output(
    raw: dict[str, Any],
    event_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Rewrite immersive planner outputs that regress into portfolio-shell structure."""
    build_spec = raw.get("build_spec") if isinstance(raw.get("build_spec"), dict) else None
    if not isinstance(build_spec, dict):
        return raw, None
    if not _is_immersive_non_portfolio(build_spec, event_input):
        return raw, None

    out = dict(raw)
    bs = copy.deepcopy(build_spec)
    fixes: list[str] = []

    creative_brief = bs.get("creative_brief") if isinstance(bs.get("creative_brief"), dict) else {}
    execution_contract = bs.get("execution_contract") if isinstance(bs.get("execution_contract"), dict) else {}
    canvas_system = execution_contract.get("canvas_system") if isinstance(execution_contract.get("canvas_system"), dict) else {}

    scene_label = _scene_label(bs, creative_brief, canvas_system)
    layout_concept = creative_brief.get("layout_concept")
    if not isinstance(layout_concept, str) or _looks_like_portfolio_shell(layout_concept):
        creative_brief = dict(creative_brief)
        creative_brief["layout_concept"] = (
            f"Build one cohesive immersive surface around {scene_label}. "
            "Use spatial layers, overlays, or scene-state transitions instead of hero/projects/about/contact sections."
        )
        bs["creative_brief"] = creative_brief
        fixes.append("layout_concept_rewritten_for_immersive_surface")

    portfolio_sections = _sections_look_like_portfolio_shell(execution_contract.get("required_sections"))
    layout_mode = execution_contract.get("layout_mode")
    if (
        not isinstance(layout_mode, str)
        or _looks_like_portfolio_shell(layout_mode)
        or layout_mode.strip().lower() in {"stacked_sections", "editorial_sections"}
        or portfolio_sections
    ):
        execution_contract = dict(execution_contract)
        execution_contract["layout_mode"] = "immersive_single_surface"
        fixes.append("layout_mode_forced_single_surface")

    required_sections = execution_contract.get("required_sections")
    if portfolio_sections:
        execution_contract["required_sections"] = [
            "primary_surface",
            "spatial_layers",
            "interaction_layer",
        ]
        fixes.append("required_sections_rewritten_for_immersive_surface")

    if execution_contract.get("session_delivery_strategy") != "single_surface_session":
        execution_contract["session_delivery_strategy"] = "single_surface_session"
        fixes.append("session_delivery_strategy_single_surface")

    canvas_system = execution_contract.get("canvas_system") if isinstance(execution_contract.get("canvas_system"), dict) else {}
    canvas_system = dict(canvas_system)
    if canvas_system.get("zone_model") != "single_scene":
        canvas_system["zone_model"] = "single_scene"
        fixes.append("canvas_zone_model_single_scene")
    if canvas_system.get("page_count_hint") != 1:
        canvas_system["page_count_hint"] = 1
        fixes.append("canvas_page_count_hint_single_surface")
    execution_contract["canvas_system"] = canvas_system
    bs["execution_contract"] = execution_contract

    steps = out.get("steps")
    if _steps_look_like_portfolio_shell(steps):
        out["steps"] = [
            {
                "title": "Primary immersive surface",
                "description": f"Stage {scene_label} as one identity-grounded scene instead of a hero-led portfolio page.",
            },
            {
                "title": "Spatial narrative layers",
                "description": "Reveal story, work, and personality through layered zones, transitions, and motion states rather than stacked sections.",
            },
            {
                "title": "Interaction and fallback",
                "description": "Wire visible motion response plus an honest reduced-motion or non-WebGL fallback that still carries the identity cues.",
            },
        ]
        fixes.append("steps_rewritten_for_single_surface_session")

    success_criteria = out.get("success_criteria")
    if _text_list_looks_like_portfolio_shell(success_criteria):
        libraries = _library_tokens(execution_contract)
        criteria = [
            "Primary surface renders an identity-grounded immersive scene rather than a stock portfolio shell.",
            "The build uses spatial layers or state transitions instead of stacked section sequencing.",
            "Pointer or scroll input produces visible scene response in the main surface.",
            "A reduced-motion or non-WebGL fallback preserves readable structure and core identity cues.",
        ]
        if libraries:
            criteria.append(
                f"The allowed runtime libraries load coherently for the scene: {', '.join(libraries)}."
            )
        out["success_criteria"] = criteria
        fixes.append("success_criteria_rewritten_for_immersive_evaluation")

    evaluation_targets = out.get("evaluation_targets")
    if _evaluation_targets_look_like_portfolio_shell(evaluation_targets):
        targets: list[dict[str, Any]] = [
            {"kind": "selector_present", "selector": "[data-kmbl-scene]"},
            {
                "kind": "text_present",
                "substring": scene_label.replace("_", " "),
            },
        ]
        if _requires_canvas(execution_contract):
            targets.append({"kind": "selector_present", "selector": "canvas"})
        for lib in _library_tokens(execution_contract):
            targets.append({"kind": "library_loaded", "library": lib})
        out["evaluation_targets"] = targets
        fixes.append("evaluation_targets_rewritten_for_immersive_surface")

    if not fixes:
        return raw, None

    out["build_spec"] = bs
    meta = {
        "applied": True,
        "fixes": fixes,
        "experience_mode": str(bs.get("experience_mode") or ""),
        "session_delivery_strategy": execution_contract.get("session_delivery_strategy"),
    }
    return out, meta


def _is_immersive_non_portfolio(build_spec: dict[str, Any], event_input: dict[str, Any]) -> bool:
    build_spec_type = str(build_spec.get("type") or "").strip().lower()
    if build_spec_type != "interactive_frontend_app_v1" and not is_interactive_frontend_vertical(build_spec, event_input):
        return False
    experience_mode = str(build_spec.get("experience_mode") or "").strip().lower()
    return experience_mode in _IMMERSIVE_EXPERIENCE_MODES


def _scene_label(
    build_spec: dict[str, Any],
    creative_brief: dict[str, Any],
    canvas_system: dict[str, Any],
) -> str:
    for value in (
        creative_brief.get("scene_metaphor"),
        creative_brief.get("scene_grammar"),
        canvas_system.get("scene_metaphor"),
        canvas_system.get("zone_model"),
        build_spec.get("site_archetype"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "an identity-grounded spatial scene"


def _looks_like_portfolio_shell(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_PORTFOLIO_TERMS_RE.search(value))


def _sections_look_like_portfolio_shell(value: Any) -> bool:
    if not isinstance(value, list):
        return True
    tokens: list[str] = []
    for item in value:
        if isinstance(item, str):
            tokens.append(item.strip().lower())
        elif isinstance(item, dict):
            for key in ("id", "name", "section", "title"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    tokens.append(raw.strip().lower())
                    break
    return not tokens or any(token in _PORTFOLIO_SECTION_TOKENS for token in tokens)


def _steps_look_like_portfolio_shell(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    matches = 0
    for item in value:
        if isinstance(item, dict):
            combined = " ".join(str(item.get(key) or "") for key in ("title", "description", "goal"))
        else:
            combined = str(item or "")
        if _looks_like_portfolio_shell(combined):
            matches += 1
    return matches >= 2


def _text_list_looks_like_portfolio_shell(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return True
    return any(_looks_like_portfolio_shell(item) for item in value if isinstance(item, str))


def _evaluation_targets_look_like_portfolio_shell(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return True
    for item in value:
        if isinstance(item, str) and _looks_like_portfolio_shell(item):
            return True
        if isinstance(item, dict):
            for key in ("selector", "substring", "criterion", "id", "name"):
                raw = item.get(key)
                if isinstance(raw, str) and _looks_like_portfolio_shell(raw):
                    return True
    return False


def _library_tokens(execution_contract: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in ("required_libraries", "allowed_libraries"):
        raw = execution_contract.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, str):
                continue
            token = item.strip().lower()
            if token and token not in seen:
                seen.add(token)
                out.append(token)
    return out


def _requires_canvas(execution_contract: dict[str, Any]) -> bool:
    libs = set(_library_tokens(execution_contract))
    if "three" in libs:
        return True
    canvas_system = execution_contract.get("canvas_system")
    if isinstance(canvas_system, dict):
        mode = str(canvas_system.get("geometry_mode") or "").strip().lower()
        if mode in {"three_scene", "webgl_scene", "wgsl_scene"}:
            return True
    return False