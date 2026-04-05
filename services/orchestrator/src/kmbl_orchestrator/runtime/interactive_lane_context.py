"""
Orchestrator-authored hints for ``interactive_frontend_app_v1`` (generator + evaluator).

Cross-file ES module import graphs are not resolved by static preview assembly; the lane should
prefer classic script bundles, IIFEs, or a single entry module with CDN deps — see
``staging/static_preview_assembly.py`` docstring.
"""

from __future__ import annotations

from typing import Any

from kmbl_orchestrator.runtime.static_vertical_invariants import WEBGL_EXPERIENCE_MODES


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
        "heavy_webgl_product_mode_requested": heavy_webgl_ask,
        "preview_pipeline": {
            "summary": (
                "KMBL assembles one HTML preview by inlining same-bundle JS in a deterministic order "
                "(hints, then DOM script order, then remaining paths). Cross-file ``import`` graphs "
                "between local JS artifacts are not bundled."
            ),
        },
        "strengths": [
            "One coherent interactive surface: state, controls, and feedback loops in plain JS or "
            "one module entry + CDN libraries.",
            "Multi-file bundles when HTML wires scripts explicitly; CSS for layout/motion; JS for behavior.",
            "Bounded motion: CSS transitions/keyframes, requestAnimationFrame, modest canvas or "
            "Three.js from CDN when the plan calls for it.",
            "Optional ``kmbl_preview_assembly_hints_v1.js_path_order`` in working_state_patch when "
            "load order must be explicit.",
        ],
        "avoid": [
            "Local ES module graphs (``import … from './sibling.js'`` across multiple generated files) "
            "— preview will not resolve those edges.",
            "npm/vite/webpack project shapes that expect a bundler — this lane is not a build system.",
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
                "scroll/cursor-driven reveals, small Three.js scenes via CDN",
            ],
            "escalate_future_lane": [
                "multi-route SPA with deep client routing",
                "large WebGL product modes that need asset pipelines, not a single preview bundle",
                "physics-heavy or shader-heavy experiences that need a dedicated app lane",
            ],
        },
        "execution_contract_signals": {
            "surface_type": ec.get("surface_type"),
            "layout_mode": ec.get("layout_mode"),
            "allowed_libraries": ec.get("allowed_libraries"),
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
