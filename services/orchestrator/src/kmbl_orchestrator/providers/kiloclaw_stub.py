"""KiloClaw stub transport — deterministic test double."""

from __future__ import annotations

from typing import Any, Literal

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.providers.kiloclaw_protocol import RoleType
from kmbl_orchestrator.providers.kiloclaw_parsing import _apply_role_contract


class KiloClawStubClient:
    """
    Deterministic placeholder responses for planner → generator → evaluator loop.

    Used when transport is ``stub`` (local development without OpenClaw).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _ = self._settings
        _ = provider_config_key
        if role_type == "planner":
            raw = {
                "build_spec": {
                    "type": "stub",
                    "title": "stub_spec",
                    "steps": [],
                    # Contract smoke: archetype-aware planning (see kmbl-planner SOUL)
                    "site_archetype": "editorial",
                },
                "constraints": {"scope": "minimal"},
                "success_criteria": ["loop_reaches_evaluator"],
                "evaluation_targets": ["smoke_check"],
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "generator":
            raw = {
                "proposed_changes": {"files": []},
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "https://preview.example.invalid",
                # Bounded-iteration smoke (see kmbl-generator SOUL)
                "_kmbl_primary_move": {
                    "mode": "refine",
                    "move_type": "typography",
                    "primary_surface": "hero",
                },
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "evaluator":
            iteration = payload.get("iteration_hint", 0)
            # Return partial on first iteration to test multi-iteration loop,
            # then pass on subsequent iterations
            if iteration == 0:
                status: Literal["pass", "partial", "fail", "blocked"] = "partial"
                issues = [{"severity": "warning", "message": "First pass incomplete, needs refinement"}]
            else:
                status = "pass"
                issues = []
            raw = {
                "status": status,
                "summary": f"stub evaluation (iteration {iteration})",
                "issues": issues,
                "artifacts": [],
                "metrics": {"stub": True, "iteration": iteration},
            }
            return _apply_role_contract(role_type, raw)
        raise ValueError(f"unknown role_type: {role_type}")
