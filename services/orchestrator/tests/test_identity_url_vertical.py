"""
Canonical vertical test: identity URL → static frontend.

Tests the end-to-end flow from identity extraction through to staging,
using the in-memory repository and stub invoker. This is the primary
proof test for the KMBL V1 canonical vertical.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.identity.seed import IdentitySeed
from kmbl_orchestrator.identity.extract import _SignalParser
from kmbl_orchestrator.identity.hydrate import (
    build_planner_identity_context,
    persist_identity_from_seed,
    DEFAULT_FALLBACK_PROFILE,
)
from kmbl_orchestrator.normalize.generator import (
    normalize_generator_output,
    _recover_static_files_from_proposed_changes,
    _recover_static_files_from_updated_state,
)
from kmbl_orchestrator.normalize.planner import normalize_planner_output
from kmbl_orchestrator.normalize.evaluator import normalize_evaluator_output
from kmbl_orchestrator.staging.build_snapshot import (
    build_staging_snapshot_payload,
    derive_frontend_static_v1,
)
from kmbl_orchestrator.staging.static_preview_assembly import (
    assemble_static_preview_html,
    resolve_static_preview_entry_path,
)
from kmbl_orchestrator.seeds import (
    IDENTITY_URL_STATIC_FRONTEND_TAG,
    build_identity_url_static_frontend_event_input,
)


# --- Identity seed tests ---


class TestIdentitySeed:
    def test_minimal_seed(self):
        seed = IdentitySeed(source_url="https://example.com")
        assert seed.source_url == "https://example.com"
        assert seed.confidence == 0.0
        assert seed.display_name is None

    def test_rich_seed(self):
        seed = IdentitySeed(
            source_url="https://janedoe.com",
            display_name="Jane Doe",
            role_or_title="UX Designer",
            short_bio="Building beautiful interfaces since 2015.",
            tone_keywords=["professional", "clean"],
            aesthetic_keywords=["minimal", "portfolio"],
            palette_hints=["#333", "#f0f0f0"],
            image_refs=["https://janedoe.com/hero.jpg"],
            headings=["About", "Work", "Contact"],
            confidence=0.83,
        )
        assert seed.display_name == "Jane Doe"
        summary = seed.to_profile_summary()
        assert "Jane Doe" in summary
        assert "UX Designer" in summary

    def test_seed_to_facets(self):
        seed = IdentitySeed(
            source_url="https://example.com",
            tone_keywords=["bold"],
            aesthetic_keywords=["modern"],
        )
        facets = seed.to_facets_json()
        assert facets["source_url"] == "https://example.com"
        assert "bold" in facets["tone_keywords"]

    def test_seed_to_identity_context(self):
        seed = IdentitySeed(
            source_url="https://example.com",
            display_name="Test",
        )
        ctx = seed.to_identity_context_dict()
        assert ctx["source_url"] == "https://example.com"
        assert "confidence" not in ctx


# --- HTML parser tests ---


class TestSignalParser:
    def test_basic_html(self):
        html = """
        <html>
        <head><title>Jane Doe | Designer</title>
        <meta name="description" content="I design things.">
        </head>
        <body>
        <h1>Jane Doe</h1>
        <h2>About</h2>
        <p>I'm a designer based in NYC.</p>
        <img src="/hero.jpg">
        <a href="/work">My Work</a>
        </body>
        </html>
        """
        parser = _SignalParser()
        parser.feed(html)
        assert parser.title == "Jane Doe | Designer"
        assert parser.meta_description == "I design things."
        assert "Jane Doe" in parser.headings
        assert "About" in parser.headings
        assert len(parser.image_srcs) == 1
        assert len(parser.link_texts) >= 1


# --- Identity persistence tests ---


class TestIdentityPersistence:
    def test_persist_seed_creates_records(self):
        from kmbl_orchestrator.persistence.repository import InMemoryRepository

        repo = InMemoryRepository()
        seed = IdentitySeed(
            source_url="https://example.com",
            display_name="Test Site",
            short_bio="A test website.",
            tone_keywords=["clean"],
            confidence=0.7,
        )
        iid = persist_identity_from_seed(repo, seed)
        assert isinstance(iid, UUID)

        ctx = build_planner_identity_context(repo, iid)
        assert ctx["identity_id"] == str(iid)
        assert ctx["profile_summary"] is not None
        assert "Test Site" in ctx["profile_summary"]
        assert ctx["source_count"] == 1
        assert len(ctx["recent_source_summaries"]) == 1

    def test_fallback_profile_applied_when_empty(self):
        """Fallback 'creative architect' profile applied when extraction yields empty."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import IdentityProfileRecord

        repo = InMemoryRepository()
        iid = uuid4()

        empty_profile = IdentityProfileRecord(
            identity_id=iid,
            profile_summary="",
            facets_json={},
            open_questions_json=[],
        )
        repo.upsert_identity_profile(empty_profile)

        ctx = build_planner_identity_context(repo, iid)
        assert ctx["identity_id"] == str(iid)
        assert ctx["profile_summary"] == DEFAULT_FALLBACK_PROFILE["profile_summary"]
        assert ctx["facets_json"] == DEFAULT_FALLBACK_PROFILE["facets_json"]
        assert ctx.get("is_fallback") is True

    def test_fallback_not_applied_when_profile_has_data(self):
        """Fallback should NOT be applied when profile has real data."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import IdentityProfileRecord

        repo = InMemoryRepository()
        iid = uuid4()

        real_profile = IdentityProfileRecord(
            identity_id=iid,
            profile_summary="Real Person — actual identity",
            facets_json={"tone_keywords": ["bold"]},
            open_questions_json=[],
        )
        repo.upsert_identity_profile(real_profile)

        ctx = build_planner_identity_context(repo, iid)
        assert ctx["profile_summary"] == "Real Person — actual identity"
        assert ctx["facets_json"] == {"tone_keywords": ["bold"]}
        assert ctx.get("is_fallback") is None

    def test_fallback_applied_when_only_profile_summary_empty(self):
        """Fallback requires BOTH profile_summary AND facets_json to be empty."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import IdentityProfileRecord

        repo = InMemoryRepository()
        iid = uuid4()

        partial_profile = IdentityProfileRecord(
            identity_id=iid,
            profile_summary="",
            facets_json={"tone_keywords": ["minimal"]},
            open_questions_json=[],
        )
        repo.upsert_identity_profile(partial_profile)

        ctx = build_planner_identity_context(repo, iid)
        assert ctx["profile_summary"] == ""
        assert ctx["facets_json"] == {"tone_keywords": ["minimal"]}
        assert ctx.get("is_fallback") is None


