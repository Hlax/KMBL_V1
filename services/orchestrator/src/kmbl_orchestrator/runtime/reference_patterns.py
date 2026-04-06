"""
Compact reference patterns for interactive frontend lanes — registry + selection + compliance hints.

Not a prompt dump: small structured entries for ``kmbl_reference_patterns`` on generator/evaluator payloads.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.generator_library_policy import (
    GAUSSIAN_SPLAT_ESCALATION_LANE,
    GAUSSIAN_SPLAT_LIBRARY_PRIMARY,
    PRIMARY_LANE_DEFAULT_LIBRARIES,
)
from kmbl_orchestrator.runtime.static_vertical_invariants import WEBGL_EXPERIENCE_MODES

# Alternate (documentation only — do not add as equal default in contract)
GAUSSIAN_SPLAT_ALTERNATES_DOC = (
    "Other splat viewers exist (e.g. Spark/WebGPU-heavy); KMBL standardizes on Three-compatible "
    f"{GAUSSIAN_SPLAT_LIBRARY_PRIMARY} for local preview + single-bundle fits."
)

# Registry: group id -> list of pattern dicts (max ~3 per group stored; selection returns subset).
_REFERENCE_GROUPS: dict[str, list[dict[str, Any]]] = {
    "default_three_gsap": [
        {
            "id": "three_gsap_cdn_bundle",
            "lane": "default_three_gsap",
            "title": "CDN Three + GSAP, HTML-wired scripts",
            "use_when": "Default interactive builds, hero motion, light 3D, scroll/cursor cues.",
            "avoid_when": "Captured photoreal splats, shader-first minimal GL, or pure 2D canvas.",
            "libraries": list(PRIMARY_LANE_DEFAULT_LIBRARIES),
            "file_shape": "component/preview/index.html; component/preview/js/*.js; optional css/",
            "implementation_notes": "Script order from HTML; optional kmbl_preview_assembly_hints_v1.js_path_order.",
        },
        {
            "id": "three_gsap_single_scene",
            "lane": "default_three_gsap",
            "title": "One Three scene + GSAP timeline",
            "use_when": "Single coherent 3D focal object + UI/motion around it.",
            "avoid_when": "Needs Gaussian splats or raw WGSL compute.",
            "libraries": ["three", "gsap"],
            "file_shape": "index.html + one main.js driving THREE + gsap",
            "implementation_notes": "Keep materials/lights understandable; rAF for render loop.",
        },
        {
            "id": "three_gsap_scroll_reactive",
            "lane": "default_three_gsap",
            "title": "Scroll / resize bound motion",
            "use_when": "Parallax, section reveals, modest canvas size changes.",
            "avoid_when": "Multi-MB asset pipelines or SPA routers.",
            "libraries": ["three", "gsap"],
            "file_shape": "HTML sections + JS listeners; GSAP ScrollTrigger optional via CDN",
            "implementation_notes": "Prefer ResizeObserver + bounded pixel ratio for preview stability.",
        },
    ],
    "wgsl_webgpu": [
        {
            "id": "wgsl_three_webgpu",
            "lane": "wgsl_webgpu",
            "title": "Three WebGPU renderer + WGSL modules",
            "use_when": "Heavy GPU ambition modes or explicit advanced shader/compute need.",
            "avoid_when": "Flat marketing pages or effects solvable with WebGL + three alone.",
            "libraries": ["three", "wgsl"],
            "file_shape": "index.html + *.wgsl under component/ + JS bootstrap",
            "implementation_notes": "Provide fallback message if WebGPU missing; keep shaders small.",
        },
        {
            "id": "wgsl_degrade_path",
            "lane": "wgsl_webgpu",
            "title": "Honest downgrade path",
            "use_when": "WGSL path requested but device may lack WebGPU.",
            "avoid_when": "N/A",
            "libraries": ["three", "wgsl"],
            "file_shape": "Same bundle; branch in JS on navigator.gpu",
            "implementation_notes": "Static fallback frame or simpler WebGL variant documented in UI.",
        },
    ],
    "pixi_2d": [
        {
            "id": "pixi_canvas_stage",
            "lane": "pixi_2d",
            "title": "Pixi stage for 2D motion / particles",
            "use_when": "Clearly 2D-first: sprites, typography on canvas, 2D games UI.",
            "avoid_when": "Spatial 3D, splats, or Three-centric scenes.",
            "libraries": ["pixi"],
            "file_shape": "index.html + Pixi Application bootstrap + assets under component/",
            "implementation_notes": "Do not use Pixi as default 3D substitute.",
        },
        {
            "id": "pixi_ui_heavy_2d",
            "lane": "pixi_2d",
            "title": "Animated 2D interfaces",
            "use_when": "HUD-style panels, draggable 2D chrome, stylized motion graphics.",
            "avoid_when": "Need real 3D camera paths or splats.",
            "libraries": ["pixi"],
            "file_shape": "Single canvas parent; keep DPI / resolution bounded",
            "implementation_notes": "Prefer one Pixi app per page section for preview simplicity.",
        },
    ],
    "shader_first_minimal": [
        {
            "id": "ogl_min_scene",
            "lane": "shader_first_minimal",
            "title": "OGL minimal mesh + shader",
            "use_when": "Shader-first art experiments, tiny custom renderer.",
            "avoid_when": "Product marketing site with stock components.",
            "libraries": ["ogl"],
            "file_shape": "index.html + glsl/vert/frag or wgsl chunks",
            "implementation_notes": "Keep draw calls few; document uniforms.",
        },
        {
            "id": "twgl_or_regl_raw",
            "lane": "shader_first_minimal",
            "title": "TWGL/regl for explicit GL control",
            "use_when": "Pass-heavy or stateful GL when OGL too thin.",
            "avoid_when": "Could be done with Three in default lane.",
            "libraries": ["twgl", "regl"],
            "file_shape": "HTML + fragment/vertex paths; minimal JS glue",
            "implementation_notes": "Not default 3D lane — only when brief is shader-centric.",
        },
    ],
    "gaussian_splat": [
        {
            "id": "gaussian_splat_three_viewer",
            "lane": "gaussian_splat",
            "title": "Three + gaussian-splats-3d viewer",
            "use_when": "Photoreal captured scenes, navigable splats, scanned hero objects.",
            "avoid_when": "Generic CSS motion sites; abstract Three mesh suffices.",
            "libraries": ["three", "gsap", GAUSSIAN_SPLAT_LIBRARY_PRIMARY],
            "file_shape": "component/preview/index.html; assets/*.ply|*.splat under component/assets/",
            "implementation_notes": (
                f"Preferred integration: {GAUSSIAN_SPLAT_LIBRARY_PRIMARY} (Three-compatible). "
                "Load splat binary or .ply; lazy-load if large. "
                + GAUSSIAN_SPLAT_ALTERNATES_DOC
            ),
        },
        {
            "id": "gaussian_splat_fallback",
            "lane": "gaussian_splat",
            "title": "Fallback when asset missing",
            "use_when": "Splat file unavailable or too large for preview.",
            "avoid_when": "N/A",
            "libraries": ["three", GAUSSIAN_SPLAT_LIBRARY_PRIMARY],
            "file_shape": "Placeholder still + message; optional low-res poster image",
            "implementation_notes": "Never fail silently — explain missing asset in UI.",
        },
    ],
}


def _libs_normalized(ec: dict[str, Any]) -> list[str]:
    raw = ec.get("allowed_libraries")
    if not isinstance(raw, list):
        return []
    return [str(x).strip().lower() for x in raw if isinstance(x, str) and str(x).strip()]


def _lane_bucket(ec: dict[str, Any], build_spec: dict[str, Any]) -> str:
    """Single bucket for pattern selection (priority order)."""
    libs = set(_libs_normalized(ec))
    el = (ec.get("escalation_lane") or "").strip().lower()
    if el == GAUSSIAN_SPLAT_ESCALATION_LANE or GAUSSIAN_SPLAT_LIBRARY_PRIMARY in libs:
        return "gaussian_splat"
    if "pixi" in libs or "pixi.js" in libs:
        return "pixi_2d"
    if libs.intersection({"ogl", "twgl", "regl"}) and "three" not in libs:
        return "shader_first_minimal"
    em = (build_spec.get("experience_mode") or "").strip().lower()
    if em in WEBGL_EXPERIENCE_MODES or "wgsl" in libs:
        return "wgsl_webgpu"
    return "default_three_gsap"


def select_reference_patterns(ec: dict[str, Any], build_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return 1–3 compact patterns for the active lane — never the full registry.

    Gaussian splat specialist: only splat patterns (no default Three/GSAP pattern mix).
    """
    bucket = _lane_bucket(ec, build_spec)
    group = _REFERENCE_GROUPS.get(bucket) or _REFERENCE_GROUPS["default_three_gsap"]
    if bucket == "gaussian_splat":
        return list(group[:2])
    if bucket == "wgsl_webgpu":
        return list(group[:2])
    if bucket == "pixi_2d":
        return list(group[:2])
    if bucket == "shader_first_minimal":
        return list(group[:2])
    return list(_REFERENCE_GROUPS["default_three_gsap"][:3])


