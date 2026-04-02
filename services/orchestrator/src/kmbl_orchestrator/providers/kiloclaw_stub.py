"""KiloClaw stub transport — deterministic test double."""

from __future__ import annotations

import logging
from typing import Any, Literal

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.providers.kiloclaw_protocol import RoleType
from kmbl_orchestrator.providers.kiloclaw_parsing import _apply_role_contract

_log = logging.getLogger(__name__)


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
        _log.warning(
            "KILOCLAW_STUB_TRANSPORT invoke_role role=%s config_key=%s — NOT a real OpenClaw/KiloClaw call",
            role_type,
            provider_config_key,
        )
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
                "proposed_changes": {
                    "files": [
                        {
                            "path": "component/hero.html",
                            "language": "html",
                            "content": "<section class='hero'><h1>Stub Hero</h1>"
                            "<p>Stub portfolio content</p></section>",
                        }
                    ]
                },
                "artifact_outputs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/hero.html",
                        "language": "html",
                        "content": "<section class='hero'><h1>Stub Hero</h1>"
                        "<p>Stub portfolio content</p></section>",
                        "entry_for_preview": True,
                        "bundle_id": "stub-bundle-001",
                    }
                ],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "http://localhost:3000/stub-preview",
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
                "metrics": {
                    "stub": True,
                    "iteration": iteration,
                    "alignment_report": {
                        "must_mention_hit_rate": 0.75 if status == "pass" else 0.4,
                        "palette_used": True if status == "pass" else False,
                        "tone_reflected": True if status == "pass" else False,
                        "structural_present": True,
                    },
                },
            }
            return _apply_role_contract(role_type, raw)
        raise ValueError(f"unknown role_type: {role_type}")
