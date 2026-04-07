from __future__ import annotations

from types import SimpleNamespace

from kmbl_orchestrator.graph.nodes_pkg.evaluator import _build_pass_rubric_v1


def test_pass_rubric_scores_have_expected_keys() -> None:
    report = SimpleNamespace(
        status="partial",
        issues_json=[{"code": "lane_mix_mismatch", "severity": "medium"}],
        metrics_json={
            "required_libraries_compliance": {"satisfied": True},
            "iteration_delta": {"delta_score": 0.35},
        },
    )
    out = _build_pass_rubric_v1(report)
    assert out["rubric_version"] == 1
    scores = out["scores"]
    assert set(scores.keys()) == {
        "technical_quality",
        "creative_transformation_quality",
        "lane_coherence",
        "identity_grounding",
        "novelty_delta",
        "literalness_risk",
    }
    assert scores["lane_coherence"] == 0
