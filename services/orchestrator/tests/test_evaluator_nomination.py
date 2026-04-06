"""Evaluator nomination extraction for staging_snapshot.marked_for_review."""

from __future__ import annotations

from kmbl_orchestrator.contracts.evaluator_nomination import extract_evaluator_nomination


def test_nomination_defaults_when_empty() -> None:
    assert extract_evaluator_nomination(None) == {
        "marked_for_review": False,
        "mark_reason": None,
        "review_tags": [],
    }


def test_nomination_pass_defaults_marked_true_without_explicit_flag() -> None:
    out = extract_evaluator_nomination({"summary": "ok"}, evaluation_status="pass")
    assert out["marked_for_review"] is True


def test_nomination_partial_defaults_marked_false_without_explicit_flag() -> None:
    out = extract_evaluator_nomination({"summary": "needs work"}, evaluation_status="partial")
    assert out["marked_for_review"] is False


def test_nomination_explicit_partial_false_overrides_pass_status() -> None:
    out = extract_evaluator_nomination(
        {"nominate_for_review": False},
        evaluation_status="pass",
    )
    assert out["marked_for_review"] is False


def test_nomination_top_level_nominate() -> None:
    out = extract_evaluator_nomination(
        {
            "nominate_for_review": True,
            "mark_reason": " strong typography ",
            "review_tags": ["experimental", 1],
        }
    )
    assert out["marked_for_review"] is True
    assert out["mark_reason"] == "strong typography"
    assert out["review_tags"] == ["experimental", "1"]


def test_nomination_metrics_fallback() -> None:
    out = extract_evaluator_nomination(
        {
            "metrics": {
                "marked_for_review": True,
                "mark_reason": "needs polish",
                "review_tags": ["needs_polish"],
            }
        }
    )
    assert out["marked_for_review"] is True
    assert out["mark_reason"] == "needs polish"
    assert out["review_tags"] == ["needs_polish"]


def test_top_level_wins_over_metrics() -> None:
    out = extract_evaluator_nomination(
        {
            "nominate_for_review": False,
            "metrics": {"nominate_for_review": True},
        }
    )
    assert out["marked_for_review"] is False


def test_graph_state_shape_round_trips() -> None:
    """Same keys as GraphState evaluator_nomination after evaluator_node — staging_node re-extracts."""
    out = extract_evaluator_nomination(
        {
            "marked_for_review": True,
            "mark_reason": "polish",
            "review_tags": ["x"],
        }
    )
    assert out["marked_for_review"] is True
    assert out["mark_reason"] == "polish"
    assert out["review_tags"] == ["x"]


def test_non_bool_marked_for_review_is_not_truthy() -> None:
    """Strings must not be coerced true — conservative default for malformed payloads."""
    out = extract_evaluator_nomination({"marked_for_review": "true"})
    assert out["marked_for_review"] is False
