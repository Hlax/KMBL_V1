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
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for continuation context.",
    )
    user_rating_context: dict[str, Any] | None = Field(
        default=None,
        description="User's rating and feedback from the most recent staging snapshot.",
    )
    user_interrupts: list[dict[str, Any]] | None = Field(
        default=None,
        description="User interrupt messages from the autonomous loop.",
    )


class GeneratorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    build_spec: dict[str, Any] = Field(default_factory=dict)
    current_working_state: dict[str, Any] = Field(default_factory=dict)
    iteration_feedback: Any | None = None
    iteration_plan: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Orchestrator hint when iteration_feedback is set: treat evaluator output as the "
            "binding amendment plan; pivot_layout_strategy / iteration_strategy pivot vs refine "
            "(duplicate, fail, stagnation, rebuild pressure, or very low design_rubric on partial → pivot); "
            "stagnation_count and pressure_recommendation echo working staging."
        ),
    )
    event_input: dict[str, Any] = Field(default_factory=dict)
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for amendment context.",
    )


class EvaluatorRoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    build_candidate: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[Any] = Field(default_factory=list)
    evaluation_targets: list[Any] = Field(default_factory=list)
    iteration_hint: int = 0
    working_staging_facts: dict[str, Any] | None = Field(
        default=None,
        description="Structured summary of current working staging surface for evaluation context.",
    )
    user_rating_context: dict[str, Any] | None = Field(
        default=None,
        description="User's rating and feedback from prior staging snapshots for calibration.",
    )


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
