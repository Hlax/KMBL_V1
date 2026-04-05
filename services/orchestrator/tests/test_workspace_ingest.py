"""workspace_manifest_v1 ingest into artifact_outputs."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.workspace_ingest import (
    WorkspaceIngestError,
    compute_workspace_ingest_preflight,
    ingest_workspace_manifest_if_present,
)
from kmbl_orchestrator.runtime.workspace_paths import (
    assert_sandbox_under_workspace_root,
    build_workspace_context_for_generator,
    default_generator_workspace_root,
    normalize_manifest_relative_path,
    paths_resolved_equal,
    resolve_generator_workspace_root,
    run_workspace_directory,
)


def test_resolve_generator_workspace_root_uses_explicit_env(tmp_path: Path) -> None:
    s = Settings.model_construct(kmbl_generator_workspace_root=str(tmp_path / "w"))
    assert resolve_generator_workspace_root(s) == (tmp_path / "w").resolve()


def test_run_workspace_directory_layout() -> None:
    s = Settings.model_construct(kmbl_generator_workspace_root="")
    tid = uuid4()
    gid = uuid4()
    p = run_workspace_directory(s, tid, gid)
    assert str(tid) in str(p)
    assert str(gid) in str(p)


def test_build_workspace_context_keys() -> None:
    s = Settings.model_construct(kmbl_generator_workspace_root="")
    tid = uuid4()
    gid = uuid4()
    ctx = build_workspace_context_for_generator(s, tid, gid)
    assert "workspace_root_resolved" in ctx
    assert "recommended_write_path" in ctx
    assert ctx.get("canonical_preview_entry_relative") == "component/preview/index.html"


def test_normalize_manifest_relative_path_mixed_separators() -> None:
    assert normalize_manifest_relative_path("component\\preview\\index.html") == "component/preview/index.html"
    assert normalize_manifest_relative_path("component//preview//x.html") == "component/preview/x.html"


def test_compute_workspace_ingest_preflight_aligns_with_recommended(tmp_path: Path) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    tid = uuid4()
    gid = uuid4()
    sandbox = root / str(tid) / str(gid)
    sandbox.mkdir(parents=True)
    s = Settings.model_construct(kmbl_generator_workspace_root=str(root))
    wm = {"version": 1, "files": [{"path": "component/preview/index.html"}]}
    pre = compute_workspace_ingest_preflight(s, tid, gid, str(sandbox), wm)
    assert pre["sandbox_matches_recommended_write_path"] is True
    assert pre["manifest_paths_normalized"] == ["component/preview/index.html"]


def test_compute_workspace_ingest_preflight_detects_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    tid = uuid4()
    gid = uuid4()
    wrong = root / str(tid) / "other"
    wrong.mkdir(parents=True)
    s = Settings.model_construct(kmbl_generator_workspace_root=str(root))
    wm = {"version": 1, "files": [{"path": "component/x.html"}]}
    pre = compute_workspace_ingest_preflight(s, tid, gid, str(wrong), wm)
    assert pre["sandbox_matches_recommended_write_path"] is False


def test_ingest_missing_file_includes_classified_details(tmp_path: Path) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    tid = uuid4()
    gid = uuid4()
    sandbox = root / str(tid) / str(gid)
    (sandbox / "component" / "preview").mkdir(parents=True)
    s = Settings.model_construct(kmbl_generator_workspace_root=str(root))
    raw = {
        "workspace_manifest_v1": {
            "version": 1,
            "files": [{"path": "component/preview/index.html"}],
        },
        "sandbox_ref": str(sandbox),
    }
    with pytest.raises(WorkspaceIngestError) as exc:
        ingest_workspace_manifest_if_present(
            raw,
            settings=s,
            thread_id=tid,
            graph_run_id=gid,
        )
    assert exc.value.details.get("ingest_failure_class") == "artifact_not_found"
    assert "expected_absolute_path" in exc.value.details


def test_paths_resolved_equal_reflexive(tmp_path: Path) -> None:
    a = (tmp_path / "x").resolve()
    a.mkdir()
    assert paths_resolved_equal(a, a)


def test_ingest_reads_files_under_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    tid = uuid4()
    gid = uuid4()
    sandbox = root / str(tid) / str(gid)
    comp = sandbox / "component" / "preview"
    comp.mkdir(parents=True)
    html = comp / "index.html"
    html.write_text("<!DOCTYPE html><html><body>x</body></html>", encoding="utf-8")

    s = Settings.model_construct(
        kmbl_generator_workspace_root=str(root),
        kmbl_workspace_ingest_max_bytes_total=2_000_000,
    )
    assert_sandbox_under_workspace_root(s, sandbox)

    raw = {
        "workspace_manifest_v1": {
            "version": 1,
            "files": [{"path": "component/preview/index.html"}],
            "entry_html": "component/preview/index.html",
        },
        "sandbox_ref": str(sandbox),
        "artifact_outputs": [],
    }
    out, stats, inline_skip = ingest_workspace_manifest_if_present(
        raw,
        settings=s,
        thread_id=tid,
        graph_run_id=gid,
    )
    assert inline_skip is None
    assert stats is not None
    assert stats["file_count"] == 1
    ao = out.get("artifact_outputs")
    assert isinstance(ao, list)
    assert any(
        isinstance(a, dict)
        and a.get("role") == "static_frontend_file_v1"
        and a.get("entry_for_preview") is True
        for a in ao
    )


def test_ingest_maps_interactive_role(tmp_path: Path) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    tid = uuid4()
    gid = uuid4()
    sandbox = root / str(tid) / str(gid)
    comp = sandbox / "component" / "preview"
    comp.mkdir(parents=True)
    (comp / "index.html").write_text("<!DOCTYPE html><html><body>x</body></html>", encoding="utf-8")

    s = Settings.model_construct(
        kmbl_generator_workspace_root=str(root),
        kmbl_workspace_ingest_max_bytes_total=2_000_000,
    )
    raw = {
        "workspace_manifest_v1": {
            "version": 1,
            "files": [{"path": "component/preview/index.html"}],
            "entry_html": "component/preview/index.html",
        },
        "sandbox_ref": str(sandbox),
        "artifact_outputs": [],
    }
    out, stats, _ = ingest_workspace_manifest_if_present(
        raw,
        settings=s,
        thread_id=tid,
        graph_run_id=gid,
        ingested_artifact_role="interactive_frontend_app_v1",
    )
    assert stats is not None
    ao = out.get("artifact_outputs")
    assert isinstance(ao, list)
    assert any(
        isinstance(a, dict)
        and a.get("role") == "interactive_frontend_app_v1"
        for a in ao
    )


def test_ingest_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "wsroot"
    root.mkdir()
    sandbox = root / "s"
    sandbox.mkdir()
    s = Settings.model_construct(kmbl_generator_workspace_root=str(root))
    raw = {
        "workspace_manifest_v1": {
            "version": 1,
            "files": [{"path": "component/../../../secret.txt"}],
        },
        "sandbox_ref": str(sandbox),
    }
    with pytest.raises(WorkspaceIngestError):
        ingest_workspace_manifest_if_present(
            raw,
            settings=s,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
        )


def test_default_generator_workspace_root_is_absolute() -> None:
    p = default_generator_workspace_root()
    assert p.is_absolute()
