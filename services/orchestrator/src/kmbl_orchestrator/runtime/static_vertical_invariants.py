"""Coherence rules for identity-URL static frontend vertical vs experience_mode."""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# Experience modes that map to ``surface_type: webgl_experience`` in planner_node. The OpenClaw
# kmbl-generator **static HTML lane** may decline with ``contract_failure cannot_satisfy_spec`` when
# the build_spec still asks for a "real" immersive/WebGL *product mode* that lane cannot satisfy,
# even though static HTML/JS/CSS bundles may embed Three.js. Clamping to flat_editorial_static keeps
# the declared mode aligned with the static lane while still allowing embedded 3D in artifacts.
WEBGL_EXPERIENCE_MODES: frozenset[str] = frozenset(
    {
        "webgl_3d_portfolio",
        "immersive_spatial_portfolio",
        "model_centric_experience",
    },
)

_STATIC_VERTICAL_INCOMPATIBLE_MODES = WEBGL_EXPERIENCE_MODES

_DEFAULT_STATIC_EXPERIENCE_MODE = "flat_editorial_static"


def is_static_frontend_vertical(build_spec: dict[str, Any], event_input: dict[str, Any]) -> bool:
    t = (build_spec.get("type") or "").strip().lower()
    if t == "static_frontend_file_v1":
        return True
    cons = event_input.get("constraints") if isinstance(event_input, dict) else {}
    if isinstance(cons, dict) and cons.get("canonical_vertical") == "static_frontend_file_v1":
        return True
    if isinstance(cons, dict) and cons.get("kmbl_static_frontend_vertical") is True:
        return True
    return False


def is_interactive_frontend_vertical(build_spec: dict[str, Any], event_input: dict[str, Any]) -> bool:
    """Multi-file component/ bundle with richer interactivity; same ingest/preview pipeline as static."""
    t = (build_spec.get("type") or "").strip().lower()
    if t == "interactive_frontend_app_v1":
        return True
    cons = event_input.get("constraints") if isinstance(event_input, dict) else {}
    if isinstance(cons, dict) and cons.get("canonical_vertical") == "interactive_frontend_app_v1":
        return True
    if isinstance(cons, dict) and cons.get("kmbl_interactive_frontend_vertical") is True:
        return True
    return False


def is_manifest_first_bundle_vertical(build_spec: dict[str, Any], event_input: dict[str, Any]) -> bool:
    """Workspace-manifest-first policy applies to static and interactive frontend bundle verticals."""
    return is_static_frontend_vertical(build_spec, event_input) or is_interactive_frontend_vertical(
        build_spec, event_input
    )


def is_preview_assembly_vertical(build_spec: dict[str, Any], event_input: dict[str, Any]) -> bool:
    """Single-document static preview assembly + related evaluator gates."""
    return is_static_frontend_vertical(build_spec, event_input) or is_interactive_frontend_vertical(
        build_spec, event_input
    )


def clamp_experience_mode_for_static_vertical(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> list[str]:
    """
    If this run is the static frontend vertical, downgrade incompatible experience_mode values
    (e.g. webgl_3d_portfolio chosen by identity derivation) so generator/evaluator contracts stay coherent.

    Mutates ``build_spec`` in place. Returns fix labels for observability.
    """
    if not is_static_frontend_vertical(build_spec, event_input):
        return []
    if is_interactive_frontend_vertical(build_spec, event_input):
        return []
    mode = build_spec.get("experience_mode")
    if not isinstance(mode, str) or not mode.strip():
        return []
    m = mode.strip()
    if m not in _STATIC_VERTICAL_INCOMPATIBLE_MODES:
        return []
    prior = m
    build_spec["experience_mode"] = _DEFAULT_STATIC_EXPERIENCE_MODE
    _log.info(
        "static_vertical: clamped experience_mode from %s to %s for static bundle coherence",
        prior,
        _DEFAULT_STATIC_EXPERIENCE_MODE,
    )
    return [f"experience_mode_clamped:{prior}->{_DEFAULT_STATIC_EXPERIENCE_MODE}"]
