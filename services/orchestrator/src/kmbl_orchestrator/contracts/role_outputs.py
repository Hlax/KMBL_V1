"""Pydantic wire contracts for KiloClaw role JSON (explicit errors when malformed)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

RoleType = Literal["planner", "generator", "evaluator"]


class PlannerRoleOutput(BaseModel):
    """Planner must return a structured plan; `build_spec` is required."""

    model_config = ConfigDict(extra="allow")

    build_spec: dict[str, Any]
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[Any] = Field(default_factory=list)
    evaluation_targets: list[Any] = Field(default_factory=list)


def _is_non_empty(value: Any) -> bool:
    """Check if a value is semantically non-empty (not None, not empty dict/list)."""
    if value is None:
        return False
    if isinstance(value, dict) and not value:
        return False
    if isinstance(value, list):
        # Empty list or list of only empty dicts is considered empty
        if not value:
            return False
        # Check if all items are empty dicts
        if all(isinstance(item, dict) and not item for item in value):
            return False
    return True


class GeneratorRoleOutput(BaseModel):
    """Generator must include at least one non-empty primary field."""

    model_config = ConfigDict(extra="allow")

    proposed_changes: Any | None = None
    updated_state: Any | None = None
    artifact_outputs: Any | None = None
    sandbox_ref: str | None = None
    preview_url: str | None = None

    @model_validator(mode="after")
    def at_least_one_primary_field(self) -> GeneratorRoleOutput:
        # Check for at least one non-empty primary field
        has_proposed = _is_non_empty(self.proposed_changes)
        has_state = _is_non_empty(self.updated_state)
        has_artifacts = _is_non_empty(self.artifact_outputs)
        
        if not (has_proposed or has_state or has_artifacts):
            raise ValueError(
                "generator output must include at least one non-empty field: "
                "proposed_changes, updated_state, or artifact_outputs "
                "(empty dict/list or list of empty dicts not accepted)"
            )
        return self


class EvaluatorRoleOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["pass", "partial", "fail", "blocked"]
    summary: str | None = None
    issues: list[Any] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Any] = Field(default_factory=list)


def validate_role_contract(role_type: RoleType, body: dict[str, Any]) -> dict[str, Any]:
    """
    Validate provider JSON against the role contract; return the same dict on success.

    Raises :class:`pydantic.ValidationError` on failure (caller maps to transport errors).
    """
    if role_type == "planner":
        PlannerRoleOutput.model_validate(body)
    elif role_type == "generator":
        GeneratorRoleOutput.model_validate(body)
    elif role_type == "evaluator":
        EvaluatorRoleOutput.model_validate(body)
    else:
        raise ValueError(f"unknown role_type: {role_type}")
    return body


__all__ = [
    "EvaluatorRoleOutput",
    "GeneratorRoleOutput",
    "PlannerRoleOutput",
    "RoleType",
    "validate_role_contract",
]
