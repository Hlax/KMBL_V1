"""Tests for the reality audit fixes — verify each subsystem actually works end-to-end."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.domain import CrawlStateRecord, IdentityProfileRecord
from kmbl_orchestrator.identity.crawl_state import (
    build_crawl_context_for_planner,
    get_or_create_crawl_state,
    record_page_visit,
    seed_external_inspiration,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.build_snapshot import (
    StagingPayloadFrontendStaticFileV1,
    derive_frontend_static_v1,
)
from kmbl_orchestrator.staging.static_preview_assembly import static_file_map_from_payload


# ---------------------------------------------------------------------------
# FIX 1 — Crawl persistence: Supabase deserializer round-trip
# ---------------------------------------------------------------------------

class TestCrawlStateDeserializer:
    def test_row_to_crawl_state(self):
        from kmbl_orchestrator.persistence.supabase_deserializers import _row_to_crawl_state

        iid = uuid4()
        row = {
            "identity_id": str(iid),
            "root_url": "https://example.com",
            "visited_urls": ["https://example.com"],
            "unvisited_urls": ["https://example.com/about"],
            "page_summaries": {
                "https://example.com": {
                    "summary": "Homepage",
                    "design_signals": ["minimal"],
                    "tone_keywords": ["professional"],
                    "crawled_at": "2026-01-01T00:00:00Z",
                }
            },
            "crawl_status": "in_progress",
            "external_inspiration_urls": [],
            "total_pages_crawled": 1,
            "last_crawled_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        record = _row_to_crawl_state(row)
        assert record.identity_id == iid
        assert record.root_url == "https://example.com"
        assert len(record.visited_urls) == 1
        assert len(record.unvisited_urls) == 1
        assert record.crawl_status == "in_progress"
        assert record.total_pages_crawled == 1


# ---------------------------------------------------------------------------
# FIX 2 — Crawl feedback loop: frontier advances across runs
# ---------------------------------------------------------------------------

class TestCrawlFeedbackLoop:
    def test_frontier_advances_after_page_visits(self):
        """visited_urls grows and unvisited_urls shrinks after page visits."""
        repo = InMemoryRepository()
        iid = uuid4()
        root = "https://example.com"

        # Seed initial state
        state = get_or_create_crawl_state(repo, iid, root)
        assert state.unvisited_urls == ["https://example.com/"]
        assert state.visited_urls == []

        # Visit root and discover links
        state = record_page_visit(
            repo, iid, root,
            summary="Homepage",
            discovered_links=["https://example.com/about", "https://example.com/contact"],
        )
        assert "https://example.com/" in state.visited_urls
        assert "https://example.com/about" in state.unvisited_urls
        assert "https://example.com/contact" in state.unvisited_urls
        assert len(state.visited_urls) == 1
        assert len(state.unvisited_urls) == 2
        assert state.total_pages_crawled == 1

        # Visit about page
        state = record_page_visit(repo, iid, "https://example.com/about", summary="About page")
        assert len(state.visited_urls) == 2
        assert len(state.unvisited_urls) == 1
        assert state.total_pages_crawled == 2

        # Visit contact page — should exhaust internal crawl
        state = record_page_visit(repo, iid, "https://example.com/contact", summary="Contact page")
        assert len(state.visited_urls) == 3
        assert len(state.unvisited_urls) == 0
        assert state.crawl_status == "exhausted"

    def test_crawl_context_reflects_frontier_state(self):
        """build_crawl_context_for_planner shows accurate frontier info."""
        repo = InMemoryRepository()
        iid = uuid4()

        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        ctx = build_crawl_context_for_planner(state)
        assert ctx["crawl_available"] is True
        assert ctx["unvisited_count"] == 1
        assert ctx["visited_count"] == 0
        assert ctx["next_urls_to_crawl"] == ["https://example.com/"]

        # After visiting root
        state = record_page_visit(
            repo, iid, "https://example.com",
            discovered_links=["https://example.com/about"],
        )
        ctx = build_crawl_context_for_planner(state)
        assert ctx["visited_count"] == 1
        assert ctx["unvisited_count"] == 1
        assert "https://example.com/about" in ctx["next_urls_to_crawl"]

    def test_cross_session_resumption(self):
        """Second call to get_or_create_crawl_state returns existing state."""
        repo = InMemoryRepository()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo, iid, "https://example.com",
            discovered_links=["https://example.com/about"],
        )

        # "New session" — loads existing state
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        assert len(state.visited_urls) == 1
        assert len(state.unvisited_urls) == 1
        assert state.total_pages_crawled == 1


# ---------------------------------------------------------------------------
# FIX 2 + 3 — Loop service: _advance_crawl_frontier + _maybe_seed_external
# ---------------------------------------------------------------------------

class TestAdvanceCrawlFrontier:
    def _make_loop(self, identity_id: UUID) -> "AutonomousLoopRecord":
        from kmbl_orchestrator.domain import AutonomousLoopRecord
        return AutonomousLoopRecord(
            loop_id=uuid4(),
            identity_id=identity_id,
            identity_url="https://example.com",
            status="running",
            phase="graph_cycle",
        )

    def test_advance_marks_urls_visited(self):
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = self._make_loop(iid)

        # Seed state with root URL
        get_or_create_crawl_state(repo, iid, "https://example.com")

        # Advance frontier
        _advance_crawl_frontier(repo, loop, {"graph_run_id": "test-run-1"})

        state = repo.get_crawl_state(iid)
        assert state is not None
        assert "https://example.com/" in state.visited_urls
        assert state.total_pages_crawled == 1

    def test_advance_triggers_external_on_exhaustion(self):
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = self._make_loop(iid)

        # Seed state with root URL only (no discovered links)
        get_or_create_crawl_state(repo, iid, "https://example.com")

        # Advance — will exhaust (only root URL, no new links discovered)
        _advance_crawl_frontier(repo, loop, {"graph_run_id": "test-run-1"})

        state = repo.get_crawl_state(iid)
        assert state is not None
        assert state.crawl_status == "exhausted"
        # External inspiration should have been seeded
        assert len(state.external_inspiration_urls) > 0

    def test_external_seeding_idempotent(self):
        """External inspiration is only seeded once."""
        from kmbl_orchestrator.autonomous.loop_service import _maybe_seed_external

        repo = InMemoryRepository()
        iid = uuid4()
        loop = self._make_loop(iid)

        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com")  # exhaust

        _maybe_seed_external(repo, loop)
        state = repo.get_crawl_state(iid)
        external_count = len(state.external_inspiration_urls)
        assert external_count > 0

        # Second call should not add more
        _maybe_seed_external(repo, loop)
        state = repo.get_crawl_state(iid)
        assert len(state.external_inspiration_urls) == external_count


# ---------------------------------------------------------------------------
# FIX 3 — Identity-aware external inspiration
# ---------------------------------------------------------------------------

class TestIdentityAwareInspiration:
    def test_derive_inspiration_from_themes(self):
        from kmbl_orchestrator.autonomous.loop_service import _derive_inspiration_urls_for_identity

        repo = InMemoryRepository()
        iid = uuid4()
        repo.upsert_identity_profile(IdentityProfileRecord(
            identity_id=iid,
            profile_summary="An artistic photography studio",
            facets_json={"themes": ["artistic", "cinematic"]},
        ))
        urls = _derive_inspiration_urls_for_identity(repo, iid)
        assert urls is not None
        assert any("behance" in u for u in urls)

    def test_fallback_to_defaults_without_profile(self):
        from kmbl_orchestrator.autonomous.loop_service import _derive_inspiration_urls_for_identity

        repo = InMemoryRepository()
        iid = uuid4()
        urls = _derive_inspiration_urls_for_identity(repo, iid)
        assert urls is None  # Will use defaults


# ---------------------------------------------------------------------------
# FIX 4 — Staging preserves json/glsl/wgsl files
# ---------------------------------------------------------------------------

class TestStagingPreservesNewFileTypes:
    def test_derive_frontend_static_includes_glsl(self):
        """GLSL files are preserved through derive_frontend_static_v1."""
        refs = [
            {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
             "language": "html", "content": "<html></html>", "bundle_id": "b1"},
            {"role": "static_frontend_file_v1", "path": "component/preview/vertex.glsl",
             "language": "glsl", "content": "void main() {}", "bundle_id": "b1"},
            {"role": "static_frontend_file_v1", "path": "component/preview/fragment.glsl",
             "language": "glsl", "content": "void main() {}", "bundle_id": "b1"},
        ]
        result = derive_frontend_static_v1(refs, {})
        assert result is not None
        assert result.file_count == 3
        paths = [f.path for f in result.files]
        assert "component/preview/vertex.glsl" in paths
        assert "component/preview/fragment.glsl" in paths

    def test_derive_frontend_static_includes_wgsl(self):
        """WGSL files are preserved through derive_frontend_static_v1."""
        refs = [
            {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
             "language": "html", "content": "<html></html>"},
            {"role": "static_frontend_file_v1", "path": "component/preview/shader.wgsl",
             "language": "wgsl", "content": "@vertex fn main() {}"},
        ]
        result = derive_frontend_static_v1(refs, {})
        assert result is not None
        assert result.file_count == 2
        assert any(f.language == "wgsl" for f in result.files)

    def test_derive_frontend_static_includes_json(self):
        """JSON files are preserved through derive_frontend_static_v1."""
        refs = [
            {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
             "language": "html", "content": "<html></html>"},
            {"role": "static_frontend_file_v1", "path": "component/preview/config.json",
             "language": "json", "content": '{"scene": {}}'},
        ]
        result = derive_frontend_static_v1(refs, {})
        assert result is not None
        assert result.file_count == 2
        assert any(f.language == "json" for f in result.files)

    def test_static_file_map_includes_all_types(self):
        """static_file_map_from_payload includes json/glsl/wgsl files."""
        payload = {
            "artifacts": {
                "artifact_refs": [
                    {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
                     "language": "html", "content": "<html></html>"},
                    {"role": "static_frontend_file_v1", "path": "component/preview/vertex.glsl",
                     "language": "glsl", "content": "void main() {}"},
                    {"role": "static_frontend_file_v1", "path": "component/preview/config.json",
                     "language": "json", "content": '{"key": "value"}'},
                    {"role": "static_frontend_file_v1", "path": "component/preview/shader.wgsl",
                     "language": "wgsl", "content": "@vertex fn main() {}"},
                ],
            },
        }
        fmap = static_file_map_from_payload(payload)
        assert "component/preview/vertex.glsl" in fmap
        assert "component/preview/config.json" in fmap
        assert "component/preview/shader.wgsl" in fmap

    def test_unknown_language_dropped_with_warning(self):
        """Artifacts with truly unknown languages are skipped."""
        refs = [
            {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
             "language": "html", "content": "<html></html>"},
            {"role": "static_frontend_file_v1", "path": "component/preview/data.xml",
             "language": "xml", "content": "<data/>"},
        ]
        result = derive_frontend_static_v1(refs, {})
        assert result is not None
        assert result.file_count == 1  # xml not included


# ---------------------------------------------------------------------------
# FIX 5 — File serving endpoint
# ---------------------------------------------------------------------------

class TestFileStagingEndpoint:
    def test_get_staging_file_serves_glsl(self):
        """Individual file endpoint serves GLSL with correct MIME type."""
        from fastapi.testclient import TestClient
        from kmbl_orchestrator.api.routes_staging_query import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        repo = InMemoryRepository()
        from kmbl_orchestrator.api.deps import get_repo
        app.dependency_overrides[get_repo] = lambda: repo

        # Create a staging snapshot with a shader file
        from kmbl_orchestrator.domain import StagingSnapshotRecord
        ssid = uuid4()
        repo.save_staging_snapshot(StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=uuid4(),
            build_candidate_id=uuid4(),
            snapshot_payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {"role": "static_frontend_file_v1", "path": "component/preview/vertex.glsl",
                         "language": "glsl", "content": "void main() { gl_Position = vec4(0.0); }"},
                    ],
                },
            },
        ))

        client = TestClient(app)
        resp = client.get(f"/orchestrator/staging/{ssid}/file/component/preview/vertex.glsl")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "gl_Position" in resp.text

    def test_get_staging_file_serves_json(self):
        """Individual file endpoint serves JSON with correct MIME type."""
        from fastapi.testclient import TestClient
        from kmbl_orchestrator.api.routes_staging_query import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        repo = InMemoryRepository()
        from kmbl_orchestrator.api.deps import get_repo
        app.dependency_overrides[get_repo] = lambda: repo

        from kmbl_orchestrator.domain import StagingSnapshotRecord
        ssid = uuid4()
        repo.save_staging_snapshot(StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=uuid4(),
            build_candidate_id=uuid4(),
            snapshot_payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {"role": "static_frontend_file_v1", "path": "component/preview/config.json",
                         "language": "json", "content": '{"scene": "forest"}'},
                    ],
                },
            },
        ))

        client = TestClient(app)
        resp = client.get(f"/orchestrator/staging/{ssid}/file/component/preview/config.json")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        assert "forest" in resp.text

    def test_get_staging_file_404_for_missing(self):
        """File endpoint returns 404 for nonexistent files."""
        from fastapi.testclient import TestClient
        from kmbl_orchestrator.api.routes_staging_query import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        repo = InMemoryRepository()
        from kmbl_orchestrator.api.deps import get_repo
        app.dependency_overrides[get_repo] = lambda: repo

        from kmbl_orchestrator.domain import StagingSnapshotRecord
        ssid = uuid4()
        repo.save_staging_snapshot(StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=uuid4(),
            build_candidate_id=uuid4(),
            snapshot_payload_json={"artifacts": {"artifact_refs": []}},
        ))

        client = TestClient(app)
        resp = client.get(f"/orchestrator/staging/{ssid}/file/component/preview/missing.glsl")
        assert resp.status_code == 404

    def test_static_preview_csp_allows_connect(self):
        """CSP header allows connect-src 'self' for fetch calls."""
        from fastapi.testclient import TestClient
        from kmbl_orchestrator.api.routes_staging_query import router

        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)

        repo = InMemoryRepository()
        from kmbl_orchestrator.api.deps import get_repo
        app.dependency_overrides[get_repo] = lambda: repo

        from kmbl_orchestrator.domain import StagingSnapshotRecord
        ssid = uuid4()
        repo.save_staging_snapshot(StagingSnapshotRecord(
            staging_snapshot_id=ssid,
            thread_id=uuid4(),
            build_candidate_id=uuid4(),
            snapshot_payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {"role": "static_frontend_file_v1", "path": "component/preview/index.html",
                         "language": "html", "content": "<html><body>Hello</body></html>",
                         "bundle_id": "b1", "previewable": True, "entry_for_preview": True},
                    ],
                },
                "metadata": {"working_state_patch": {}},
            },
        ))

        client = TestClient(app)
        resp = client.get(f"/orchestrator/staging/{ssid}/static-preview")
        assert resp.status_code == 200
        assert "connect-src 'self'" in resp.headers.get("content-security-policy", "")


# ---------------------------------------------------------------------------
# FIX 6 — surface_type derivation
# ---------------------------------------------------------------------------

class TestSurfaceType:
    def test_static_html_for_flat_modes(self):
        from kmbl_orchestrator.graph.nodes_pkg.planner import _derive_surface_type
        assert _derive_surface_type("flat_standard") == "static_html"
        assert _derive_surface_type("flat_editorial_static") == "static_html"
        assert _derive_surface_type("") == "static_html"

    def test_webgl_for_3d_modes(self):
        from kmbl_orchestrator.graph.nodes_pkg.planner import _derive_surface_type
        assert _derive_surface_type("webgl_3d_portfolio") == "webgl_experience"
        assert _derive_surface_type("immersive_spatial_portfolio") == "webgl_experience"
        assert _derive_surface_type("model_centric_experience") == "webgl_experience"

    def test_surface_type_in_generator_contract(self):
        """GeneratorRoleInput accepts surface_type field."""
        from kmbl_orchestrator.contracts.role_inputs import GeneratorRoleInput

        inp = GeneratorRoleInput(
            thread_id="t1",
            build_spec={},
            surface_type="webgl_experience",
        )
        assert inp.surface_type == "webgl_experience"

    def test_surface_type_default_is_static_html(self):
        from kmbl_orchestrator.contracts.role_inputs import GeneratorRoleInput

        inp = GeneratorRoleInput(thread_id="t1", build_spec={})
        assert inp.surface_type == "static_html"

    def test_kmbl_habitat_runtime_accepted_by_validate_role_input(self):
        from kmbl_orchestrator.contracts.role_inputs import validate_role_input

        out = validate_role_input(
            "generator",
            {
                "thread_id": "t1",
                "build_spec": {},
                "kmbl_habitat_runtime": {
                    "effective_strategy": "fresh_start",
                    "suppress_prior_working_surface": True,
                },
            },
        )
        assert out["kmbl_habitat_runtime"]["effective_strategy"] == "fresh_start"
        assert out["kmbl_habitat_runtime"]["suppress_prior_working_surface"] is True
