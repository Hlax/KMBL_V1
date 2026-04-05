"""Tests for html_block_v1 artifact contract, block merge engine, and integration.

Covers:
- HtmlBlockArtifactV1 model validation
- normalize_html_block_artifact and normalize_html_block_outputs_list
- block_merge: replace, append_to_body, prepend_to_body
- block_merge: element-not-found fallback (append)
- block_merge: new file seeded from minimal template
- block_merge: multiple blocks on one file
- normalize_combined passes html_block_v1 through unchanged
- validate_generator_output_for_candidate accepts html_block_v1-only output
- generator_node wires blocks into build_candidate (integration)
- Staging snapshot carries block_preview_anchors in metadata
- Preview anchor propagation end-to-end
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.contracts.html_block_artifact_v1 import (
    HtmlBlockArtifactV1,
    normalize_html_block_artifact,
    normalize_html_block_outputs_list,
)
from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
    normalize_combined_artifact_outputs_list,
)
from kmbl_orchestrator.staging.block_merge import (
    apply_blocks_to_static_files,
    apply_html_block,
    _apply_append_to_body,
    _apply_prepend_to_body,
    _replace_element_by_id,
)
from kmbl_orchestrator.staging.integrity import validate_generator_output_for_candidate


# ─────────────────────────────────────────────────────────────────────────────
# 1. HtmlBlockArtifactV1 contract
# ─────────────────────────────────────────────────────────────────────────────

class TestHtmlBlockArtifactV1Contract:
    def _minimal(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "role": "html_block_v1",
            "block_id": "hero",
            "target_path": "component/preview/index.html",
            "operation": "replace",
            "target_selector": "#hero",
            "content": "<section id='hero'><h1>Hello</h1></section>",
        }
        base.update(overrides)
        return base

    def test_valid_minimal(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(self._minimal())
        assert m.block_id == "hero"
        assert m.target_path == "component/preview/index.html"
        assert m.operation == "replace"
        assert m.target_selector == "#hero"

    def test_valid_append_to_body(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(
            self._minimal(operation="append_to_body", target_selector="__body__")
        )
        assert m.operation == "append_to_body"
        assert m.target_selector == "__body__"

    def test_effective_preview_anchor_from_target_selector(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(self._minimal())
        assert m.effective_preview_anchor == "hero"

    def test_effective_preview_anchor_explicit(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(
            self._minimal(preview_anchor="my-anchor")
        )
        assert m.effective_preview_anchor == "my-anchor"

    def test_effective_preview_anchor_body_uses_block_id(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(
            self._minimal(operation="append_to_body", target_selector="__body__")
        )
        assert m.effective_preview_anchor == "hero"

    def test_invalid_block_id_starts_with_number(self) -> None:
        with pytest.raises(Exception):
            HtmlBlockArtifactV1.model_validate(self._minimal(block_id="1hero"))

    def test_invalid_target_path_not_html(self) -> None:
        with pytest.raises(Exception):
            HtmlBlockArtifactV1.model_validate(
                self._minimal(target_path="component/preview/index.css")
            )

    def test_invalid_target_path_no_component_prefix(self) -> None:
        with pytest.raises(Exception):
            HtmlBlockArtifactV1.model_validate(
                self._minimal(target_path="public/index.html")
            )

    def test_invalid_target_selector_class(self) -> None:
        with pytest.raises(Exception):
            HtmlBlockArtifactV1.model_validate(
                self._minimal(target_selector=".hero")
            )

    def test_extra_fields_ignored(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(
            self._minimal(unknown_field="ignored")
        )
        assert not hasattr(m, "unknown_field")

    def test_bundle_id_stored(self) -> None:
        m = HtmlBlockArtifactV1.model_validate(
            self._minimal(bundle_id="preview")
        )
        assert m.bundle_id == "preview"


class TestNormalizeHtmlBlock:
    def _block(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "role": "html_block_v1",
            "block_id": "nav",
            "target_path": "component/preview/index.html",
            "operation": "replace",
            "target_selector": "#nav",
            "content": "<nav id='nav'><a href='/'>Home</a></nav>",
        }
        base.update(overrides)
        return base

    def test_normalize_valid(self) -> None:
        result = normalize_html_block_artifact(self._block())
        assert result is not None
        assert result["block_id"] == "nav"
        assert result["role"] == "html_block_v1"

    def test_normalize_invalid_returns_none(self) -> None:
        result = normalize_html_block_artifact({"role": "html_block_v1", "block_id": "1bad"})
        assert result is None

    def test_normalize_non_block_returns_none(self) -> None:
        result = normalize_html_block_artifact({"role": "static_frontend_file_v1"})
        assert result is None

    def test_list_normalizer_deduplicates_by_block_id(self) -> None:
        seq = [self._block(), self._block()]  # duplicate block_id=nav
        out = normalize_html_block_outputs_list(seq)
        blocks = [x for x in out if isinstance(x, dict) and x.get("role") == "html_block_v1"]
        assert len(blocks) == 1

    def test_list_normalizer_passes_through_non_block_items(self) -> None:
        static = {"role": "static_frontend_file_v1", "path": "component/p/index.html"}
        out = normalize_html_block_outputs_list([self._block(), static])
        assert len(out) == 2

    def test_combined_normalizer_passes_html_block_through(self) -> None:
        """normalize_combined_artifact_outputs_list must NOT strip html_block_v1 items."""
        block = self._block()
        result = normalize_combined_artifact_outputs_list([block])
        blocks = [r for r in result if isinstance(r, dict) and r.get("role") == "html_block_v1"]
        assert len(blocks) == 1, (
            "html_block_v1 artifact was stripped by normalize_combined — it must be preserved"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Block merge engine
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<nav id="nav"><a href="/">Old nav</a></nav>
<section id="hero">
  <h1>Old heading</h1>
  <p>Old body</p>
</section>
<footer id="footer">Old footer</footer>
</body>
</html>
"""


