"""Unit tests for scripts/smoke_stability.py (gallery checklist + classification)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from smoke_stability import (  # type: ignore[import-not-found]
    classify_failure,
    evaluate_gallery_stability,
    stability_exit_code,
)


def _minimal_staging_payload() -> dict:
    return {
        "metadata": {"working_state_patch": {"ui_gallery_strip_v1": {"items": [{"label": "a"}]}}},
        "artifacts": {"artifact_refs": []},
    }


def test_evaluate_pass_completed_gallery() -> None:
    r = evaluate_gallery_stability(
        preset="seeded_gallery_strip_v1",
        start_body={"effective_event_input": {}},
        final_status={"status": "completed", "snapshot": {}},
        detail_json={
            "role_invocations": [
                {"role_type": "planner", "status": "completed"},
                {"role_type": "generator", "status": "completed"},
                {"role_type": "evaluator", "status": "completed"},
            ],
            "associated_outputs": {"staging_snapshot_id": "s1"},
        },
        detail_http_status=200,
        staging_payload=_minimal_staging_payload(),
        staging_fetch_attempted=True,
        poll_status_codes=[200, 200],
        log_text=None,
    )
    assert r["stability_check"] == "pass"
    assert stability_exit_code(r) == 0


def test_evaluate_fail_planner() -> None:
    r = evaluate_gallery_stability(
        preset="seeded_gallery_strip_varied_v1",
        start_body={
            "effective_event_input": {
                "variation": {"run_nonce": "n1"},
            }
        },
        final_status={"status": "failed", "failure_phase": "planner"},
        detail_json={
            "role_invocations": [{"role_type": "planner", "status": "failed"}],
        },
        detail_http_status=200,
        staging_payload=None,
        staging_fetch_attempted=False,
        poll_status_codes=[200],
        log_text=None,
    )
    assert r["stability_check"] == "fail"
    assert r["failure_category"] == "planner_formatting_contract"
    assert stability_exit_code(r) == 1


def test_classify_checkpoint_duplicate() -> None:
    c = classify_failure(
        final_status={
            "status": "failed",
            "failure": {"message": "duplicate key checkpoint_pkey 23505"},
        },
        detail_json=None,
    )
    assert c == "checkpoint_idempotency"


def test_evaluate_partial_poll_500() -> None:
    r = evaluate_gallery_stability(
        preset="seeded_gallery_strip_v1",
        start_body={"effective_event_input": {}},
        final_status={"status": "completed", "snapshot": {}},
        detail_json={
            "role_invocations": [
                {"role_type": "planner", "status": "completed"},
                {"role_type": "generator", "status": "completed"},
                {"role_type": "evaluator", "status": "completed"},
            ],
            "associated_outputs": {"staging_snapshot_id": "s1"},
        },
        detail_http_status=200,
        staging_payload=_minimal_staging_payload(),
        staging_fetch_attempted=True,
        poll_status_codes=[200, 500, 200],
        log_text=None,
    )
    assert r["stability_check"] == "partial"
    assert stability_exit_code(r) == 0