# --- Recovery promotion tests ---


class TestRecoveryPromotion:
    def test_promote_from_proposed_changes(self):
        proposed = {
            "files": [
                {
                    "path": "component/preview/index.html",
                    "content": "<html><body>Hello</body></html>",
                },
                {
                    "path": "component/preview/styles.css",
                    "content": "body { color: #333; }",
                },
            ]
        }
        result = _recover_static_files_from_proposed_changes(proposed, [])
        assert len(result) == 2
        assert result[0]["role"] == "static_frontend_file_v1"
        assert result[0]["language"] == "html"
        assert result[0]["entry_for_preview"] is True
        assert result[1]["language"] == "css"
        assert result[1]["entry_for_preview"] is False

    def test_no_promotion_when_artifacts_exist(self):
        existing = [{"role": "static_frontend_file_v1", "path": "component/x.html"}]
        proposed = {"files": [{"path": "component/y.html", "content": "<html>y</html>"}]}
        result = _recover_static_files_from_proposed_changes(proposed, existing)
        assert len(result) == 1

    def test_no_promotion_with_empty_content(self):
        proposed = {"files": [{"path": "component/empty.html", "content": ""}]}
        result = _recover_static_files_from_proposed_changes(proposed, [])
        assert len(result) == 0

    def test_no_promotion_with_non_component_path(self):
        proposed = {"files": [{"path": "src/app.js", "content": "console.log('hi')"}]}
        result = _recover_static_files_from_proposed_changes(proposed, [])
        assert len(result) == 0