class TestReplaceElementById:
    def test_replace_section(self) -> None:
        new_section = '<section id="hero"><h1>New heading</h1></section>'
        result = _replace_element_by_id(_SAMPLE_HTML, "hero", new_section)
        assert result is not None
        assert "New heading" in result
        assert "Old heading" not in result

    def test_replace_nav(self) -> None:
        new_nav = '<nav id="nav"><a href="/">New nav</a></nav>'
        result = _replace_element_by_id(_SAMPLE_HTML, "nav", new_nav)
        assert result is not None
        assert "New nav" in result
        assert "Old nav" not in result

    def test_replace_preserves_rest_of_document(self) -> None:
        new_nav = '<nav id="nav"><a href="/">Home</a></nav>'
        result = _replace_element_by_id(_SAMPLE_HTML, "nav", new_nav)
        assert result is not None
        assert "Old footer" in result
        assert "hero" in result

    def test_missing_element_returns_none(self) -> None:
        result = _replace_element_by_id(_SAMPLE_HTML, "nonexistent", "<div>x</div>")
        assert result is None

    def test_replace_nested_tags(self) -> None:
        html = (
            "<html><body>"
            "<div id='outer'><div><span>inner</span></div></div>"
            "</body></html>"
        )
        result = _replace_element_by_id(html, "outer", "<div id='outer'>new</div>")
        assert result is not None
        assert "<span>inner</span>" not in result
        assert "new" in result


class TestAppendPrepend:
    def test_append_to_body(self) -> None:
        result = _apply_append_to_body(_SAMPLE_HTML, "<div id='new'>appended</div>")
        body_close = result.rfind("</body>")
        new_pos = result.rfind("appended")
        assert new_pos < body_close

    def test_prepend_to_body(self) -> None:
        result = _apply_prepend_to_body(_SAMPLE_HTML, "<div id='first'>prepended</div>")
        # prepended content should appear before original nav
        prepended_pos = result.find("prepended")
        nav_pos = result.find("Old nav")
        assert prepended_pos < nav_pos

    def test_append_no_body_tag(self) -> None:
        html = "<div>content</div>"
        result = _apply_append_to_body(html, "<footer>footer</footer>")
        assert "footer" in result

    def test_prepend_no_body_tag(self) -> None:
        html = "<div>content</div>"
        result = _apply_prepend_to_body(html, "<header>header</header>")
        assert "header" in result


