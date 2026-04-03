"""Unit tests for compute_evaluator_decision and maybe_suppress_duplicate_staging.

These test the pure routing logic independently of graph wiring.
"""

from __future__ import annotations

import pytest

from kmbl_orchestrator.graph.helpers import (
    compute_evaluator_decision,
    maybe_suppress_duplicate_staging,
)


class TestComputeEvaluatorDecision:
    """Pure‐function tests: (status, iteration, max_iterations) → (decision, reason)."""

    def test_pass_always_stages(self) -> None:
        d, r = compute_evaluator_decision("pass", 0, 3)
        assert d == "stage"
        assert r is None

    def test_pass_stages_even_on_first_iteration(self) -> None:
        d, r = compute_evaluator_decision("pass", 0, 0)
        assert d == "stage"
        assert r is None

    def test_blocked_always_interrupts(self) -> None:
        d, r = compute_evaluator_decision("blocked", 0, 3)
        assert d == "interrupt"
        assert r == "evaluator_blocked"

    def test_blocked_interrupts_at_max(self) -> None:
        d, r = compute_evaluator_decision("blocked", 3, 3)
        assert d == "interrupt"
        assert r == "evaluator_blocked"

    def test_fail_iterates_when_under_max(self) -> None:
        d, r = compute_evaluator_decision("fail", 0, 3)
        assert d == "iterate"
        assert r is None

    def test_fail_stages_at_max_iterations(self) -> None:
        """Key degraded path: fail at max iterations → stages anyway."""
        d, r = compute_evaluator_decision("fail", 3, 3)
        assert d == "stage"
        assert r is None

    def test_partial_iterates_when_under_max(self) -> None:
        d, r = compute_evaluator_decision("partial", 1, 5)
        assert d == "iterate"
        assert r is None

    def test_partial_stages_at_max_iterations(self) -> None:
        """Partial at max iterations → stages anyway (degraded-success path)."""
        d, r = compute_evaluator_decision("partial", 5, 5)
        assert d == "stage"
        assert r is None

    def test_fail_stages_at_boundary(self) -> None:
        """iteration == max_iterations means we have exhausted retries."""
        d, r = compute_evaluator_decision("fail", 10, 10)
        assert d == "stage"
        assert r is None

    def test_fail_iterates_one_before_max(self) -> None:
        d, r = compute_evaluator_decision("fail", 9, 10)
        assert d == "iterate"
        assert r is None

    def test_unknown_status_interrupts(self) -> None:
        d, r = compute_evaluator_decision("garbage", 0, 3)
        assert d == "interrupt"
        assert r == "unknown_eval_status"

    def test_empty_status_interrupts(self) -> None:
        d, r = compute_evaluator_decision("", 0, 3)
        assert d == "interrupt"
        assert r == "unknown_eval_status"

    @pytest.mark.parametrize("max_iter", [0, 1, 5, 10])
    def test_pass_stages_regardless_of_max_iterations(self, max_iter: int) -> None:
        d, _ = compute_evaluator_decision("pass", 0, max_iter)
        assert d == "stage"

    @pytest.mark.parametrize("iteration", [0, 1, 2])
    def test_partial_iterates_below_max_3(self, iteration: int) -> None:
        d, _ = compute_evaluator_decision("partial", iteration, 3)
        assert d == "iterate"


class TestMaybeSuppressDuplicateStaging:
    """Test the duplicate-output suppression logic."""

    def test_suppresses_fail_with_duplicate_rejection(self) -> None:
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "stage", None, "fail", {"duplicate_rejection": True}
        )
        assert d == "interrupt"
        assert r == "duplicate_output_after_max_iterations"
        assert suppressed is True

    def test_does_not_suppress_partial_with_duplicate(self) -> None:
        """Partial + duplicate does NOT suppress — this is the subtle gap."""
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "stage", None, "partial", {"duplicate_rejection": True}
        )
        assert d == "stage"
        assert r is None
        assert suppressed is False

    def test_does_not_suppress_without_duplicate_flag(self) -> None:
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "stage", None, "fail", {}
        )
        assert d == "stage"
        assert r is None
        assert suppressed is False

    def test_does_not_suppress_iterate_decision(self) -> None:
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "iterate", None, "fail", {"duplicate_rejection": True}
        )
        assert d == "iterate"
        assert r is None
        assert suppressed is False

    def test_handles_none_metrics(self) -> None:
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "stage", None, "fail", None
        )
        assert d == "stage"
        assert suppressed is False

    def test_does_not_suppress_pass(self) -> None:
        d, r, suppressed = maybe_suppress_duplicate_staging(
            "stage", None, "pass", {"duplicate_rejection": True}
        )
        assert d == "stage"
        assert suppressed is False
