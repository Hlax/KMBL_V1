from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.graph.nodes_pkg.evaluator import reconcile_evaluator_false_negatives


def _report_with_issues(*, issues: list[dict]) -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="partial",
        summary="x",
        issues_json=issues,
        metrics_json={},
        artifacts_json=[],
    )


def test_reconcile_drops_missing_preview_when_operator_preview_exists() -> None:
    report = _report_with_issues(
        issues=[
            {"code": "missing_preview", "message": "preview unavailable"},
            {"code": "other", "message": "keep"},
        ]
    )
    bc = {"artifact_outputs": []}
    pr = {"operator_preview_url": "http://127.0.0.1:8010/orchestrator/runs/g/candidate-preview"}

    out = reconcile_evaluator_false_negatives(report, build_candidate=bc, preview_resolution=pr)

    assert len(out.issues_json) == 1
    assert out.issues_json[0]["code"] == "other"
    rec = out.metrics_json.get("kmbl_issue_reconciliation_v1")
    assert isinstance(rec, dict)
    assert rec.get("dropped_missing_preview") == 1


def test_reconcile_drops_missing_h1_when_summary_has_h1_text() -> None:
    report = _report_with_issues(
        issues=[
            {
                "code": "missing_element",
                "selector": "h1",
                "message": "Missing h1 heading",
            },
            {"code": "other", "message": "keep"},
        ]
    )
    bc = {
        "kmbl_build_candidate_summary_v1": {
            "h1_text": "Root H1",
            "sections_or_modules": {"h1_text": "Nested H1"},
        },
        "artifact_outputs": [],
    }

    out = reconcile_evaluator_false_negatives(report, build_candidate=bc, preview_resolution={})

    assert len(out.issues_json) == 1
    assert out.issues_json[0]["code"] == "other"
    rec = out.metrics_json.get("kmbl_issue_reconciliation_v1")
    assert isinstance(rec, dict)
    assert rec.get("dropped_missing_h1") == 1


def test_reconcile_keeps_missing_preview_without_local_preview_evidence() -> None:
    report = _report_with_issues(issues=[{"code": "missing_preview", "message": "preview unavailable"}])

    out = reconcile_evaluator_false_negatives(report, build_candidate={"artifact_outputs": []}, preview_resolution={})

    assert len(out.issues_json) == 1
    assert out.issues_json[0]["code"] == "missing_preview"
    assert "kmbl_issue_reconciliation_v1" not in out.metrics_json
