"""Post-evaluator adjustments: keep pass honest when preview surface metrics are bad."""

from __future__ import annotations

from copy import deepcopy

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.iteration_plan import preview_metrics_indicate_unhealthy


def apply_preview_surface_gate(
    report: EvaluationReportRecord,
    *,
    is_static_vertical: bool,
) -> EvaluationReportRecord:
    if not is_static_vertical or report.status != "pass":
        return report
    m = dict(report.metrics_json)

    if not preview_metrics_indicate_unhealthy(m):
        return report

    issues = list(report.issues_json)
    issues.append(
        {
            "code": "preview_surface_not_verified",
            "message": (
                "Adjusted pass→partial: metrics indicate preview/surface was not healthy or "
                "not verified."
            ),
        }
    )
    m2 = deepcopy(m)
    m2["pass_adjusted_for_preview_surface"] = True
    summary = (report.summary or "").strip()
    suffix = "[Adjusted: pass→partial — preview surface metrics not healthy.]"
    if suffix not in summary:
        summary = f"{summary} {suffix}".strip() if summary else suffix
    return report.model_copy(
        update={
            "status": "partial",
            "summary": summary,
            "issues_json": issues,
            "metrics_json": m2,
        }
    )
