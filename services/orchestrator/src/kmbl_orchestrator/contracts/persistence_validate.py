"""Second-pass validation before persisting domain rows (post wire-contract)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

RoleType = Literal["planner", "generator", "evaluator"]


class _PlannerBuildSpecShape(BaseModel):
    """Minimum structure after normalization (type/title default in planner_normalize)."""

    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    steps: list[Any] = Field(default_factory=list)


class _PlannerPersistableBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    build_spec: _PlannerBuildSpecShape


def _is_non_empty_generator_field(value: Any) -> bool:
    """Check if a generator field is semantically non-empty."""
    if value is None:
        return False
    if isinstance(value, dict) and not value:
        return False
    if isinstance(value, list):
        if not value:
            return False
        # List of only empty dicts is considered empty
        if all(isinstance(item, dict) and not item for item in value):
            return False
    return True


class _GeneratorPersistableBody(BaseModel):
    """Ensure at least one persistable artifact exists with actual content."""

    proposed_changes: Any | None = None
    updated_state: Any | None = None
    artifact_outputs: Any | None = None

    @model_validator(mode="after")
    def at_least_one_persistable(self) -> _GeneratorPersistableBody:
        has_proposed = _is_non_empty_generator_field(self.proposed_changes)
        has_state = _is_non_empty_generator_field(self.updated_state)
        has_artifacts = _is_non_empty_generator_field(self.artifact_outputs)
        
        if not (has_proposed or has_state or has_artifacts):
            raise ValueError(
                "no persistable generator fields (all are None, empty, or contain only empty dicts)"
            )
        return self


class _EvaluatorPersistableRaw(BaseModel):
    """Evaluator output must be structurally safe before evaluation_report row."""

    model_config = ConfigDict(extra="allow")

    status: Literal["pass", "partial", "fail", "blocked"]
    summary: str = ""
    issues: list[Any] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def summary_coerce(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("issues", mode="before")
    @classmethod
    def issues_must_be_list(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        raise ValueError("issues must be an array")


def validate_role_output_for_persistence(role_type: RoleType, raw: dict[str, Any]) -> None:
    """
    Raises ValidationError if outputs are not safe to normalize into product tables.

    Call only after wire-level role output contract passes.
    """
    if role_type == "planner":
        _PlannerPersistableBody.model_validate(raw)
    elif role_type == "generator":
        _GeneratorPersistableBody.model_validate(raw)
    elif role_type == "evaluator":
        _EvaluatorPersistableRaw.model_validate(raw)
    else:
        raise ValueError(f"unknown role_type: {role_type}")


__all__ = ["validate_role_output_for_persistence", "ValidationError"]
