"""
Structured handling for ``interactive_frontend_app_v1`` planner ``build_spec.execution_contract``.

Only applied when ``is_interactive_frontend_vertical`` — static and other verticals are untouched.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kmbl_orchestrator.runtime.generator_library_policy import (
    GAUSSIAN_SPLAT_ESCALATION_LANE,
    GAUSSIAN_SPLAT_LIBRARY_PRIMARY,
    HEAVY_WEBGL_WGSL_TOKEN,
    PRIMARY_LANE_DEFAULT_LIBRARIES,
)
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    WEBGL_EXPERIENCE_MODES,
    is_interactive_frontend_vertical,
)

_log = logging.getLogger(__name__)

# Fields we normalize/validate explicitly; other ``execution_contract`` keys are preserved.
_TRACKED_EC_KEYS = frozenset(
    {
        "allowed_libraries",
        "required_libraries",
        "required_interactions",
        "interactive_runtime_tier",
        "webgl_ambition_ack",
        "lane_escalation_hint",
        "escalation_lane",
    },
)

DEFAULT_LANE_ESCALATION = (
    "full_spa_or_asset_pipeline_not_in_scope_use_habitat_or_future_webgl_lane"
)
DEFAULT_WEBGL_ACK = "visible_scene_or_honest_downgrade"


class InteractiveExecutionContractV1(BaseModel):
    """Canonical shape for interactive lane execution hints (subset of full contract)."""

    model_config = ConfigDict(extra="ignore")

    allowed_libraries: list[str] = Field(default_factory=list)
    required_libraries: list[str] = Field(default_factory=list)
    required_interactions: list[dict[str, Any]] = Field(default_factory=list)
    interactive_runtime_tier: str = "bounded_preview"
    webgl_ambition_ack: str | None = None
    lane_escalation_hint: str | None = None
    escalation_lane: str | None = None

    @field_validator("allowed_libraries", "required_libraries", mode="before")
    @classmethod
    def _coerce_libs(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for x in v[:8]:
            if isinstance(x, str) and x.strip():
                out.append(x.strip().lower())
            elif x is not None:
                s = str(x).strip()
                if s:
                    out.append(s.lower())
        return out

    @field_validator("required_interactions", mode="before")
    @classmethod
    def _coerce_ri(cls, v: Any) -> list[dict[str, Any]]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[dict[str, Any]] = []
        for x in v[:8]:
            if isinstance(x, dict):
                out.append(x)
            elif isinstance(x, str) and x.strip():
                out.append({"id": x.strip()})
        return out

    @field_validator("interactive_runtime_tier", mode="before")
    @classmethod
    def _tier(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "bounded_preview"
        return str(v).strip()

    @field_validator("escalation_lane", mode="before")
    @classmethod
    def _escalation_lane(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        return str(v).strip().lower()[:48]


AmbitionProfile = Literal["bounded_preview", "heavy_webgl_ask"]


class InteractiveBuildSpecHardeningMeta(BaseModel):
    """Observability for interactive planning — stored on planner raw payload and graph events."""

    model_config = ConfigDict(extra="forbid")

    applied: bool = False
    interactive_vertical: bool = False
    fixes: list[str] = Field(default_factory=list)
    fields_missing_before: dict[str, bool] = Field(default_factory=dict)
    ambition_profile: AmbitionProfile = "bounded_preview"
    out_of_scope_signals: list[str] = Field(default_factory=list)
    interaction_intent_weak: bool = False
    validation_ok: bool = True
    validation_error: str | None = None


def _out_of_scope_signals(ec: dict[str, Any], build_spec: dict[str, Any]) -> list[str]:
    sig: list[str] = []
    st = ec.get("surface_type")
    if isinstance(st, str):
        sl = st.lower()
        if any(x in sl for x in ("spa", "multi_page_app", "client_router", "react-router")):
            sig.append("surface_type_suggests_spa_or_router")
    raw_steps = str(build_spec.get("steps") or "")
    if any(k in raw_steps.lower() for k in ("vite.config", "webpack", "monorepo", "npm workspace")):
        sig.append("steps_mention_bundler_workspace")
    return sig


def apply_interactive_build_spec_hardening(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> tuple[dict[str, Any], InteractiveBuildSpecHardeningMeta]:
    """
    Validate and merge ``execution_contract`` for interactive verticals; return metadata for logging.

    Non-interactive: returns ``(build_spec, meta)`` with ``applied=False`` and no mutation.
    """
    meta = InteractiveBuildSpecHardeningMeta(interactive_vertical=is_interactive_frontend_vertical(build_spec, event_input))
    if not meta.interactive_vertical:
        meta.applied = False
        return build_spec, meta

    meta.applied = True
    bs = build_spec
    ec_in = bs.get("execution_contract")
    missing_before: dict[str, bool] = {}
    for k in _TRACKED_EC_KEYS:
        missing_before[k] = not (isinstance(ec_in, dict) and k in ec_in and ec_in.get(k) is not None)
    meta.fields_missing_before = missing_before

    fixes: list[str] = []
    if not isinstance(ec_in, dict):
        ec = {}
        bs["execution_contract"] = ec
        fixes.append("execution_contract_initialized")
    else:
        ec = copy.deepcopy(ec_in)

    # Coerce / default tracked fields (intent: fewer silent surprises — track each fix)
    if not isinstance(ec.get("allowed_libraries"), list):
        if ec.get("allowed_libraries") is not None:
            fixes.append("allowed_libraries_coerced_to_list")
        ec["allowed_libraries"] = ec.get("allowed_libraries") if isinstance(ec.get("allowed_libraries"), list) else []

    if not isinstance(ec.get("required_interactions"), list):
        if ec.get("required_interactions") is not None:
            fixes.append("required_interactions_coerced_to_list")
        ec["required_interactions"] = (
            ec["required_interactions"] if isinstance(ec.get("required_interactions"), list) else []
        )

    ri_raw = ec.get("required_interactions")
    if isinstance(ri_raw, list):
        norm_ri: list[dict[str, Any]] = []
        had_string_entries = False
        for x in ri_raw[:8]:
            if isinstance(x, dict):
                norm_ri.append(x)
            elif isinstance(x, str) and x.strip():
                had_string_entries = True
                norm_ri.append({"id": x.strip()})
        if had_string_entries:
            fixes.append("required_interactions_entries_normalized")
        ec["required_interactions"] = norm_ri

    if ec.get("interactive_runtime_tier") is None or (
        isinstance(ec.get("interactive_runtime_tier"), str) and not str(ec["interactive_runtime_tier"]).strip()
    ):
        ec["interactive_runtime_tier"] = "bounded_preview"
        fixes.append("interactive_runtime_tier_defaulted")

    em = (bs.get("experience_mode") or "").strip().lower()
    if em in WEBGL_EXPERIENCE_MODES:
        meta.ambition_profile = "heavy_webgl_ask"
        if not ec.get("webgl_ambition_ack"):
            ec["webgl_ambition_ack"] = DEFAULT_WEBGL_ACK
            fixes.append("webgl_ambition_ack_defaulted")
    else:
        meta.ambition_profile = "bounded_preview"

    if ec.get("lane_escalation_hint") is None or (
        isinstance(ec.get("lane_escalation_hint"), str) and not str(ec["lane_escalation_hint"]).strip()
    ):
        ec["lane_escalation_hint"] = DEFAULT_LANE_ESCALATION
        fixes.append("lane_escalation_hint_defaulted")

    # Primary interactive lane: default three + gsap when planner omitted libraries (see docs/generator-library-policy.md).
    al = ec.get("allowed_libraries")
    if not isinstance(al, list) or len([x for x in al if isinstance(x, str) and x.strip()]) == 0:
        ec["allowed_libraries"] = list(PRIMARY_LANE_DEFAULT_LIBRARIES)
        fixes.append("allowed_libraries_defaulted_primary_lane")

    # required_libraries: formalize when absent.  If planner set allowed but not
    # required, inherit allowed as required for the primary interactive lane.
    rl = ec.get("required_libraries")
    if not isinstance(rl, list) or len([x for x in rl if isinstance(x, str) and x.strip()]) == 0:
        al_effective = ec.get("allowed_libraries")
        if isinstance(al_effective, list):
            ec["required_libraries"] = list(al_effective)
        else:
            ec["required_libraries"] = list(PRIMARY_LANE_DEFAULT_LIBRARIES)
        fixes.append("required_libraries_defaulted_from_allowed")

    # Heavy WebGPU ambition modes: append wgsl so execution_contract signals WGSL/WebGPU path (not default for flat modes).
    em_libs = (bs.get("experience_mode") or "").strip().lower()
    if em_libs in WEBGL_EXPERIENCE_MODES:
        libs_cur = ec.get("allowed_libraries")
        if isinstance(libs_cur, list):
            norm = [str(x).strip().lower() for x in libs_cur if isinstance(x, str) and str(x).strip()]
            if HEAVY_WEBGL_WGSL_TOKEN not in norm:
                if len(norm) >= 8:
                    norm = norm[:7]
                norm.append(HEAVY_WEBGL_WGSL_TOKEN)
                ec["allowed_libraries"] = norm
                fixes.append("allowed_libraries_appended_wgsl_for_heavy_webgl_ambition")

    # Gaussian splat specialist lane: ensure Three + primary splat viewer when planner selected lane.
    if (ec.get("escalation_lane") or "").strip().lower() == GAUSSIAN_SPLAT_ESCALATION_LANE:
        libs_cur = ec.get("allowed_libraries")
        if isinstance(libs_cur, list):
            norm = [str(x).strip().lower() for x in libs_cur if isinstance(x, str) and str(x).strip()]
            for token in ("three", "gsap", GAUSSIAN_SPLAT_LIBRARY_PRIMARY):
                if token not in norm and len(norm) < 8:
                    norm.append(token)
            ec["allowed_libraries"] = norm
            fixes.append("allowed_libraries_merged_for_gaussian_splat_lane")

    # Pydantic validation on tracked slice (extras on ``ec`` remain untouched)
    tracked = {k: ec.get(k) for k in _TRACKED_EC_KEYS}
    try:
        validated = InteractiveExecutionContractV1.model_validate(tracked)
        vd = validated.model_dump(mode="python")
        for k in _TRACKED_EC_KEYS:
            ec[k] = vd[k]
        meta.validation_ok = True
    except Exception as ex:
        meta.validation_ok = False
        meta.validation_error = f"{type(ex).__name__}: {ex}"[:500]
        _log.warning("interactive execution_contract pydantic validation degraded: %s", meta.validation_error)

    bs["execution_contract"] = ec

    meta.out_of_scope_signals = _out_of_scope_signals(ec, bs)

    ri_final = ec.get("required_interactions")
    if isinstance(ri_final, list) and len(ri_final) == 0:
        meta.interaction_intent_weak = True
        fixes.append("required_interactions_empty_weak_intent")

    meta.fixes = fixes
    return build_spec, meta


def validate_interactive_execution_contract_slice(execution_contract: dict[str, Any]) -> None:
    """
    Validate the tracked interactive slice (raises ``ValidationError`` from Pydantic on failure).

    Used by planner persist-time validation after orchestrator hardening.
    """
    tracked = {k: execution_contract.get(k) for k in _TRACKED_EC_KEYS}
    InteractiveExecutionContractV1.model_validate(tracked)


def normalize_interactive_build_spec_inplace(
    build_spec: dict[str, Any],
    event_input: dict[str, Any],
) -> list[str]:
    """Backward-compatible: mutate build_spec and return fix label list."""
    _, meta = apply_interactive_build_spec_hardening(build_spec, event_input)
    return meta.fixes
