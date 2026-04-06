"""Session staging link builder and event_input merge."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.session_staging_links import (
    build_session_staging_links_dict,
    effective_orchestrator_public_base,
    merge_session_staging_into_event_input,
)


def test_build_paths_and_optional_urls() -> None:
    s = Settings(orchestrator_public_base_url="http://127.0.0.1:8010")
    d = build_session_staging_links_dict(
        s,
        graph_run_id="g1",
        thread_id="t1",
    )
    assert d["graph_run_id"] == "g1"
    assert d["thread_id"] == "t1"
    assert d["orchestrator_staging_preview_path"] == "/orchestrator/runs/g1/staging-preview"
    assert d["orchestrator_candidate_preview_path"] == "/orchestrator/runs/g1/candidate-preview"
    assert d["orchestrator_working_staging_json_path"] == "/orchestrator/working-staging/t1"
    assert d["control_plane_staging_preview_path"] == "/api/runs/g1/staging-preview"
    assert d["control_plane_live_habitat_path"] == "/habitat/live/t1"
    assert d["orchestrator_candidate_preview_url"] == "http://127.0.0.1:8010/orchestrator/runs/g1/candidate-preview"
    assert d["orchestrator_staging_preview_url"] == "http://127.0.0.1:8010/orchestrator/runs/g1/staging-preview"
    assert d["orchestrator_public_base_source"] == "configured"


def test_merge_into_event_input() -> None:
    s = Settings()
    ei = merge_session_staging_into_event_input(
        s,
        {"scenario": "x"},
        graph_run_id="g",
        thread_id="t",
    )
    assert ei["scenario"] == "x"
    assert "kmbl_session_staging" in ei
    assert ei["kmbl_session_staging"]["thread_id"] == "t"


def test_merge_skips_without_ids() -> None:
    s = Settings()
    ei = merge_session_staging_into_event_input(s, {"a": 1}, graph_run_id=None, thread_id="t")
    assert "kmbl_session_staging" not in ei


def test_derived_local_base_when_unconfigured_dev() -> None:
    s = Settings(
        orchestrator_public_base_url="",
        orchestrator_port=8010,
        kmbl_env="development",
        kmbl_preview_derive_local_public_base=True,
    )
    base, src = effective_orchestrator_public_base(s)
    assert base == "http://127.0.0.1:8010"
    assert src == "derived_local"
    d = build_session_staging_links_dict(s, graph_run_id="g1", thread_id="t1")
    assert d["orchestrator_public_base_source"] == "derived_local"
    assert d["orchestrator_candidate_preview_url"].startswith("http://127.0.0.1:8010/")


def test_no_derived_base_in_production_without_url() -> None:
    s = Settings(
        orchestrator_public_base_url="",
        kmbl_env="production",
        kmbl_preview_derive_local_public_base=True,
    )
    base, src = effective_orchestrator_public_base(s)
    assert base is None
    assert src == "none"
