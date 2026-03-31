"""Static HTML/CSS/JS artifact normalization and staging-derived metadata."""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
    normalize_combined_artifact_outputs_list,
    normalize_static_frontend_artifact_outputs_list,
)
from kmbl_orchestrator.contracts.static_frontend_patch_v1 import (
    normalize_static_frontend_preview_in_patch,
)
from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord, ThreadRecord
from kmbl_orchestrator.normalize.generator import normalize_generator_output
from kmbl_orchestrator.runtime.scenario_visibility import static_frontend_visibility_from_staging_payload
from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload, derive_frontend_static_v1


def _minimal_html() -> str:
    return "<!DOCTYPE html><html><head><title>t</title></head><body>ok</body></html>"


def test_static_frontend_artifact_normalizes_and_dedupes_roles() -> None:
    raw = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": _minimal_html(),
            "bundle_id": "card_a",
            "entry_for_preview": True,
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/styles.css",
            "language": "css",
            "content": "body { margin: 0; }",
            "bundle_id": "card_a",
        },
    ]
    out = normalize_static_frontend_artifact_outputs_list(raw)
    assert len(out) == 2
    assert out[0]["path"] == "component/preview/index.html"
    assert out[0]["previewable"] is True
    assert out[1]["previewable"] is False


def test_static_frontend_skips_duplicate_paths() -> None:
    one = {
        "role": "static_frontend_file_v1",
        "path": "component/a.html",
        "language": "html",
        "content": _minimal_html(),
    }
    result = normalize_static_frontend_artifact_outputs_list([one, one])
    static = [r for r in result if isinstance(r, dict) and r.get("role") == "static_frontend_file_v1"]
    assert len(static) == 1


def test_static_frontend_warns_on_two_entry_for_preview_same_bundle() -> None:
    a = {
        "role": "static_frontend_file_v1",
        "path": "component/a.html",
        "language": "html",
        "content": _minimal_html(),
        "bundle_id": "b1",
        "entry_for_preview": True,
    }
    b = {
        "role": "static_frontend_file_v1",
        "path": "component/b.html",
        "language": "html",
        "content": _minimal_html(),
        "bundle_id": "b1",
        "entry_for_preview": True,
    }
    result = normalize_static_frontend_artifact_outputs_list([a, b])
    static = [r for r in result if isinstance(r, dict) and r.get("role") == "static_frontend_file_v1"]
    assert len(static) == 2


def test_combined_with_gallery_unchanged_order() -> None:
    gal = {
        "role": "gallery_strip_image_v1",
        "key": "img1",
        "url": "https://example.com/i.png",
    }
    fe = {
        "role": "static_frontend_file_v1",
        "path": "component/x.html",
        "language": "html",
        "content": _minimal_html(),
    }
    out = normalize_combined_artifact_outputs_list([gal, fe])
    assert out[0]["role"] == "gallery_strip_image_v1"
    assert out[1]["role"] == "static_frontend_file_v1"


def test_normalize_generator_output_chains_preview_patch() -> None:
    raw = {
        "artifact_outputs": [
            {
                "role": "static_frontend_file_v1",
                "path": "component/x.html",
                "language": "html",
                "content": _minimal_html(),
            }
        ],
        "updated_state": {
            "static_frontend_preview_v1": {"entry_path": "component/x.html"},
        },
    }
    tid = uuid4()
    gid = uuid4()
    ginv = uuid4()
    bsid = uuid4()
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=ginv,
        build_spec_id=bsid,
    )
    assert bc.working_state_patch_json.get("static_frontend_preview_v1", {}).get(
        "entry_path"
    ) == "component/x.html"
    assert len(bc.artifact_refs_json) == 1


def test_normalize_generator_warns_on_preview_path_not_in_artifacts() -> None:
    raw = {
        "artifact_outputs": [
            {
                "role": "static_frontend_file_v1",
                "path": "component/x.html",
                "language": "html",
                "content": _minimal_html(),
            }
        ],
        "updated_state": {
            "static_frontend_preview_v1": {"entry_path": "component/missing.html"},
        },
    }
    tid = uuid4()
    gid = uuid4()
    ginv = uuid4()
    bsid = uuid4()
    bc = normalize_generator_output(
        raw,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=ginv,
        build_spec_id=bsid,
    )
    assert len(bc.artifact_refs_json) == 1


def test_derive_frontend_static_v1_preview_entry() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": _minimal_html(),
            "bundle_id": "u1",
        },
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/extra.html",
            "language": "html",
            "content": "<html><body>alt</body></html>",
            "bundle_id": "u1",
            "entry_for_preview": True,
        },
    ]
    fs = derive_frontend_static_v1(arts, {"static_frontend_preview_v1": {"entry_path": "component/preview/index.html"}})
    assert fs is not None
    assert fs.file_count == 2
    assert fs.bundle_count == 1
    assert fs.bundles[0].preview_entry_path == "component/preview/extra.html"
    assert fs.patch_preview_entry_path == "component/preview/index.html"


def test_build_staging_snapshot_payload_includes_frontend_static() -> None:
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()
    bsid = uuid4()
    evid = uuid4()
    html = _minimal_html()
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/preview/index.html",
            "language": "html",
            "content": html,
            "bundle_id": "main",
            "entry_for_preview": True,
        }
    ]
    bc = BuildCandidateRecord(
        build_candidate_id=bcid,
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=bsid,
        candidate_kind="content",
        working_state_patch_json={},
        artifact_refs_json=arts,
    )
    ev = EvaluationReportRecord(
        evaluation_report_id=evid,
        thread_id=tid,
        graph_run_id=gid,
        evaluator_invocation_id=uuid4(),
        build_candidate_id=bcid,
        status="pass",
        summary="ok",
        issues_json=[],
        metrics_json={},
    )
    th = ThreadRecord(thread_id=tid, identity_id=None, thread_kind="build", status="active")
    payload = build_staging_snapshot_payload(
        build_candidate=bc, evaluation_report=ev, thread=th, build_spec=None
    )
    fs = payload["metadata"]["frontend_static"]
    assert fs is not None
    assert fs["convention"] == "component_paths_v1"
    assert fs["file_count"] == 1
    assert fs["has_previewable_html"] is True
    assert fs["bundles"][0]["preview_entry_path"] == "component/preview/index.html"


def test_static_frontend_visibility_fallback_without_metadata_block() -> None:
    p = {
        "artifacts": {
            "artifact_refs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/a.html",
                    "language": "html",
                    "content": "x",
                }
            ]
        },
        "metadata": {"working_state_patch": {}},
    }
    fv = static_frontend_visibility_from_staging_payload(p)
    assert fv["has_static_frontend"] is True
    assert fv["static_frontend_file_count"] == 1


def test_normalize_static_frontend_preview_standalone() -> None:
    arts = [
        {
            "role": "static_frontend_file_v1",
            "path": "component/a.html",
            "language": "html",
            "content": _minimal_html(),
            "bundle_id": "b",
        }
    ]
    patch = normalize_static_frontend_preview_in_patch(
        {"static_frontend_preview_v1": {"entry_path": "component/a.html", "bundle_id": "b"}},
        arts,
    )
    assert patch["static_frontend_preview_v1"]["entry_path"] == "component/a.html"
