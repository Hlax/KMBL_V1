"""
KMBL frontend generation library policy — constants + compact runtime payloads.

Source of truth (human): ``docs/generator-library-policy.md``.
Orchestrator applies defaults to ``execution_contract.allowed_libraries`` for interactive verticals
and attaches ``generator_library_policy`` to ``kmbl_interactive_lane_context``.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.static_vertical_invariants import WEBGL_EXPERIENCE_MODES

# Machine tokens (lowercase) aligned with planner normalize / execution_contract.
PRIMARY_LANE_DEFAULT_LIBRARIES: tuple[str, ...] = ("three", "gsap")

# Appended when experience_mode is a heavy WebGPU ambition mode (explicit signal).
HEAVY_WEBGL_WGSL_TOKEN = "wgsl"

# Three-compatible Gaussian splat viewing (specialist lane — not default).
GAUSSIAN_SPLAT_LIBRARY_PRIMARY = "gaussian-splats-3d"
GAUSSIAN_SPLAT_ESCALATION_LANE = "gaussian_splat_v1"

# Splat / point-cloud assets (preview may still load as URLs or small binaries).
GAUSSIAN_SPLAT_ASSET_EXTENSIONS: tuple[str, ...] = (".splat", ".ply")

OPTIONAL_SUPPORT_LIBRARIES: tuple[str, ...] = (
    "lil-gui",
    "camera-controls",
    "postprocessing",
    "troika-three-text",
    "gl-matrix",
    "glslify",
)

CONTROLLED_ESCALATION_LIBRARIES: tuple[str, ...] = (
    "pixi",
    "ogl",
    "twgl",
    "regl",
)

NOT_DEFAULT_FRAMEWORKS: tuple[str, ...] = (
    "react-three-fiber",
    "babylon.js",
    "babylon",
    "a-frame",
    "aframe",
    "playcanvas",
    "spline",
    "needle engine",
    "needle",
)

ALLOWED_SHADER_FILE_EXTENSIONS: tuple[str, ...] = (".glsl", ".vert", ".frag", ".wgsl")

# Combined asset extensions surfaced to generator (shaders + splat data).
INTERACTIVE_ASSET_EXTENSIONS: tuple[str, ...] = tuple(
    dict.fromkeys((*ALLOWED_SHADER_FILE_EXTENSIONS, *GAUSSIAN_SPLAT_ASSET_EXTENSIONS))
)


def _libs_list(ec: dict[str, Any]) -> list[str]:
    raw = ec.get("allowed_libraries")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip().lower())
    return out


def build_generator_library_policy_payload(
    ec: dict[str, Any],
    build_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Compact JSON for ``kmbl_interactive_lane_context.generator_library_policy``.

    Does not duplicate full prose — references policy doc and encodes resolved signals.
    """
    em = (build_spec.get("experience_mode") or "").strip().lower()
    heavy_webgpu_ambition = em in WEBGL_EXPERIENCE_MODES
    libs = _libs_list(ec)
    lib_set = set(libs)
    has_wgsl = "wgsl" in lib_set
    has_pixi = "pixi" in lib_set or "pixi.js" in lib_set
    has_escalation_minimal_gl = bool(lib_set.intersection({"ogl", "twgl", "regl"}))
    has_gaussian_splat = GAUSSIAN_SPLAT_LIBRARY_PRIMARY in lib_set
    elane = (ec.get("escalation_lane") or "").strip().lower()
    gaussian_lane_active = elane == GAUSSIAN_SPLAT_ESCALATION_LANE or has_gaussian_splat

    return {
        "policy_version": 2,
        "policy_doc": "docs/generator-library-policy.md",
        "primary_lane_defaults": list(PRIMARY_LANE_DEFAULT_LIBRARIES),
        "allowed_shader_file_extensions": list(ALLOWED_SHADER_FILE_EXTENSIONS),
        "gaussian_splat_asset_extensions": list(GAUSSIAN_SPLAT_ASSET_EXTENSIONS),
        "interactive_asset_extensions": list(INTERACTIVE_ASSET_EXTENSIONS),
        "gaussian_splat_lane": {
            "escalation_lane_token": GAUSSIAN_SPLAT_ESCALATION_LANE,
            "primary_library": GAUSSIAN_SPLAT_LIBRARY_PRIMARY,
            "preferred_stack": ["three", GAUSSIAN_SPLAT_LIBRARY_PRIMARY, "gsap"],
            "not_default": True,
            "alternate_viewers_note": (
                "Spark/other WebGPU-heavy viewers are not KMBL defaults; use only if brief demands."
            ),
        },
        "resolved_allowed_libraries": libs,
        "heavy_webgpu_wgsl_ambition_experience_mode": heavy_webgpu_ambition,
        "webgpu_wgsl_in_contract": has_wgsl,
        "not_default_frameworks": list(NOT_DEFAULT_FRAMEWORKS),
        "escalation_hints": {
            "wgsl_webgpu": (
                "Use WGSL / Three WebGPU path only when experience_mode signals heavy GPU ambition "
                "or build_spec justifies it; orchestrator may append `wgsl` when mode is webgl_3d_portfolio / "
                "immersive_spatial_portfolio / model_centric_experience."
            ),
            "ogl_twgl_regl": (
                "Shader-first / minimal abstraction only — not the default 3D lane."
            ),
            "pixi": (
                "2D canvas / motion graphics only when brief is 2D-first — not default 3D."
            ),
            "gaussian_splat": (
                "Specialist lane for captured/photoreal splat scenes — set escalation_lane to "
                f"{GAUSSIAN_SPLAT_ESCALATION_LANE} and include {GAUSSIAN_SPLAT_LIBRARY_PRIMARY}; "
                "not for generic sites solvable with ordinary Three meshes."
            ),
        },
        "flags": {
            "contract_includes_pixi": has_pixi,
            "contract_includes_minimal_shader_gl": has_escalation_minimal_gl,
            "gaussian_splat_lane_active": gaussian_lane_active,
            "escalation_lane": elane or None,
        },
    }
