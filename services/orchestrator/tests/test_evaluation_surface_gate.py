"""Preview surface gate: pass→partial when metrics show an unhealthy preview."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.evaluation_surface_gate import apply_preview_surface_gate


def _report(status: str, metrics: dict) -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status=status,  # type: ignore[arg-type]
        summary="ok",
        issues_json=[],
        metrics_json=metrics,
        artifacts_json=[],
    )


def test_non_static_skips_gate() -> None:
    r = _report("pass", {"preview_load_failed": True})
    out = apply_preview_surface_gate(r, is_static_vertical=False)
    assert out.status == "pass"


def test_non_pass_skips_gate() -> None:
    r = _report("partial", {"preview_load_failed": True})
    out = apply_preview_surface_gate(r, is_static_vertical=True)
    assert out.status == "partial"


def test_pass_downgraded_when_preview_unhealthy() -> None:
    r = _report("pass", {"preview_load_failed": True})
    out = apply_preview_surface_gate(r, is_static_vertical=True)
    assert out.status == "partial"
    assert out.metrics_json.get("pass_adjusted_for_preview_surface") is True
    codes = [i.get("code") for i in out.issues_json if isinstance(i, dict)]
    assert "preview_surface_not_verified" in codes


def test_pass_unchanged_when_preview_ok() -> None:
    r = _report("pass", {"preview": {"loaded": True, "ok": True}})
    out = apply_preview_surface_gate(r, is_static_vertical=True)
    assert out.status == "pass"