# --- Generator normalize with recovery ---


class TestGeneratorNormalizeWithRecovery:
    def test_artifacts_promoted_from_proposed_changes(self):
        raw = {
            "proposed_changes": {
                "files": [
                    {
                        "path": "component/preview/index.html",
                        "content": "<!DOCTYPE html><html><body><h1>Test</h1></body></html>",
                    },
                    {
                        "path": "component/preview/styles.css",
                        "content": "body { margin: 0; }",
                    },
                ]
            },
            "artifact_outputs": [],
            "updated_state": {},
        }
        cand = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        static_rows = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_rows) >= 2
        html_rows = [r for r in static_rows if r.get("language") == "html"]
        assert len(html_rows) >= 1


# --- Identity URL passthrough tests ---


class TestIdentityUrlPassthrough:
    """Verify identity_id is correctly passed when identity_url is provided."""

    def test_identity_id_str_updates_on_url_extraction(self):
        """Simulates the logic in api/main.py start_run where identity_id_str should update."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository

        repo = InMemoryRepository()

        body_identity_id = None
        identity_url = "https://example.com"

        identity_id_str = str(body_identity_id) if body_identity_id is not None else None
        assert identity_id_str is None

        seed = IdentitySeed(
            source_url=identity_url,
            display_name="Example",
            confidence=0.6,
        )
        iid = persist_identity_from_seed(repo, seed)
        identity_id_str = str(iid)

        assert identity_id_str is not None
        assert identity_id_str == str(iid)

        ctx = build_planner_identity_context(repo, UUID(identity_id_str))
        assert ctx["identity_id"] == identity_id_str
        assert "Example" in ctx["profile_summary"]

    def test_identity_id_str_preserved_when_explicit_id_provided(self):
        """When body.identity_id is provided, it should be used (not overwritten)."""
        explicit_id = uuid4()

        body_identity_id = explicit_id
        identity_url = None

        identity_id_str = str(body_identity_id) if body_identity_id is not None else None
        assert identity_id_str == str(explicit_id)


# --- Event input builder tests ---


class TestEventInputBuilder:
    def test_builds_identity_url_event_input(self):
        ev = build_identity_url_static_frontend_event_input(
            identity_url="https://example.com",
            seed_summary="Example Site — A test.",
        )
        assert ev["scenario"] == IDENTITY_URL_STATIC_FRONTEND_TAG
        assert "example.com" in ev["task"]
        assert ev["constraints"]["canonical_vertical"] == "static_frontend_file_v1"
        assert ev["identity_url"] == "https://example.com"


# --- End-to-end vertical flow (in-memory, stub data) ---


class TestCanonicalVerticalFlow:
    """Simulates the full vertical with normalized data (no live KiloClaw)."""

    def _make_planner_output(self) -> dict[str, Any]:
        return {
            "build_spec": {
                "type": "static_frontend",
                "title": "Jane Doe Portfolio",
                "description": "A single-page portfolio reflecting extracted identity.",
            },
            "constraints": {
                "canonical_vertical": "static_frontend_file_v1",
                "kmbl_static_frontend_vertical": True,
            },
            "success_criteria": [
                "Page contains heading with identity name",
                "Page has at least one section of content",
            ],
            "evaluation_targets": [
                {"check": "text_present", "text": "Jane Doe"},
                {"check": "artifact_role_count_min", "role": "static_frontend_file_v1", "min": 1},
            ],
        }

    def _make_generator_output(self) -> dict[str, Any]:
        return {
            "proposed_changes": {},
            "artifact_outputs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": (
                        "<!DOCTYPE html><html><head><title>Jane Doe</title>"
                        '<link rel="stylesheet" href="styles.css"></head>'
                        "<body><h1>Jane Doe</h1><p>UX Designer</p>"
                        "<section><h2>About</h2><p>Building interfaces since 2015.</p></section>"
                        "<footer>Contact: jane@example.com</footer></body></html>"
                    ),
                    "entry_for_preview": True,
                },
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/styles.css",
                    "language": "css",
                    "content": (
                        "body { font-family: sans-serif; margin: 0; padding: 2rem; "
                        "color: #333; background: #fafafa; } "
                        "h1 { font-size: 2.5rem; } "
                        "section { margin: 2rem 0; } "
                        "footer { margin-top: 3rem; color: #666; }"
                    ),
                },
            ],
            "updated_state": {
                "static_frontend_preview_v1": {
                    "entry_path": "component/preview/index.html",
                }
            },
        }

    def _make_evaluator_output(self) -> dict[str, Any]:
        return {
            "status": "pass",
            "summary": "Static frontend produced with valid structure and identity content.",
            "issues": [],
            "metrics": {"artifact_count": 2, "has_html": True},
            "artifacts": [],
        }

    def test_full_vertical_flow(self):
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import ThreadRecord

        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()

        seed = IdentitySeed(
            source_url="https://janedoe.com",
            display_name="Jane Doe",
            role_or_title="UX Designer",
            short_bio="Building interfaces since 2015.",
            tone_keywords=["professional", "clean"],
            confidence=0.83,
        )
        iid = persist_identity_from_seed(repo, seed)

        repo.ensure_thread(ThreadRecord(
            thread_id=tid, identity_id=iid, thread_kind="build", status="active"
        ))
        ctx = build_planner_identity_context(repo, iid)
        assert ctx["identity_id"] == str(iid)
        assert "Jane Doe" in (ctx.get("profile_summary") or "")

        planner_raw = self._make_planner_output()
        spec = normalize_planner_output(
            planner_raw, thread_id=tid, graph_run_id=gid, planner_invocation_id=uuid4()
        )
        repo.save_build_spec(spec)
        assert spec.spec_json["type"] == "static_frontend"

        generator_raw = self._make_generator_output()
        cand = normalize_generator_output(
            generator_raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=uuid4(),
            build_spec_id=spec.build_spec_id,
        )
        repo.save_build_candidate(cand)
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) >= 1

        evaluator_raw = self._make_evaluator_output()
        report = normalize_evaluator_output(
            evaluator_raw,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=uuid4(),
            build_candidate_id=cand.build_candidate_id,
        )
        repo.save_evaluation_report(report)
        assert report.status == "pass"

        thread = repo.get_thread(tid)
        payload = build_staging_snapshot_payload(
            build_candidate=cand,
            evaluation_report=report,
            thread=thread,
            build_spec=spec,
        )
        assert payload["version"] == 1
        fs = payload["metadata"].get("frontend_static")
        assert fs is not None
        assert fs["has_previewable_html"] is True
        assert fs["file_count"] >= 1

        entry_path, error_code = resolve_static_preview_entry_path(payload)
        assert entry_path is not None, f"entry_path resolution failed: {error_code}"
        assert entry_path.endswith(".html")

        preview_html, preview_err = assemble_static_preview_html(payload, entry_path=entry_path)
        assert preview_html is not None, f"preview assembly failed: {preview_err}"
        assert "Jane Doe" in preview_html
        assert "font-family" in preview_html

    def test_vertical_with_recovery_promotion(self):
        """Generator puts files only in proposed_changes; recovery promotes them."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import ThreadRecord

        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()
        bsid = uuid4()

        generator_raw = {
            "proposed_changes": {
                "files": [
                    {
                        "path": "component/preview/index.html",
                        "content": "<html><body><h1>Recovered</h1></body></html>",
                    }
                ]
            },
            "artifact_outputs": [],
            "updated_state": {},
        }
        cand = normalize_generator_output(
            generator_raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=uuid4(),
            build_spec_id=bsid,
        )
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) >= 1
        assert "Recovered" in static_arts[0]["content"]

    def test_partial_evaluation_stages_successfully(self):
        """Partial evaluator output should produce a valid staging snapshot."""
        from kmbl_orchestrator.persistence.repository import InMemoryRepository
        from kmbl_orchestrator.domain import ThreadRecord

        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()

        seed = IdentitySeed(
            source_url="https://janedoe.com",
            display_name="Jane Doe",
            confidence=0.5,
        )
        iid = persist_identity_from_seed(repo, seed)
        repo.ensure_thread(ThreadRecord(
            thread_id=tid, identity_id=iid, thread_kind="build", status="active"
        ))

        planner_raw = self._make_planner_output()
        spec = normalize_planner_output(
            planner_raw, thread_id=tid, graph_run_id=gid, planner_invocation_id=uuid4()
        )
        repo.save_build_spec(spec)

        generator_raw = self._make_generator_output()
        cand = normalize_generator_output(
            generator_raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=uuid4(),
            build_spec_id=spec.build_spec_id,
        )
        repo.save_build_candidate(cand)

        evaluator_raw = {
            "status": "partial",
            "summary": "Output exists but some identity signals missing.",
            "issues": ["heading present but bio section incomplete"],
            "metrics": {"artifact_count": 2, "has_html": True},
            "artifacts": [],
        }
        report = normalize_evaluator_output(
            evaluator_raw,
            thread_id=tid,
            graph_run_id=gid,
            evaluator_invocation_id=uuid4(),
            build_candidate_id=cand.build_candidate_id,
        )
        repo.save_evaluation_report(report)
        assert report.status == "partial"

        thread = repo.get_thread(tid)
        payload = build_staging_snapshot_payload(
            build_candidate=cand,
            evaluation_report=report,
            thread=thread,
            build_spec=spec,
        )
        assert payload["version"] == 1
        assert payload["evaluation"]["status"] == "partial"
        fs = payload["metadata"].get("frontend_static")
        assert fs is not None
        assert fs["has_previewable_html"] is True

    def test_minimal_single_html_artifact_succeeds(self):
        """A single HTML file with no CSS/JS should normalize and preview."""
        raw = {
            "proposed_changes": {},
            "artifact_outputs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html><body><h1>Minimal</h1></body></html>",
                    "entry_for_preview": True,
                },
            ],
            "updated_state": {},
        }
        cand = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) == 1
        assert static_arts[0]["language"] == "html"