def build_library_compliance_hints(ec: dict[str, Any], build_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Lightweight policy signals for generator context / evaluator feedback — not hard failures.

    Each item: ``code``, ``severity`` (info|warn), ``detail`` (short).
    """
    hints: list[dict[str, Any]] = []
    libs = _libs_normalized(ec)
    lib_set = set(libs)
    el = (ec.get("escalation_lane") or "").strip().lower()

    if GAUSSIAN_SPLAT_LIBRARY_PRIMARY in lib_set and el != GAUSSIAN_SPLAT_ESCALATION_LANE:
        hints.append(
            {
                "code": "gaussian_splat_library_without_escalation_lane",
                "severity": "info",
                "detail": (
                    f"allowed_libraries includes {GAUSSIAN_SPLAT_LIBRARY_PRIMARY} but "
                    f"execution_contract.escalation_lane is not gaussian_splat_v1 — "
                    "planner should justify splat lane in build_spec."
                ),
            }
        )
    if el == GAUSSIAN_SPLAT_ESCALATION_LANE and GAUSSIAN_SPLAT_LIBRARY_PRIMARY not in lib_set:
        hints.append(
            {
                "code": "gaussian_splat_lane_missing_primary_library",
                "severity": "warn",
                "detail": (
                    f"escalation_lane={GAUSSIAN_SPLAT_ESCALATION_LANE} but "
                    f"{GAUSSIAN_SPLAT_LIBRARY_PRIMARY} not in allowed_libraries."
                ),
            }
        )
    if "pixi" in lib_set and (GAUSSIAN_SPLAT_LIBRARY_PRIMARY in lib_set or el == GAUSSIAN_SPLAT_ESCALATION_LANE):
        hints.append(
            {
                "code": "mixed_escalation_pixi_and_gaussian_splat",
                "severity": "warn",
                "detail": "PixiJS and Gaussian splat stack together — unusual; verify brief intent.",
            }
        )
    if lib_set.intersection(set(NOT_DEFAULT_FRAMEWORKS_TOKENS)):
        hints.append(
            {
                "code": "non_default_framework_in_contract",
                "severity": "info",
                "detail": "Non-default framework token present — ensure brief explicitly requires it.",
            }
        )
    return hints


# Subset of generator_library_policy NOT_DEFAULT_FRAMEWORKS as tokens (lowercase).
NOT_DEFAULT_FRAMEWORKS_TOKENS: frozenset[str] = frozenset(
    {
        "react-three-fiber",
        "babylon.js",
        "babylon",
        "a-frame",
        "aframe",
        "playcanvas",
        "spline",
        "needle engine",
        "needle",
    }
)
