"""Pydantic wire contracts for KiloClaw role JSON (explicit errors when malformed)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RoleType = Literal["planner", "generator", "evaluator"]


class PlannerRoleOutput(BaseModel):
    """Planner must return a structured plan; `build_spec` is required.

    When ``crawl_context`` is present in the input (i.e. the orchestrator offered
    frontier URLs), the planner **should** include ``selected_urls`` in the
    top-level output or inside ``build_spec``.  ``selected_urls`` must be a
    list of absolute HTTP(S) URLs chosen from the offered ``next_urls_to_crawl``.
    If no URLs were used, return an empty list rather than omitting the field.

    **build_spec conventions (orchestrator-aware, not all validated here):**

    - ``creative_brief`` — freeform creative direction (mood, direction_summary,
      identity_interpretation). Prefer this for exploratory language; the
      orchestrator compacts long strings in ``compact_planner_wire_output``.
    - ``machine_constraints`` — optional dict for stable, machine-readable caps
      (e.g. vertical ids, feature flags). Use alongside top-level ``constraints``;
      normalizers may merge or prefer one source; keep prose out of this object.
    - ``literal_success_checks`` — on **iteration_index 0**, the orchestrator may
      cap how many checks apply so the first generator pass is not over-constrained
      (see ``apply_first_iteration_literal_cap`` in ``planner_normalize``).
    """

    model_config = ConfigDict(extra="allow")

    build_spec: dict[str, Any]
    selected_urls: list[str] = Field(
        default_factory=list,
        description=(
            "URLs the planner actually used from crawl_context.next_urls_to_crawl. "
            "Must only contain URLs from the offered frontier or explicitly allowed "
            "external inspiration URLs. Return [] when no URLs were consulted. "
            "Orchestrator uses this for tier-2 (selected_by_planner) evidence."
        ),
    )
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
    """Generator must include at least one non-empty primary field **or** a structured failure."""

    model_config = ConfigDict(extra="allow")

    proposed_changes: Any | None = None
    updated_state: Any | None = None
    artifact_outputs: Any | None = None
    sandbox_ref: str | None = None
    preview_url: str | None = None
    # Local-build lane: orchestrator expands files into artifact_outputs before normalize.
    workspace_manifest_v1: dict[str, Any] | None = None
    # Machine-readable failure when the model cannot produce artifacts (no prose fallback).
    # When present with non-empty ``code`` and ``message``, primary fields may be empty.
    contract_failure: dict[str, Any] | None = None
    # Cool lane: explicit status (orchestrator validates vocabulary when lane is on).
    # ``status`` must be one of: executed | downgraded | cannot_fulfill (lowercase).
    execution_acknowledgment: dict[str, Any] | None = None

    @model_validator(mode="after")
    def at_least_one_primary_field_or_contract_failure(self) -> GeneratorRoleOutput:
        cf = self.contract_failure
        if isinstance(cf, dict):
            code = cf.get("code")
            msg = cf.get("message")
            if isinstance(code, str) and code.strip() and isinstance(msg, str) and msg.strip():
                return self

        has_proposed = _is_non_empty(self.proposed_changes)
        has_state = _is_non_empty(self.updated_state)
        has_artifacts = _is_non_empty(self.artifact_outputs)
        wm = self.workspace_manifest_v1
        has_workspace_manifest = (
            isinstance(wm, dict)
            and isinstance(wm.get("files"), list)
            and len(wm["files"]) > 0
            and isinstance(self.sandbox_ref, str)
            and self.sandbox_ref.strip()
        )

        if not (has_proposed or has_state or has_artifacts or has_workspace_manifest):
            raise ValueError(
                "generator output must include at least one non-empty field: "
                "proposed_changes, updated_state, artifact_outputs, "
                "or workspace_manifest_v1 with files and sandbox_ref "
                "(empty dict/list or list of empty dicts not accepted), "
                "or contract_failure with string code and message"
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