class TestApplyBlocksToStaticFiles:
    def _block(self, **kwargs: Any) -> dict[str, Any]:
        base = {
            "role": "html_block_v1",
            "block_id": "hero",
            "target_path": "component/preview/index.html",
            "operation": "replace",
            "target_selector": "#hero",
            "content": "<section id='hero'><h1>Updated hero</h1></section>",
            "preview_anchor": "hero",
        }
        base.update(kwargs)
        return base

    def test_replace_existing_section(self) -> None:
        merged_map, anchors = apply_blocks_to_static_files(
            [self._block()],
            {"component/preview/index.html": _SAMPLE_HTML},
        )
        assert "component/preview/index.html" in merged_map
        html = merged_map["component/preview/index.html"]
        assert "Updated hero" in html
        assert "Old heading" not in html
        assert anchors == ["hero"]

    def test_new_file_seeded_from_template(self) -> None:
        """When target_path doesn't exist in file_map, create from minimal template."""
        merged_map, anchors = apply_blocks_to_static_files(
            [self._block(operation="append_to_body", target_selector="__body__")],
            {},  # no existing files
        )
        assert "component/preview/index.html" in merged_map
        html = merged_map["component/preview/index.html"]
        assert "Updated hero" in html

    def test_element_not_found_fallback_to_append(self) -> None:
        """When replace target not found, content is appended to body."""
        merged_map, anchors = apply_blocks_to_static_files(
            [self._block(target_selector="#nonexistent")],
            {"component/preview/index.html": _SAMPLE_HTML},
        )
        html = merged_map.get("component/preview/index.html", "")
        assert "Updated hero" in html

    def test_identical_content_returns_empty_merged_map(self) -> None:
        """If the replacement produces identical HTML, no file is marked as changed."""
        # Pass the exact existing section content as the replacement
        original_section = (
            '<section id="hero">\n'
            "  <h1>Old heading</h1>\n"
            "  <p>Old body</p>\n"
            "</section>"
        )
        merged_map, _ = apply_blocks_to_static_files(
            [self._block(content=original_section)],
            {"component/preview/index.html": _SAMPLE_HTML},
        )
        # Content is identical after replacement → file should NOT appear in merged_map
        assert "component/preview/index.html" not in merged_map, (
            "unchanged file should not appear in merged_map"
        )

    def test_multiple_blocks_same_file(self) -> None:
        block1 = self._block(block_id="hero", target_selector="#hero",
                              content="<section id='hero'>New hero</section>",
                              preview_anchor="hero")
        block2 = self._block(block_id="footer", target_selector="#footer",
                              content="<footer id='footer'>New footer</footer>",
                              preview_anchor="footer")
        merged_map, anchors = apply_blocks_to_static_files(
            [block1, block2],
            {"component/preview/index.html": _SAMPLE_HTML},
        )
        html = merged_map["component/preview/index.html"]
        assert "New hero" in html
        assert "New footer" in html
        assert "hero" in anchors
        assert "footer" in anchors

    def test_apply_html_block_helper(self) -> None:
        result = apply_html_block(_SAMPLE_HTML, self._block())
        assert "Updated hero" in result

    def test_anchors_derived_from_target_selector(self) -> None:
        block = self._block(preview_anchor=None)  # no explicit anchor
        merged_map, anchors = apply_blocks_to_static_files(
            [block],
            {"component/preview/index.html": _SAMPLE_HTML},
        )
        assert "hero" in anchors  # derived from target_selector=#hero


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integrity check accepts html_block_v1 output
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrityAcceptsHtmlBlocks:
    def test_block_only_output_is_valid(self) -> None:
        output = {
            "artifact_outputs": [
                {
                    "role": "html_block_v1",
                    "block_id": "hero",
                    "target_path": "component/preview/index.html",
                    "operation": "replace",
                    "target_selector": "#hero",
                    "content": "<section id='hero'>x</section>",
                }
            ]
        }
        validate_generator_output_for_candidate(output)  # must not raise

    def test_empty_artifact_outputs_still_invalid(self) -> None:
        with pytest.raises(ValueError):
            validate_generator_output_for_candidate({"artifact_outputs": []})

    def test_no_primary_field_still_invalid(self) -> None:
        with pytest.raises(ValueError):
            validate_generator_output_for_candidate({})


