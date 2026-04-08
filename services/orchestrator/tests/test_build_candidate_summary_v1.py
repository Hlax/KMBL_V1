"""build_candidate_summary_v1, slim payloads, snippets, and gate merge behavior."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.contracts.role_inputs import validate_role_input
from kmbl_orchestrator.domain import BuildCandidateRecord
from kmbl_orchestrator.runtime.graph_run_detail_read_model import _build_candidate_summary_brief
from kmbl_orchestrator.runtime.artifact_snippet_extract import (
    extract_evaluator_snippets,
    extract_failure_focus_snippets,
)
from kmbl_orchestrator.runtime.build_candidate_summary_v1 import (
    SUMMARY_VERSION,
    build_build_candidate_summary_v1,
    merge_slim_with_full_artifacts_for_gates,
    merge_summary_into_raw_payload,
    strip_artifact_contents,
    summary_json_size,
)
from kmbl_orchestrator.runtime.evaluator_preflight import should_skip_evaluator_llm


def _artifacts_three_gsap() -> list[dict]:
    return [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<!DOCTYPE html><html><head><title>T</title></head><body><canvas id=c></canvas>"
            "<script src=\"https://unpkg.com/three\"></script></body></html>",
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/main.js",
            "language": "js",
            "content": "import * as THREE from 'three'; import gsap from 'gsap'; console.log(gsap);",
        },
    ]


def test_summary_default_three_gsap_detects_libs() -> None:
    arts = _artifacts_three_gsap()
    bs = {"type": "interactive_frontend_app_v1", "experience_mode": "flat_standard"}
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
    assert s["summary_version"] == SUMMARY_VERSION
    assert s["lane"] == "interactive_frontend_app_v1"
    assert "three" in s["libraries_detected"]
    assert "gsap" in s["libraries_detected"]
    assert s["experience_summary"]["artifact_count"] == 2
    n = summary_json_size(s)
    assert 0 < n < 20_000


def test_summary_wgsl_and_shader_paths() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/shader.wgsl",
            "language": "wgsl",
            "content": "@vertex fn main() {}",
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<html><script>navigator.gpu</script></html>",
        },
    ]
    bs = {"type": "interactive_frontend_app_v1"}
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
    assert s["rendering_summary"]["has_wgsl_files"] is True
    assert "wgsl" in s["libraries_detected"]


def test_summary_gaussian_splat_warning() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<html></html>",
        },
    ]
    bs = {
        "type": "interactive_frontend_app_v1",
        "execution_contract": {
            "escalation_lane": "gaussian_splat_v1",
            "allowed_libraries": ["three", "gaussian-splats-3d"],
        },
    }
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
    assert any("gaussian_splat_lane" in w for w in s["warnings"])


def test_summary_pixi_lane() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<html><script>const app = new PIXI.Application();</script></html>",
        },
    ]
    bs = {"type": "interactive_frontend_app_v1"}
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
    assert "pixi" in s["libraries_detected"]


def test_summary_extracts_nested_h1_text() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": "<html><body><h1><span>Meow Wolf</span> Immersive Story</h1></body></html>",
        },
    ]
    bs = {"type": "interactive_frontend_app_v1"}
    ei = {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}
    s = build_build_candidate_summary_v1(arts, build_spec=bs, event_input=ei)
    assert s["sections_or_modules"]["h1_text"] == "Meow Wolf Immersive Story"


def test_strip_artifacts_omits_content() -> None:
    slim = strip_artifact_contents(_artifacts_three_gsap())
    assert all("content" not in x for x in slim)
    assert all(x.get("content_omitted") for x in slim)
    assert slim[0].get("content_len", 0) > 0


def test_merge_slim_with_full_for_gates() -> None:
    full = _artifacts_three_gsap()
    slim = {
        "preview_url": "https://x/preview",
        "artifact_outputs": strip_artifact_contents(full),
        "kmbl_build_candidate_summary_v1": {"summary_version": 1},
    }
    merged = merge_slim_with_full_artifacts_for_gates(slim, full)
    assert merged["artifact_outputs"][0].get("content")
    assert merged["preview_url"] == "https://x/preview"


def test_snippets_bounded() -> None:
    arts = _artifacts_three_gsap()
    sn = extract_evaluator_snippets(arts, max_total=5000)
    total = len(str(sn))
    assert total <= 6000
    assert sn.get("entry_html") is not None


def test_failure_focus_snippets() -> None:
    arts = [{"role": "x", "path": "a.js", "content": "foo NEEDLE bar baz"}]
    out = extract_failure_focus_snippets(arts, substring_needles=["NEEDLE"])
    assert len(out) == 1
    assert "NEEDLE" in out[0]["text"]


def test_skip_evaluator_respects_summary_entrypoints() -> None:
    slim = {
        "kmbl_build_candidate_summary_v2": {
            "entrypoints": ["component/preview/index.html"],
        },
        "artifact_outputs": [],
    }
    skip, _ = should_skip_evaluator_llm(
        slim,
        {"type": "static_frontend_file_v1"},
        {"scenario": "kmbl_identity_url_static_v1"},
    )
    assert skip is False


def test_merge_summary_into_raw_payload() -> None:
    rp = merge_summary_into_raw_payload({"a": 1}, {"summary_version": 1})
    assert rp["kmbl_build_candidate_summary_v1"]["summary_version"] == 1


def test_merge_summary_into_raw_payload_includes_v2() -> None:
    rp = merge_summary_into_raw_payload(
        {},
        {"summary_version": 1},
        summary_v2={"summary_version": 2, "canonical_source": "orchestrator_artifact_inspection_v2"},
    )
    assert rp["kmbl_build_candidate_summary_v2"]["summary_version"] == 2


def test_validate_evaluator_accepts_summary_fields() -> None:
    out = validate_role_input(
        "evaluator",
        {
            "thread_id": "t",
            "build_candidate": {"artifact_outputs": []},
            "success_criteria": [],
            "evaluation_targets": [],
            "iteration_hint": 0,
            "kmbl_build_candidate_summary_v1": {"summary_version": 1},
        },
    )
    assert out["kmbl_build_candidate_summary_v1"]["summary_version"] == 1


def test_validate_generator_accepts_prior_summary() -> None:
    out = validate_role_input(
        "generator",
        {
            "thread_id": "t",
            "build_spec": {},
            "kmbl_prior_build_candidate_summary_v1": {"lane": "interactive_frontend_app_v1"},
        },
    )
    assert out["kmbl_prior_build_candidate_summary_v1"]["lane"] == "interactive_frontend_app_v1"


def test_build_candidate_summary_brief_from_record() -> None:
    bc = BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="content",
        raw_payload_json={
            "kmbl_build_candidate_summary_v1": {
                "summary_version": 1,
                "lane": "interactive_frontend_app_v1",
                "escalation_lane": None,
                "libraries_detected": ["three", "gsap"],
                "entrypoints": ["component/preview/index.html"],
                "experience_summary": {"artifact_count": 2},
                "file_inventory": [{"path": "a.html"}, {"path": "b.js"}],
            }
        },
    )
    b = _build_candidate_summary_brief(bc)
    assert b is not None
    assert b["lane"] == "interactive_frontend_app_v1"
    assert b["file_inventory_count"] == 2
    assert b["libraries_detected"] == ["three", "gsap"]
    assert b.get("warnings_count") == 0
