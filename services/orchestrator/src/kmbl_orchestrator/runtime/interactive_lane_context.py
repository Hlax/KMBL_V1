"""
Orchestrator-authored hints for ``interactive_frontend_app_v1`` (generator + evaluator).

Cross-file ES module import graphs are not resolved by static preview assembly; the lane should
prefer classic script bundles, IIFEs, or a single entry module with CDN deps — see
``staging/static_preview_assembly.py`` docstring.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.generator_library_policy import (
    build_generator_library_policy_payload,
)
from kmbl_orchestrator.runtime.reference_patterns import (
    build_library_compliance_hints,
    select_reference_patterns,
)
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    IMMERSIVE_IDENTITY_ARCHETYPE,
    PRIMARY_SURFACE_HERO_SCENE_FIRST,
    WEBGL_EXPERIENCE_MODES,
)


def build_interactive_lane_context(
    build_spec: dict[str, Any],
    _event_input: dict[str, Any],
) -> dict[str, Any]:
    """
    Compact, stable JSON for ``kmbl_interactive_lane_context`` / ``kmbl_interactive_lane_expectations``.

    Same dict is sent to generator (capabilities + discipline) and evaluator (fair expectations).
    """
    ec = build_spec.get("execution_contract") if isinstance(build_spec.get("execution_contract"), dict) else {}
    em = build_spec.get("experience_mode")
    em_s = em.strip().lower() if isinstance(em, str) else ""
    heavy_webgl_ask = em_s in WEBGL_EXPERIENCE_MODES

    site_arch = (build_spec.get("site_archetype") or "").strip().lower()
    primary_surface = ec.get("primary_surface_mode") if isinstance(ec, dict) else None
    psm_s = str(primary_surface).strip().lower() if primary_surface else ""
    immersive_identity = (
        site_arch == IMMERSIVE_IDENTITY_ARCHETYPE
        or em_s == IMMERSIVE_IDENTITY_ARCHETYPE
        or psm_s == PRIMARY_SURFACE_HERO_SCENE_FIRST
    )
    immersive_constraints: list[str] = []
    immersive_anti_patterns: list[str] = []
    if immersive_identity:
        immersive_constraints = [
            "Primary surface must be an interactive hero scene (canvas/WebGL mount) above the fold.",
            "Projects and case studies are secondary; avoid work-grid / about / contact as the dominant fold structure.",
            "Scene state must respond to pointer and/or scroll; 3D must not be only parallax decoration.",
            "Provide a valid prefers-reduced-motion fallback (static or simplified hero).",
        ]
        immersive_anti_patterns = [
            "Portfolio-starter IA with work grid + about + contact as the main above-fold experience.",
            "Claiming immersive 3D using only CSS transforms/parallax without a real WebGL/canvas region.",
            "Listing Three.js/GSAP in copy without wiring a hero mount and interaction loop.",
        ]

    req_int = ec.get("required_interactions")
    interaction_hints: list[str] = []
    if isinstance(req_int, list):
        for x in req_int[:12]:
            if isinstance(x, dict):
                iid = x.get("id") or x.get("mechanism")
                if iid:
                    interaction_hints.append(str(iid))
            elif isinstance(x, str) and x.strip():
                interaction_hints.append(x.strip())

    return {
        "lane": "interactive_frontend_app_v1",
        "experience_mode": em_s or None,
        "site_archetype": site_arch or None,
        "primary_surface_mode": psm_s or None,
        "immersive_identity_experience": immersive_identity,
        "immersive_constraints": immersive_constraints,
        "immersive_anti_patterns": immersive_anti_patterns,
        "heavy_webgl_product_mode_requested": heavy_webgl_ask,
        "preview_pipeline": {
            "summary": (
                "KMBL assembles one HTML preview by inlining same-bundle JS in a deterministic order "
                "(hints, then DOM script order, then remaining paths). Cross-file ``import`` graphs "
                "between local JS artifacts are not bundled."
            ),
            "splat_and_cdn_note": (
                "``.splat`` / ``.ply`` ship as same-bundle artifacts (served via orchestrator file routes). "
                "If runtime loads Three/GSAP/splat helpers from a CDN, static-preview CSP allows "
                "``connect-src`` to unpkg + jsDelivr for fetch — prefer same-bundle when possible."
            ),
        },
        "strengths": [
            "One coherent interactive surface: state, controls, and feedback loops in plain JS or "
            "one module entry + CDN libraries.",
            "Default library lane: **Three.js + GSAP** (see ``generator_library_policy``) unless the plan "
            "escalates — keep stacks lightweight and local-preview-friendly.",
            "Multi-file bundles when HTML wires scripts explicitly; CSS for layout/motion; JS for behavior.",
            "Bounded motion: CSS transitions/keyframes, requestAnimationFrame, modest canvas or "
            "Three.js from CDN when the plan calls for it.",
            "Shader assets: ``.glsl`` / ``.vert`` / ``.frag`` / ``.wgsl`` are valid when they improve visuals.",
            "Gaussian splats (captured 3D): specialist lane only — see ``generator_library_policy.gaussian_splat_lane`` "
            "and ``reference_patterns``; not a default for generic marketing sites.",
            "Optional ``kmbl_preview_assembly_hints_v1.js_path_order`` in working_state_patch when "
            "load order must be explicit.",
        ],
        "avoid": [
            "Local ES module graphs (``import … from './sibling.js'`` across multiple generated files) "
            "— preview will not resolve those edges.",
            "npm/vite/webpack project shapes that expect a bundler — this lane is not a build system.",
            "Defaulting to React Three Fiber, Babylon.js, A-Frame, PlayCanvas, Spline/Needle — not default KMBL lanes.",
            "Using PixiJS as the default 3D path — reserve for clearly 2D-first briefs.",
            "WGSL/WebGPU stacks unless ``generator_library_policy`` / experience_mode signals heavy GPU ambition.",
            "Gaussian splat viewers for ordinary hero text or abstract motion — use default Three+GSAP instead.",
            "Treating the lane as a full game engine or immersive product shell; keep scope to one "
            "previewable experience.",
            "Placeholder interactivity (one noop click) when the plan asked for meaningful interaction.",
        ],
        "structure_discipline": [
            "HTML: structure, landmarks, and ``<script src=…>`` / entry wiring.",
            "CSS: visual language, layout, responsive rules, motion where appropriate.",
            "JS: behavior, state, events; keep globals or explicit entry IIFE/module minimal and ordered.",
        ],
        "interactivity_tiers": {
            "fits_this_lane": [
                "micro-apps, panels, filters, toggles, draggable-lite, canvas demos, "
                "scroll/cursor-driven reveals, small Three.js + GSAP scenes via CDN (default interactive lane)",
            ],
            "escalation_lanes": [
                "WebGPU/WGSL (Three path): only when heavy GPU ambition is justified — see policy + experience_mode.",
                "OGL / TWGL / regl: shader-first minimal rendering only — not the default 3D lane.",
                "PixiJS: 2D canvas / motion graphics — not the default 3D lane.",
                "Gaussian splat (gaussian-splats-3d + Three): photoreal captured/scanned scenes only — "
                "set execution_contract.escalation_lane to gaussian_splat_v1 and justify in build spec.",
            ],
            "escalate_future_lane": [
                "multi-route SPA with deep client routing",
                "large WebGL product modes that need asset pipelines, not a single preview bundle",
                "physics-heavy experiences that need a dedicated app lane beyond bounded preview",
            ],
        },
        "generator_library_policy": build_generator_library_policy_payload(ec, build_spec),
        "reference_patterns": select_reference_patterns(ec, build_spec),
        "library_compliance_hints": build_library_compliance_hints(ec, build_spec),
        "execution_contract_signals": {
            "surface_type": ec.get("surface_type"),
            "layout_mode": ec.get("layout_mode"),
            "allowed_libraries": ec.get("allowed_libraries"),
            "escalation_lane": ec.get("escalation_lane"),
            "required_interactions_preview": interaction_hints[:8],
        },
        "evaluator_fairness": [
            "Reward observable interactivity and coherent runtime behavior, not framework completeness.",
            "Do not fail for lacking Redux/SSR/routing; judge the shipped bundle against criteria.",
            "Distinguish static editorial (mostly copy/layout) from bounded interactive apps.",
            "When ``heavy_webgl_product_mode_requested`` is true but artifacts only show a flat page, "
            "prefer partial + concrete issues over pretending the immersive mode was met.",
        ],
    }
