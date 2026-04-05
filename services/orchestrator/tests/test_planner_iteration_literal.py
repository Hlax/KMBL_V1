"""Unit tests for first-iteration literal check capping (no FastAPI/LangGraph deps)."""

from __future__ import annotations

from kmbl_orchestrator.contracts.planner_normalize import apply_first_iteration_literal_cap


def test_apply_first_iteration_literal_cap_only_iteration_zero() -> None:
    many = [{"needle": f"x{i}"} for i in range(20)]
    bs: dict = {"type": "generic", "title": "T", "literal_success_checks": many}
    out0, capped0 = apply_first_iteration_literal_cap(dict(bs), 0)
    assert capped0 is True
    assert len(out0["literal_success_checks"]) == 8
    out1, capped1 = apply_first_iteration_literal_cap(dict(bs), 1)
    assert capped1 is False
    assert len(out1["literal_success_checks"]) == 20
