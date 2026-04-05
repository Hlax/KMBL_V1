"""Pydantic role wire contracts (planner / generator / evaluator)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kmbl_orchestrator.contracts.role_outputs import (
    EvaluatorRoleOutput,
    GeneratorRoleOutput,
    PlannerRoleOutput,
    validate_role_contract,
)


def test_planner_requires_build_spec() -> None:
    with pytest.raises(ValidationError):
        PlannerRoleOutput.model_validate({"constraints": {}})


def test_generator_requires_at_least_one_primary_key() -> None:
    with pytest.raises(ValidationError):
        GeneratorRoleOutput.model_validate({"sandbox_ref": "x"})


def test_evaluator_validates_status() -> None:
    with pytest.raises(ValidationError):
        EvaluatorRoleOutput.model_validate({"status": "maybe"})


def test_validate_role_contract_passes_through() -> None:
    body = {
        "build_spec": {"t": 1},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    assert validate_role_contract("planner", body) is body


def test_validate_role_contract_generator() -> None:
    # Generator requires at least one non-empty primary field
    raw = {"proposed_changes": {"files": [{"path": "test.txt"}]}, "artifact_outputs": None, "updated_state": None}
    assert validate_role_contract("generator", raw) == raw


def test_generator_rejects_all_empty_fields() -> None:
    # Empty dict/list or list of empty dicts should be rejected
    with pytest.raises(ValidationError):
        GeneratorRoleOutput.model_validate({"proposed_changes": {}, "artifact_outputs": [], "updated_state": {}})

    with pytest.raises(ValidationError):
        GeneratorRoleOutput.model_validate({"proposed_changes": None, "artifact_outputs": [{}], "updated_state": None})


def test_generator_accepts_contract_failure_without_primary_fields() -> None:
    raw = {
        "contract_failure": {"code": "context_too_large", "message": "Cannot complete within limits."},
        "proposed_changes": None,
        "artifact_outputs": None,
        "updated_state": None,
    }
    assert validate_role_contract("generator", raw) == raw