# ─────────────────────────────────────────────────────────────────────────────
# 4. Staging snapshot metadata carries block_preview_anchors
# ─────────────────────────────────────────────────────────────────────────────

class TestStagingSnapshotBlockAnchors:
    def _make_bc(
        self,
        block_preview_anchors: list[str] | None = None,
    ) -> Any:
        from kmbl_orchestrator.domain import BuildCandidateRecord

        wsp: dict[str, Any] = {}
        if block_preview_anchors:
            wsp["block_preview_anchors"] = block_preview_anchors

        return BuildCandidateRecord(
            build_candidate_id=uuid4(),
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
            candidate_kind="habitat",
            working_state_patch_json=wsp,
            artifact_refs_json=[
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html><body><h1>hi</h1></body></html>",
                    "entry_for_preview": True,
                }
            ],
        )

    def test_block_anchors_present_in_payload(self) -> None:
        from kmbl_orchestrator.domain import EvaluationReportRecord, ThreadRecord
        from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload

        bc = self._make_bc(block_preview_anchors=["hero", "about"])
        er = EvaluationReportRecord(
            evaluation_report_id=uuid4(),
            thread_id=bc.thread_id,
            graph_run_id=bc.graph_run_id,
            evaluator_invocation_id=uuid4(),
            build_candidate_id=bc.build_candidate_id,
            status="pass",
            summary="ok",
        )
        thread = ThreadRecord(thread_id=bc.thread_id)
        payload = build_staging_snapshot_payload(
            build_candidate=bc,
            evaluation_report=er,
            thread=thread,
            build_spec=None,
        )
        anchors = payload["metadata"]["block_preview_anchors"]
        assert anchors == ["hero", "about"]

    def test_no_block_anchors_is_empty_list(self) -> None:
        from kmbl_orchestrator.domain import EvaluationReportRecord, ThreadRecord
        from kmbl_orchestrator.staging.build_snapshot import build_staging_snapshot_payload

        bc = self._make_bc()  # no anchors
        er = EvaluationReportRecord(
            evaluation_report_id=uuid4(),
            thread_id=bc.thread_id,
            graph_run_id=bc.graph_run_id,
            evaluator_invocation_id=uuid4(),
            build_candidate_id=bc.build_candidate_id,
            status="pass",
        )
        thread = ThreadRecord(thread_id=bc.thread_id)
        payload = build_staging_snapshot_payload(
            build_candidate=bc,
            evaluation_report=er,
            thread=thread,
            build_spec=None,
        )
        assert payload["metadata"]["block_preview_anchors"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. End-to-end: generator_node applies blocks via the graph pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestGeneratorNodeBlockApplication:
    """Integration: blocks produced by the stub transport flow through generator_node."""

    def _make_settings(self) -> Any:
        from kmbl_orchestrator.config import Settings

        return Settings.model_construct(
            openclaw_transport="stub",
            graph_max_iterations_default=3,
            habitat_image_generation_enabled=False,
        )

    def test_block_applied_to_existing_working_staging(self) -> None:
        """When a working_staging HTML exists, html_block_v1 amendments merge correctly."""
        from kmbl_orchestrator.graph.app import (
            GraphContext,
            _apply_html_blocks_to_candidate,
            _extract_html_file_map_from_working_staging,
        )
        from kmbl_orchestrator.domain import (
            BuildCandidateRecord,
            WorkingStagingRecord,
        )
        from kmbl_orchestrator.persistence.repository import InMemoryRepository

        repo = InMemoryRepository()
        settings = self._make_settings()

        # Seed a working staging with an existing HTML
        tid = uuid4()
        ws = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=tid,
            payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {
                            "role": "static_frontend_file_v1",
                            "path": "component/preview/index.html",
                            "language": "html",
                            "content": _SAMPLE_HTML,
                            "entry_for_preview": True,
                        }
                    ]
                }
            },
        )
        repo.save_working_staging(ws)

        # Candidate with html_block_v1 artifact
        block = {
            "role": "html_block_v1",
            "block_id": "hero",
            "target_path": "component/preview/index.html",
            "operation": "replace",
            "target_selector": "#hero",
            "content": "<section id='hero'><h1>Block-generated hero</h1></section>",
            "preview_anchor": "hero",
        }
        cand = BuildCandidateRecord(
            build_candidate_id=uuid4(),
            thread_id=tid,
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
            candidate_kind="habitat",
            artifact_refs_json=[block],
        )

        # Test extraction
        file_map = _extract_html_file_map_from_working_staging(ws)
        assert "component/preview/index.html" in file_map

        # Apply blocks
        from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

        ctx = GraphContext(repo, DefaultRoleInvoker(settings=settings), settings)
        updated = _apply_html_blocks_to_candidate(ctx, cand, tid)

        # Should have merged static file + original block for provenance
        roles = {a.get("role") for a in updated.artifact_refs_json if isinstance(a, dict)}
        assert "static_frontend_file_v1" in roles
        assert "html_block_v1" in roles

        # Merged HTML should contain the new content
        merged_static = next(
            a for a in updated.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        )
        assert "Block-generated hero" in merged_static["content"]
        assert "Old heading" not in merged_static["content"]

        # Block anchor should be recorded in working_state_patch
        anchors = updated.working_state_patch_json.get("block_preview_anchors", [])
        assert "hero" in anchors

    def test_no_blocks_candidate_unchanged(self) -> None:
        """Candidate without html_block_v1 is returned unchanged."""
        from kmbl_orchestrator.graph.app import (
            GraphContext,
            _apply_html_blocks_to_candidate,
        )
        from kmbl_orchestrator.domain import BuildCandidateRecord
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

        repo = InMemoryRepository()
        settings = self._make_settings()
        tid = uuid4()
        cand = BuildCandidateRecord(
            build_candidate_id=uuid4(),
            thread_id=tid,
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
            candidate_kind="habitat",
            artifact_refs_json=[
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html>ok</html>",
                    "entry_for_preview": True,
                }
            ],
        )
        ctx = GraphContext(repo, DefaultRoleInvoker(settings=settings), settings)
        result = _apply_html_blocks_to_candidate(ctx, cand, tid)
        assert result is cand  # same object returned when no blocks

    def test_block_without_existing_staging_seeds_from_template(self) -> None:
        """Block with no existing working_staging creates the file from minimal template."""
        from kmbl_orchestrator.graph.app import (
            GraphContext,
            _apply_html_blocks_to_candidate,
        )
        from kmbl_orchestrator.domain import BuildCandidateRecord
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

        repo = InMemoryRepository()
        settings = self._make_settings()
        tid = uuid4()  # no working_staging saved for this thread

        block = {
            "role": "html_block_v1",
            "block_id": "main",
            "target_path": "component/preview/index.html",
            "operation": "append_to_body",
            "target_selector": "__body__",
            "content": "<main id='main'><p>First content</p></main>",
            "preview_anchor": "main",
        }
        cand = BuildCandidateRecord(
            build_candidate_id=uuid4(),
            thread_id=tid,
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
            candidate_kind="habitat",
            artifact_refs_json=[block],
        )

        ctx = GraphContext(repo, DefaultRoleInvoker(settings=settings), settings)
        updated = _apply_html_blocks_to_candidate(ctx, cand, tid)

        static_refs = [
            a for a in updated.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert static_refs, "expected a static_frontend_file_v1 to be created from template"
        html = static_refs[0]["content"]
        assert "First content" in html

        anchors = updated.working_state_patch_json.get("block_preview_anchors", [])
        assert "main" in anchors
