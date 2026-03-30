"""gallery_strip_harness merged metrics on evaluation_report."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord
from kmbl_orchestrator.normalize.gallery_strip_harness import merge_gallery_strip_harness_checks


def _bc_with_strip(patch: dict) -> BuildCandidateRecord:
    return BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        working_state_patch_json=patch,
        artifact_refs_json=[],
        sandbox_ref=None,
        preview_url=None,
        status="generated",
    )


def _report() -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=uuid4(),
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
        artifacts_json=[],
    )


def test_harness_adds_metrics_when_strip_present() -> None:
    bc = _bc_with_strip(
        {
            "ui_gallery_strip_v1": {
                "items": [
                    {
                        "label": "One",
                        "caption": "c",
                        "image_url": "https://example.com/i.png",
                        "href": "https://example.com/h",
                        "image_artifact_key": "k1",
                    },
                ],
            },
        }
    )
    r0 = _report()
    r1 = merge_gallery_strip_harness_checks(r0, bc, probe_urls=False)
    assert r1.metrics_json.get("gallery_strip_v1_present") is True
    assert r1.metrics_json.get("gallery_strip_v1_item_count") == 1
    assert r1.metrics_json.get("gallery_strip_v1_href_all_http") is True
    assert r1.metrics_json.get("gallery_strip_v1_url_probe_skipped") is True


def test_harness_noop_without_strip() -> None:
    bc = _bc_with_strip({"other": 1})
    r0 = _report()
    r1 = merge_gallery_strip_harness_checks(r0, bc, probe_urls=False)
    assert r1.metrics_json == {}