# --- Lenient normalization tests ---


class TestLenientNormalization:
    """Normalization should skip bad rows, not crash."""

    def test_extra_fields_on_artifact_ignored(self):
        """Generator adds extra keys like 'description' — should not crash."""
        raw = {
            "proposed_changes": {},
            "artifact_outputs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html><body>OK</body></html>",
                    "entry_for_preview": True,
                    "description": "A test page",
                    "metadata": {"author": "generator"},
                },
            ],
            "updated_state": {},
        }
        cand = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) == 1

    def test_bad_row_skipped_good_rows_preserved(self):
        """One malformed artifact should not crash the entire normalization."""
        raw = {
            "proposed_changes": {},
            "artifact_outputs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html><body>Good</body></html>",
                    "entry_for_preview": True,
                },
                {
                    "role": "static_frontend_file_v1",
                    "path": "",
                    "language": "html",
                    "content": "",
                },
            ],
            "updated_state": {},
        }
        cand = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) == 1
        assert "Good" in static_arts[0]["content"]

    def test_duplicate_paths_keep_first(self):
        """Duplicate paths should keep first, not crash."""
        from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
            normalize_static_frontend_artifact_outputs_list,
        )

        seq = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html>First</html>",
            },
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html>Second</html>",
            },
        ]
        result = normalize_static_frontend_artifact_outputs_list(seq)
        static = [r for r in result if isinstance(r, dict) and r.get("role") == "static_frontend_file_v1"]
        assert len(static) == 1
        assert "First" in static[0]["content"]


