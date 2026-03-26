"""Evaluator raw output → evaluation_report record (docs/07 §4.6, §1.10)."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID, uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord


def normalize_evaluator_output(
    raw: dict[str, Any],
    *,
    thread_id: UUID,
    graph_run_id: UUID,
    evaluator_invocation_id: UUID,
    build_candidate_id: UUID,
) -> EvaluationReportRecord:
    """Map KiloClaw evaluator JSON into persisted evaluation_report columns."""
    report_id = uuid4()
    status = raw.get("status", "fail")
    if status not in ("pass", "partial", "fail", "blocked"):
        status = "fail"
    summary = raw.get("summary")
    issues = raw.get("issues")
    if not isinstance(issues, list):
        issues = [] if issues is None else [issues]
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = [] if artifacts is None else [artifacts]
    return EvaluationReportRecord(
        evaluation_report_id=report_id,
        thread_id=thread_id,
        graph_run_id=graph_run_id,
        evaluator_invocation_id=evaluator_invocation_id,
        build_candidate_id=build_candidate_id,
        status=cast(Literal["pass", "partial", "fail", "blocked"], status),
        summary=str(summary) if summary is not None else None,
        issues_json=issues,
        metrics_json=metrics,
        artifacts_json=artifacts,
    )
