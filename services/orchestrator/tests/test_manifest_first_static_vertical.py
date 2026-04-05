"""Manifest-first static vertical policy + evaluator preview resolution."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.session_staging_links import (
    resolve_evaluator_preview_resolution,
    resolve_evaluator_preview_url,
)
from kmbl_orchestrator.runtime.workspace_ingest import (
    workspace_ingest_not_attempted_reason,
    workspace_ingest_should_attempt,
)


def test_workspace_ingest_not_attempted_reason_no_manifest() -> None:
    r = workspace_ingest_not_attempted_reason({})
    assert r is not None
    assert r["code"] == "no_manifest"


def test_workspace_ingest_not_attempted_reason_no_sandbox() -> None:
    r = workspace_ingest_not_attempted_reason(
        {"workspace_manifest_v1": {"version": 1, "files": [{"path": "component/x.html"}]}},
    )
    assert r is not None
    assert r["code"] == "no_sandbox_ref"


def test_workspace_ingest_not_attempted_reason_ok() -> None:
    assert (
        workspace_ingest_not_attempted_reason(
            {
                "workspace_manifest_v1": {"version": 1, "files": [{"path": "component/x.html"}]},
                "sandbox_ref": "C:/tmp/sandbox",
            },
        )
        is None
    )
    assert workspace_ingest_should_attempt(
        {
            "workspace_manifest_v1": {"version": 1, "files": [{"path": "component/x.html"}]},
            "sandbox_ref": "C:/tmp/sandbox",
        },
    )


def test_resolve_evaluator_preview_resolution_candidate_absolute() -> None:
    s = Settings(orchestrator_public_base_url="http://127.0.0.1:8010")
    r = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="g1",
        thread_id="t1",
        build_candidate={},
    )
    assert r["preview_url"] == "http://127.0.0.1:8010/orchestrator/runs/g1/candidate-preview"
    assert r["preview_url_source"] == "orchestrator_candidate_preview"
    assert r["preview_url_is_absolute"] is True
    assert r["orchestrator_public_base_url_configured"] is True


def test_resolve_evaluator_preview_resolution_https_fallback() -> None:
    s = Settings()
    r = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="g1",
        thread_id="t1",
        build_candidate={"preview_url": "https://x.example/h"},
    )
    assert r["preview_url"] == "https://x.example/h"
    assert r["preview_url_source"] == "build_candidate_preview_url"
    assert r["preview_url_is_absolute"] is True
    assert r["orchestrator_public_base_url_configured"] is False


def test_resolve_evaluator_preview_url_wraps_resolution() -> None:
    s = Settings()
    u = resolve_evaluator_preview_url(
        s,
        graph_run_id="g1",
        thread_id="t1",
        build_candidate={"preview_url": "https://z.example/"},
    )
    assert u == "https://z.example/"


def test_validate_evaluator_role_input_accepts_preview_resolution() -> None:
    from kmbl_orchestrator.contracts.role_inputs import validate_role_input

    out = validate_role_input(
        "evaluator",
        {
            "thread_id": "t1",
            "preview_resolution": {
                "preview_url": "http://127.0.0.1:8010/orchestrator/runs/g/candidate-preview",
                "preview_url_is_absolute": True,
            },
        },
    )
    assert out["preview_resolution"]["preview_url_is_absolute"] is True
