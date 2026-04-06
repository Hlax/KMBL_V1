"""Tests for the mutable working-staging model.

Covers: patch/rebuild application, auto-checkpoint logic,
rollback/recovery, approval → publication, and persistence layer.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    EvaluationReportRecord,
    PublicationSnapshotRecord,
    StagingCheckpointRecord,
    ThreadRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.working_staging_ops import (
    apply_generator_to_working_staging,
    approve_working_staging,
    choose_update_mode,
    create_staging_checkpoint,
    fresh_rebuild,
    merge_artifacts_into_payload,
    rollback_to_checkpoint,
    rollback_to_publication,
    should_auto_checkpoint,
    _payload_has_previewable_html,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_working_staging(
    *,
    thread_id: UUID | None = None,
    identity_id: UUID | None = None,
    revision: int = 0,
    status: str = "draft",
    payload: dict[str, Any] | None = None,
) -> WorkingStagingRecord:
    return WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=thread_id or uuid4(),
        identity_id=identity_id,
        payload_json=payload or {},
        revision=revision,
        status=status,  # type: ignore[arg-type]
    )


def _make_build_candidate(
    *,
    thread_id: UUID | None = None,
    graph_run_id: UUID | None = None,
    artifact_refs: list[Any] | None = None,
    working_state_patch: dict[str, Any] | None = None,
) -> BuildCandidateRecord:
    tid = thread_id or uuid4()
    gid = graph_run_id or uuid4()
    return BuildCandidateRecord(
        build_candidate_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        generator_invocation_id=uuid4(),
        build_spec_id=uuid4(),
        candidate_kind="habitat",
        artifact_refs_json=artifact_refs or [],
        working_state_patch_json=working_state_patch or {},
    )


def _make_eval_report(
    *,
    status: str = "pass",
    thread_id: UUID | None = None,
    graph_run_id: UUID | None = None,
    build_candidate_id: UUID | None = None,
) -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        thread_id=thread_id or uuid4(),
        graph_run_id=graph_run_id or uuid4(),
        evaluator_invocation_id=uuid4(),
        build_candidate_id=build_candidate_id or uuid4(),
        status=status,  # type: ignore[arg-type]
        summary="test evaluation",
    )


def _html_artifact(path: str = "index.html") -> dict[str, Any]:
    return {
        "role": "static_frontend_file_v1",
        "path": path,
        "language": "html",
        "content": "<html><body>Hello</body></html>",
        "previewable": True,
        "entry_for_preview": True,
    }


def _css_artifact(path: str = "style.css") -> dict[str, Any]:
    return {
        "role": "static_frontend_file_v1",
        "path": path,
        "language": "css",
        "content": "body { color: #333; }",
        "previewable": False,
        "entry_for_preview": False,
    }


# ---------------------------------------------------------------------------
# choose_update_mode
# ---------------------------------------------------------------------------


class TestChooseUpdateMode:
    def test_no_working_staging_returns_rebuild(self):
        assert choose_update_mode(None, "pass") == "rebuild"

    def test_revision_zero_returns_rebuild(self):
        ws = _make_working_staging(revision=0)
        assert choose_update_mode(ws, "pass") == "rebuild"

    def test_fail_status_returns_rebuild(self):
        ws = _make_working_staging(revision=3)
        assert choose_update_mode(ws, "fail") == "rebuild"

    def test_pass_status_returns_patch(self):
        ws = _make_working_staging(revision=1)
        assert choose_update_mode(ws, "pass") == "patch"

    def test_partial_status_returns_patch(self):
        ws = _make_working_staging(revision=2)
        assert choose_update_mode(ws, "partial") == "patch"


# ---------------------------------------------------------------------------
# merge_artifacts_into_payload
# ---------------------------------------------------------------------------


class TestMergeArtifacts:
    def test_patch_merges_artifacts_by_path(self):
        existing = {
            "version": 1,
            "artifacts": {
                "artifact_refs": [
                    _html_artifact("index.html"),
                    _css_artifact("style.css"),
                ]
            },
            "metadata": {"working_state_patch": {"old_key": "old_value"}},
        }
        new_payload = {
            "artifacts": {
                "artifact_refs": [
                    {**_html_artifact("index.html"), "content": "<html>Updated</html>"},
                ]
            },
            "metadata": {"working_state_patch": {"new_key": "new_value"}},
        }
        merged = merge_artifacts_into_payload(existing, new_payload)

        refs = merged["artifacts"]["artifact_refs"]
        assert len(refs) == 2
        html_ref = next(r for r in refs if r["path"] == "index.html")
        assert "Updated" in html_ref["content"]
        css_ref = next(r for r in refs if r["path"] == "style.css")
        assert css_ref["language"] == "css"

        wsp = merged["metadata"]["working_state_patch"]
        assert wsp["old_key"] == "old_value"
        assert wsp["new_key"] == "new_value"

    def test_new_paths_appended(self):
        existing = {
            "artifacts": {"artifact_refs": [_html_artifact("index.html")]},
        }
        new_payload = {
            "artifacts": {"artifact_refs": [_css_artifact("theme.css")]},
        }
        merged = merge_artifacts_into_payload(existing, new_payload)
        refs = merged["artifacts"]["artifact_refs"]
        assert len(refs) == 2

    def test_empty_new_refs_leaves_existing(self):
        existing = {
            "artifacts": {"artifact_refs": [_html_artifact()]},
        }
        merged = merge_artifacts_into_payload(existing, {"artifacts": {"artifact_refs": []}})
        assert len(merged["artifacts"]["artifact_refs"]) == 1

    def test_scalars_overwritten(self):
        existing = {"version": 1, "summary": {"title": "Old"}}
        new_payload = {"summary": {"title": "New"}}
        merged = merge_artifacts_into_payload(existing, new_payload)
        assert merged["summary"]["title"] == "New"
        assert merged["version"] == 1

    def test_frontend_static_replaced(self):
        existing = {"metadata": {"frontend_static": {"file_count": 1}}}
        new_payload = {"metadata": {"frontend_static": {"file_count": 5}}}
        merged = merge_artifacts_into_payload(existing, new_payload)
        assert merged["metadata"]["frontend_static"]["file_count"] == 5


# ---------------------------------------------------------------------------
# apply_generator_to_working_staging — rebuild
# ---------------------------------------------------------------------------


class TestRebuildMode:
    def test_first_run_creates_working_staging_with_rebuild(self):
        ws = _make_working_staging(revision=0)
        bc = _make_build_candidate(
            thread_id=ws.thread_id,
            artifact_refs=[_html_artifact()],
        )
        ev = _make_eval_report(status="pass")

        result = apply_generator_to_working_staging(
            working_staging=ws,
            build_candidate=bc,
            evaluation_report=ev,
            build_spec=None,
            mode="rebuild",
        )

        assert result.revision == 1
        assert result.last_update_mode == "rebuild"
        assert result.last_update_build_candidate_id == bc.build_candidate_id
        assert result.payload_json.get("version") == 1
        assert result.status == "review_ready"

    def test_partial_does_not_promote_draft_to_review_ready(self) -> None:
        ws = _make_working_staging(revision=0)
        bc = _make_build_candidate(
            thread_id=ws.thread_id,
            artifact_refs=[_html_artifact()],
        )
        ev = _make_eval_report(status="partial")

        result = apply_generator_to_working_staging(
            working_staging=ws,
            build_candidate=bc,
            evaluation_report=ev,
            build_spec=None,
            mode="rebuild",
        )

        assert result.status == "draft"

    def test_rebuild_replaces_payload_entirely(self):
        old_payload = {
            "version": 1,
            "artifacts": {"artifact_refs": [_css_artifact("old.css")]},
            "metadata": {"frontend_static": {"file_count": 1}},
        }
        ws = _make_working_staging(revision=2, payload=old_payload, status="review_ready")
        bc = _make_build_candidate(
            thread_id=ws.thread_id,
            artifact_refs=[_html_artifact("new.html")],
        )
        ev = _make_eval_report(status="fail")

        result = apply_generator_to_working_staging(
            working_staging=ws,
            build_candidate=bc,
            evaluation_report=ev,
            build_spec=None,
            mode="rebuild",
        )

        refs = result.payload_json.get("artifacts", {}).get("artifact_refs", [])
        paths = [r.get("path") for r in refs if isinstance(r, dict)]
        assert "new.html" in paths
        assert "old.css" not in paths
        assert result.revision == 3

    def test_fail_evaluation_triggers_rebuild_mode(self):
        ws = _make_working_staging(revision=2)
        assert choose_update_mode(ws, "fail") == "rebuild"


# ---------------------------------------------------------------------------
# apply_generator_to_working_staging — patch
# ---------------------------------------------------------------------------


class TestPatchMode:
    def test_second_run_patches_existing_working_staging(self):
        ws = _make_working_staging(revision=1)
        ws.payload_json = {
            "version": 1,
            "artifacts": {"artifact_refs": [_html_artifact("index.html")]},
            "metadata": {
                "working_state_patch": {},
                "frontend_static": {
                    "file_count": 1, "has_previewable_html": True,
                },
            },
        }
        ws.status = "review_ready"

        bc = _make_build_candidate(
            thread_id=ws.thread_id,
            artifact_refs=[_css_artifact("style.css")],
        )
        ev = _make_eval_report(status="pass")

        result = apply_generator_to_working_staging(
            working_staging=ws,
            build_candidate=bc,
            evaluation_report=ev,
            build_spec=None,
            mode="patch",
        )

        refs = result.payload_json.get("artifacts", {}).get("artifact_refs", [])
        assert len(refs) == 2
        assert result.revision == 2
        assert result.last_update_mode == "patch"

    def test_multiple_runs_accumulate_artifacts(self):
        ws = _make_working_staging(revision=0)
        files = ["index.html", "style.css", "app.js"]

        for i, fname in enumerate(files):
            lang = fname.rsplit(".", 1)[-1]
            if lang == "js":
                lang = "js"
            ref = {
                "role": "static_frontend_file_v1",
                "path": fname,
                "language": lang if lang != "js" else "js",
                "content": f"content-{i}",
                "previewable": lang == "html",
                "entry_for_preview": lang == "html",
            }
            bc = _make_build_candidate(
                thread_id=ws.thread_id,
                artifact_refs=[ref],
            )
            ev = _make_eval_report(status="pass")
            mode = "rebuild" if ws.revision == 0 else "patch"
            ws = apply_generator_to_working_staging(
                working_staging=ws,
                build_candidate=bc,
                evaluation_report=ev,
                build_spec=None,
                mode=mode,
            )

        refs = ws.payload_json.get("artifacts", {}).get("artifact_refs", [])
        assert len(refs) == 3
        assert ws.revision == 3


# ---------------------------------------------------------------------------
# Checkpoint logic
# ---------------------------------------------------------------------------


class TestCheckpoints:
    def test_auto_checkpoint_on_post_patch(self):
        before = _make_working_staging(revision=1)
        after = _make_working_staging(revision=2)
        trigger = should_auto_checkpoint(before, after, "patch")
        assert trigger == "post_patch"

    def test_auto_checkpoint_on_first_previewable_html(self):
        before = _make_working_staging(revision=1, payload={})
        after = _make_working_staging(
            revision=2,
            payload={
                "metadata": {"frontend_static": {"has_previewable_html": True}},
            },
        )
        trigger = should_auto_checkpoint(before, after, "rebuild")
        assert trigger == "first_previewable_html"

    def test_no_checkpoint_on_rebuild_without_html(self):
        before = _make_working_staging(revision=1, payload={})
        after = _make_working_staging(revision=2, payload={})
        trigger = should_auto_checkpoint(before, after, "rebuild")
        assert trigger is None

    def test_auto_checkpoint_before_rebuild(self):
        """The caller should create a pre_rebuild checkpoint before apply.
        This tests the checkpoint creation helper directly."""
        ws = _make_working_staging(revision=3, payload={"version": 1})
        cp = create_staging_checkpoint(ws, trigger="pre_rebuild")
        assert cp.working_staging_id == ws.working_staging_id
        assert cp.revision_at_checkpoint == 3
        assert cp.trigger == "pre_rebuild"
        assert cp.payload_snapshot_json == {"version": 1}

    def test_checkpoint_is_deep_copy(self):
        payload = {"artifacts": {"artifact_refs": [_html_artifact()]}}
        ws = _make_working_staging(revision=1, payload=payload)
        cp = create_staging_checkpoint(ws, trigger="post_patch")
        ws.payload_json["artifacts"]["artifact_refs"].clear()
        assert len(cp.payload_snapshot_json["artifacts"]["artifact_refs"]) == 1


# ---------------------------------------------------------------------------
# Rollback / recovery
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_to_checkpoint_restores_payload(self):
        ws = _make_working_staging(revision=3)
        saved_payload = {"version": 1, "artifacts": {"artifact_refs": [_html_artifact()]}}
        cp = StagingCheckpointRecord(
            staging_checkpoint_id=uuid4(),
            working_staging_id=ws.working_staging_id,
            thread_id=ws.thread_id,
            payload_snapshot_json=copy.deepcopy(saved_payload),
            revision_at_checkpoint=2,
            trigger="post_patch",
        )

        ws = rollback_to_checkpoint(ws, cp)
        assert ws.payload_json == saved_payload
        assert ws.revision == 4
        assert ws.current_checkpoint_id == cp.staging_checkpoint_id

    def test_rollback_to_publication_restores_payload(self):
        ws = _make_working_staging(revision=5)
        pub_payload = {"version": 1, "summary": {"title": "Published build"}}
        pub = PublicationSnapshotRecord(
            publication_snapshot_id=uuid4(),
            source_staging_snapshot_id=uuid4(),
            thread_id=ws.thread_id,
            payload_json=copy.deepcopy(pub_payload),
        )

        ws = rollback_to_publication(ws, pub)
        assert ws.payload_json == pub_payload
        assert ws.revision == 6
        assert ws.status == "review_ready"

    def test_fresh_rollback_clears_payload(self):
        ws = _make_working_staging(
            revision=4,
            status="review_ready",
            payload={"version": 1, "artifacts": {"artifact_refs": [_html_artifact()]}},
        )

        ws = fresh_rebuild(ws)
        assert ws.payload_json == {}
        assert ws.revision == 5
        assert ws.status == "draft"
        assert ws.current_checkpoint_id is None


# ---------------------------------------------------------------------------
# Approval → publication
# ---------------------------------------------------------------------------


class TestApproval:
    def test_approve_creates_publication_from_working_staging(self):
        ws = _make_working_staging(
            revision=3,
            status="review_ready",
            payload={"version": 1, "artifacts": {"artifact_refs": [_html_artifact()]}},
        )
        src = uuid4()
        ws_updated, pub, cp = approve_working_staging(
            ws, approved_by="tester", source_staging_snapshot_id=src
        )

        assert ws_updated.status == "frozen"
        assert pub.source_staging_snapshot_id == src
        assert pub.source_working_staging_id == ws.working_staging_id
        assert pub.source_staging_checkpoint_id == cp.staging_checkpoint_id
        assert pub.payload_json["version"] == 1
        assert pub.published_by == "tester"

    def test_approve_creates_pre_approval_checkpoint(self):
        ws = _make_working_staging(revision=2, status="review_ready", payload={"version": 1})
        _, _, cp = approve_working_staging(ws, source_staging_snapshot_id=uuid4())
        assert cp.trigger == "pre_approval"
        assert cp.revision_at_checkpoint == 2


# ---------------------------------------------------------------------------
# Persistence layer
# ---------------------------------------------------------------------------


class TestWorkingStagingPersistence:
    def test_save_and_retrieve(self):
        repo = InMemoryRepository()
        ws = _make_working_staging()

        repo.save_working_staging(ws)
        retrieved = repo.get_working_staging_for_thread(ws.thread_id)
        assert retrieved is not None
        assert retrieved.working_staging_id == ws.working_staging_id

    def test_get_returns_none_when_missing(self):
        repo = InMemoryRepository()
        assert repo.get_working_staging_for_thread(uuid4()) is None

    def test_save_overwrites_existing(self):
        repo = InMemoryRepository()
        ws = _make_working_staging()
        repo.save_working_staging(ws)

        ws.revision = 5
        repo.save_working_staging(ws)
        retrieved = repo.get_working_staging_for_thread(ws.thread_id)
        assert retrieved is not None
        assert retrieved.revision == 5

    def test_checkpoint_persistence(self):
        repo = InMemoryRepository()
        ws = _make_working_staging()
        cp1 = create_staging_checkpoint(ws, trigger="post_patch")
        cp2 = create_staging_checkpoint(ws, trigger="pre_rebuild")

        repo.save_staging_checkpoint(cp1)
        repo.save_staging_checkpoint(cp2)

        retrieved = repo.get_staging_checkpoint(cp1.staging_checkpoint_id)
        assert retrieved is not None
        assert retrieved.trigger == "post_patch"

        listed = repo.list_staging_checkpoints(ws.working_staging_id)
        assert len(listed) == 2

    def test_working_staging_preview_serves_html(self):
        """Working staging with previewable HTML can be detected."""
        ws = _make_working_staging(
            revision=1,
            payload={
                "artifacts": {"artifact_refs": [_html_artifact()]},
                "metadata": {"frontend_static": {"has_previewable_html": True}},
            },
        )
        assert _payload_has_previewable_html(ws.payload_json)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_existing_staging_snapshot_tests_still_pass(self):
        """The old StagingSnapshotRecord model is still importable and usable."""
        from kmbl_orchestrator.domain import StagingSnapshotRecord

        rec = StagingSnapshotRecord(
            staging_snapshot_id=uuid4(),
            thread_id=uuid4(),
            build_candidate_id=uuid4(),
            status="review_ready",
        )
        assert rec.status == "review_ready"

    def test_publication_has_new_lineage_fields(self):
        """PublicationSnapshotRecord now supports working staging lineage."""
        pub = PublicationSnapshotRecord(
            publication_snapshot_id=uuid4(),
            source_staging_snapshot_id=uuid4(),
            source_working_staging_id=uuid4(),
            source_staging_checkpoint_id=uuid4(),
        )
        assert pub.source_working_staging_id is not None
        assert pub.source_staging_checkpoint_id is not None

    def test_publication_old_fields_still_work(self):
        """Existing publications without new fields still work."""
        pub = PublicationSnapshotRecord(
            publication_snapshot_id=uuid4(),
            source_staging_snapshot_id=uuid4(),
        )
        assert pub.source_working_staging_id is None
        assert pub.source_staging_checkpoint_id is None
