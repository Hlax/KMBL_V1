"""Preview host classification and manifest-first grounding without live browser URL."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.preview_reachability import (
    classify_preview_url_host,
    manifest_first_evaluator_grounding_satisfied,
    preview_host_blocked_by_openclaw_default,
    summary_v2_supports_offline_evaluator_grounding,
)
from kmbl_orchestrator.runtime.session_staging_links import resolve_evaluator_preview_resolution


def test_classify_localhost_vs_private_vs_public() -> None:
    assert classify_preview_url_host("http://127.0.0.1:8010/x") == "localhost"
    assert classify_preview_url_host("http://localhost/p") == "localhost"
    assert classify_preview_url_host("http://10.0.0.1/p") == "private_ip"
    assert classify_preview_url_host("http://192.168.0.1/p") == "private_ip"
    assert classify_preview_url_host("https://trycloudflare.com/x") == "public_host"


def test_preview_host_blocked_defaults() -> None:
    assert preview_host_blocked_by_openclaw_default("http://127.0.0.1:1/") is True
    assert preview_host_blocked_by_openclaw_default("https://public.example/") is False


def test_resolve_localhost_operator_browser_none_allow_private_restores() -> None:
    s = Settings(
        orchestrator_public_base_url="http://127.0.0.1:8010",
        kmbl_evaluator_allow_private_preview_fetch=False,
    )
    r = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="g",
        thread_id="t",
        build_candidate={},
    )
    assert r["operator_preview_url"] == "http://127.0.0.1:8010/orchestrator/runs/g/candidate-preview"
    assert r["preview_url"] is None
    assert r["preview_grounding_mode"] == "operator_local_only"
    assert r["preview_url_browser_reachable_expected"] is False

    s2 = Settings(
        orchestrator_public_base_url="http://127.0.0.1:8010",
        kmbl_evaluator_allow_private_preview_fetch=True,
    )
    r2 = resolve_evaluator_preview_resolution(
        s2,
        graph_run_id="g",
        thread_id="t",
        build_candidate={},
    )
    assert r2["preview_url"] == "http://127.0.0.1:8010/orchestrator/runs/g/candidate-preview"
    assert r2["preview_grounding_mode"] == "browser_reachable"
    assert r2["preview_url_browser_reachable_expected"] is True


def test_manifest_first_grounding_offline_summary() -> None:
    pr = {"preview_url": None, "preview_url_is_absolute": False}
    bc = {
        "kmbl_build_candidate_summary_v2": {
            "entrypoints": ["index.html"],
            "preview_readiness": {"has_resolved_entrypoints": True},
        },
    }
    assert summary_v2_supports_offline_evaluator_grounding(bc) is True
    assert manifest_first_evaluator_grounding_satisfied(pr, bc) is True


def test_manifest_first_grounding_requires_summary_when_no_browser_url() -> None:
    pr = {"preview_url": None, "preview_url_is_absolute": False}
    assert manifest_first_evaluator_grounding_satisfied(pr, {}) is False