# --- Updated state recovery tests ---


class TestUpdatedStateRecovery:
    def test_promote_from_updated_state(self):
        updated = {
            "files": [
                {
                    "path": "component/preview/index.html",
                    "content": "<html><body>From state</body></html>",
                },
            ]
        }
        result = _recover_static_files_from_updated_state(updated, [])
        assert len(result) == 1
        assert result[0]["role"] == "static_frontend_file_v1"

    def test_no_promotion_when_artifacts_exist(self):
        existing = [{"role": "static_frontend_file_v1", "path": "component/x.html"}]
        updated = {"files": [{"path": "component/y.html", "content": "<html>y</html>"}]}
        result = _recover_static_files_from_updated_state(updated, existing)
        assert len(result) == 1

    def test_full_normalize_with_updated_state_recovery(self):
        raw = {
            "proposed_changes": {},
            "artifact_outputs": [],
            "updated_state": {
                "files": [
                    {
                        "path": "component/preview/index.html",
                        "content": "<html><body>Recovered from state</body></html>",
                    }
                ]
            },
        }
        cand = normalize_generator_output(
            raw,
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
        )
        static_arts = [
            a for a in cand.artifact_refs_json
            if isinstance(a, dict) and a.get("role") == "static_frontend_file_v1"
        ]
        assert len(static_arts) >= 1


