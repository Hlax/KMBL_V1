"""KiloClaw role execution client — stub until real API is wired (docs/09, docs/12 §6)."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from kmbl_orchestrator.config import Settings, get_settings

RoleType = Literal["planner", "generator", "evaluator"]


class KiloClawClient(Protocol):
    """Invokes a hosted role configuration in KiloClaw."""

    def invoke_role(self, role_type: RoleType, payload: dict[str, Any]) -> dict[str, Any]:
        """Returns structured output payload (not raw transport framing)."""
        ...


class KiloClawStubClient:
    """
    Deterministic placeholder responses for planner → generator → evaluator loop.

    TODO: Replace with httpx calls to KILOCLAW_BASE_URL using provider_config_key
    per role; handle auth (KILOCLAW_API_KEY), timeouts, and async callbacks if needed.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(self, role_type: RoleType, payload: dict[str, Any]) -> dict[str, Any]:
        _ = self._settings  # reserved for real wiring
        if role_type == "planner":
            return {
                "build_spec": {"title": "stub_spec", "steps": []},
                "constraints": {"scope": "minimal"},
                "success_criteria": ["loop_reaches_evaluator"],
                "evaluation_targets": ["smoke_check"],
            }
        if role_type == "generator":
            return {
                "proposed_changes": {"files": []},
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "https://preview.example.invalid",
            }
        if role_type == "evaluator":
            iteration = payload.get("iteration_hint", 0)
            status: Literal["pass", "partial", "fail", "blocked"] = (
                "pass" if iteration >= 0 else "partial"
            )
            return {
                "status": status,
                "summary": "stub evaluation",
                "issues": [],
                "artifacts": [],
                "metrics": {"stub": True},
            }
        raise ValueError(f"unknown role_type: {role_type}")
