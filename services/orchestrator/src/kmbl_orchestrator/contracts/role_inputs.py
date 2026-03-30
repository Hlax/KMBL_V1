"""Validated outbound payloads to KiloClaw (orchestrator → provider boundary)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RoleType = Literal["planner", "generator", "evaluator"]


class PlannerRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    identity_context: dict[str, Any] = Field(default_factory=dict)
    memory_context: dict[str, Any] = Field(default_factory=dict)
    event_input: dict[str, Any] = Field(default_factory=dict)
    current_state_summary: dict[str, Any] = Field(default_factory=dict)


class GeneratorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    build_spec: dict[str, Any] = Field(default_factory=dict)
    current_working_state: dict[str, Any] = Field(default_factory=dict)
    iteration_feedback: Any | None = None
    # Same event_input the planner saw (scenario, task, constraints, variation). Omitted in [].
    event_input: dict[str, Any] = Field(default_factory=dict)


class EvaluatorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    build_candidate: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[Any] = Field(default_factory=list)
    evaluation_targets: list[Any] = Field(default_factory=list)
    iteration_hint: int = 0


def validate_role_input(role_type: RoleType, payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a JSON-safe dict for the provider. Raises ValidationError on bad input."""
    if role_type == "planner":
        return PlannerRoleInput.model_validate(payload).model_dump(mode="json")
    if role_type == "generator":
        return GeneratorRoleInput.model_validate(payload).model_dump(mode="json")
    if role_type == "evaluator":
        return EvaluatorRoleInput.model_validate(payload).model_dump(mode="json")
    raise ValueError(f"unknown role_type: {role_type}")


__all__ = [
    "EvaluatorRoleInput",
    "GeneratorRoleInput",
    "PlannerRoleInput",
    "RoleType",
    "validate_role_input",
    "ValidationError",
]