# --- Gallery harness non-downgrade tests ---


class TestGalleryHarnessNonDowngrade:
    def test_gallery_harness_does_not_downgrade_status(self):
        from kmbl_orchestrator.normalize.gallery_strip_harness import (
            merge_gallery_strip_harness_checks,
        )
        from kmbl_orchestrator.domain import BuildCandidateRecord, EvaluationReportRecord

        bc = BuildCandidateRecord(
            build_candidate_id=uuid4(),
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            generator_invocation_id=uuid4(),
            build_spec_id=uuid4(),
            candidate_kind="habitat",
            working_state_patch_json={
                "ui_gallery_strip_v1": {
                    "items": [
                        {
                            "label": "Test",
                            "href": "http://example.com",
                            "image_url": "http://unreachable.invalid/img.jpg",
                        }
                    ]
                }
            },
            artifact_refs_json=[],
            status="generated",
        )
        report = EvaluationReportRecord(
            evaluation_report_id=uuid4(),
            thread_id=bc.thread_id,
            graph_run_id=bc.graph_run_id,
            evaluator_invocation_id=uuid4(),
            build_candidate_id=bc.build_candidate_id,
            status="pass",
            summary="All good",
            issues_json=[],
            metrics_json={},
            artifacts_json=[],
        )
        result = merge_gallery_strip_harness_checks(report, bc, probe_urls=False)
        assert result.status == "pass", "gallery harness must not downgrade pass status"


# --- Decision router tests ---


