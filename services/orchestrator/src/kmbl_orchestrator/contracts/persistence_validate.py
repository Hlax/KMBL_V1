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


class _GeneratorPersistableBody(BaseModel):
    """Ensure at least one persistable artifact exists beyond empty dict."""

    proposed_changes: Any | None = None
    updated_state: Any | None = None
    artifact_outputs: Any | None = None

    @model_validator(mode="after")
    def at_least_one_persistable(self) -> _GeneratorPersistableBody:
        if (
            self.proposed_changes is None
            and self.updated_state is None
            and self.artifact_outputs is None
        ):
            raise ValueError("no persistable generator fields")
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