class TestDecisionRouterLogic:
    """Verify the extracted decision logic used by the graph's decision_router."""

    def test_pass_stages(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("pass", iteration=0, max_iterations=3)
        assert decision == "stage"
        assert reason is None

    def test_partial_iterates_below_max(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("partial", iteration=0, max_iterations=3)
        assert decision == "iterate"
        assert reason is None

    def test_partial_stages_at_max_iterations(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("partial", iteration=3, max_iterations=3)
        assert decision == "stage"
        assert reason is None

    def test_fail_iterates_below_max(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("fail", iteration=0, max_iterations=3)
        assert decision == "iterate"
        assert reason is None

    def test_fail_stages_at_max_iterations(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("fail", iteration=3, max_iterations=3)
        assert decision == "stage"
        assert reason is None

    def test_blocked_interrupts(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("blocked", iteration=0, max_iterations=3)
        assert decision == "interrupt"
        assert reason == "evaluator_blocked"

    def test_unknown_status_interrupts(self):
        from kmbl_orchestrator.graph.app import compute_evaluator_decision

        decision, reason = compute_evaluator_decision("garbage", iteration=0, max_iterations=3)
        assert decision == "interrupt"
        assert reason == "unknown_eval_status"

    def test_fail_duplicate_at_max_interrupts_not_stages(self):
        from kmbl_orchestrator.graph.app import (
            compute_evaluator_decision,
            maybe_suppress_duplicate_staging,
        )

        decision, reason = compute_evaluator_decision("fail", iteration=3, max_iterations=3)
        assert decision == "stage"
        d2, r2, suppressed = maybe_suppress_duplicate_staging(
            decision, reason, "fail", {"duplicate_rejection": True}
        )
        assert d2 == "interrupt"
        assert r2 == "duplicate_output_after_max_iterations"
        assert suppressed is True

    def test_fail_no_duplicate_metric_still_stages_at_max(self):
        from kmbl_orchestrator.graph.app import (
            compute_evaluator_decision,
            maybe_suppress_duplicate_staging,
        )

        decision, reason = compute_evaluator_decision("fail", iteration=3, max_iterations=3)
        d2, r2, suppressed = maybe_suppress_duplicate_staging(
            decision, reason, "fail", {}
        )
        assert d2 == "stage"
        assert r2 is None
        assert suppressed is False


class TestIterationPlanForGenerator:
    def test_none_for_empty_feedback(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        assert build_iteration_plan_for_generator(None) is None
        assert build_iteration_plan_for_generator({}) is None

    def test_fail_requests_pivot(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {"status": "fail", "summary": "x", "issues": [{"code": "a"}], "metrics": {}}
        )
        assert plan is not None
        assert plan["treat_feedback_as_amendment_plan"] is True
        assert plan["pivot_layout_strategy"] is True
        assert plan["iteration_strategy"] == "pivot"
        assert plan["evaluator_status"] == "fail"
        assert plan["issue_count"] == 1
        assert plan["headline"] == "x"

    def test_duplicate_requests_pivot(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {
                "status": "fail",
                "summary": None,
                "issues": [],
                "metrics": {"duplicate_rejection": True},
            }
        )
        assert plan["pivot_layout_strategy"] is True
        assert plan["iteration_strategy"] == "pivot"
        assert plan["duplicate_rejection"] is True

    def test_partial_no_pivot_by_default(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {
                "status": "partial",
                "summary": "ok",
                "issues": [{"code": "minor"}],
                "metrics": {},
            }
        )
        assert plan["pivot_layout_strategy"] is False
        assert plan["iteration_strategy"] == "refine"
        assert plan["evaluator_status"] == "partial"

    def test_partial_low_design_rubric_pivots(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {
                "status": "partial",
                "summary": "weak",
                "issues": [],
                "metrics": {"design_rubric": {"design_quality": 2, "originality": 1.5}},
            }
        )
        assert plan["pivot_layout_strategy"] is True
        assert plan["iteration_strategy"] == "pivot"

    def test_stagnation_pivots(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {"status": "partial", "summary": "x", "issues": [], "metrics": {}},
            stagnation_count=3,
        )
        assert plan["iteration_strategy"] == "pivot"
        assert plan["stagnation_count"] == 3

    def test_pressure_rebuild_pivots(self):
        from kmbl_orchestrator.runtime.iteration_plan import build_iteration_plan_for_generator

        plan = build_iteration_plan_for_generator(
            {"status": "partial", "summary": "x", "issues": [], "metrics": {}},
            pressure_recommendation="rebuild",
        )
        assert plan["iteration_strategy"] == "pivot"
