"""Tests for crawl state persistence, URL normalization, cross-session resumption,
internal link exhaustion, external inspiration transition, and generator flexibility."""

from __future__ import annotations

from uuid import uuid4

from kmbl_orchestrator.identity.url_normalize import (
    is_same_domain,
    normalize_url,
    resolve_url,
)
from kmbl_orchestrator.identity.crawl_state import (
    build_crawl_context_for_planner,
    get_next_urls_to_crawl,
    get_or_create_crawl_state,
    record_page_visit,
    seed_external_inspiration,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository


# ──────────────────────────────────────────────
# URL normalization
# ──────────────────────────────────────────────


class TestNormalizeUrl:
    def test_lowercase_scheme_and_host(self) -> None:
        assert normalize_url("HTTPS://Example.COM/path") == "https://example.com/path"

    def test_strip_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/about/") == "https://example.com/about"

    def test_keep_root_slash(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_remove_fragment(self) -> None:
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_remove_default_port_443(self) -> None:
        assert normalize_url("https://example.com:443/page") == "https://example.com/page"

    def test_remove_default_port_80(self) -> None:
        assert normalize_url("http://example.com:80/page") == "http://example.com/page"

    def test_keep_non_default_port(self) -> None:
        assert normalize_url("https://example.com:8080/page") == "https://example.com:8080/page"

    def test_strip_utm_params(self) -> None:
        result = normalize_url("https://example.com/page?utm_source=twitter&name=val")
        assert "utm_source" not in result
        assert "name=val" in result

    def test_strip_fbclid(self) -> None:
        result = normalize_url("https://example.com/page?fbclid=abc123")
        assert "fbclid" not in result

    def test_collapse_double_slashes(self) -> None:
        assert normalize_url("https://example.com//path///to") == "https://example.com/path/to"

    def test_empty_scheme_defaults_https(self) -> None:
        result = normalize_url("://example.com/page")
        assert result.startswith("https://")


class TestIsSameDomain:
    def test_same_domain(self) -> None:
        assert is_same_domain("https://example.com/about", "https://example.com/") is True

    def test_www_prefix_stripped(self) -> None:
        assert is_same_domain("https://www.example.com/", "https://example.com/") is True

    def test_different_domain(self) -> None:
        assert is_same_domain("https://other.com/", "https://example.com/") is False

    def test_invalid_url(self) -> None:
        assert is_same_domain("not-a-url", "https://example.com") is False


class TestResolveUrl:
    def test_relative_url(self) -> None:
        result = resolve_url("/about", "https://example.com/page")
        assert result == "https://example.com/about"

    def test_absolute_url(self) -> None:
        result = resolve_url("https://example.com/about", "https://example.com/page")
        assert result == "https://example.com/about"

    def test_javascript_ignored(self) -> None:
        assert resolve_url("javascript:void(0)", "https://example.com") is None

    def test_mailto_ignored(self) -> None:
        assert resolve_url("mailto:user@example.com", "https://example.com") is None

    def test_empty_ignored(self) -> None:
        assert resolve_url("", "https://example.com") is None


# ──────────────────────────────────────────────
# Crawl state persistence across sessions
# ──────────────────────────────────────────────


class TestCrawlStatePersistence:
    """Verify crawl state survives across simulated sessions."""

    def _make_repo(self) -> InMemoryRepository:
        return InMemoryRepository()

    def test_create_fresh_state(self) -> None:
        repo = self._make_repo()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        # normalize_url adds trailing slash for root paths
        assert state.root_url == normalize_url("https://example.com")
        assert state.crawl_status == "in_progress"
        assert len(state.unvisited_urls) == 1
        assert state.visited_urls == []

    def test_resume_existing_state(self) -> None:
        """Simulates two sessions: first creates, second resumes."""
        repo = self._make_repo()
        iid = uuid4()

        # Session 1: create and visit root
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com",
            summary="Landing page",
            discovered_links=["/about", "/work", "/contact"],
        )
        assert len(state.visited_urls) == 1
        assert len(state.unvisited_urls) == 3  # discovered internal links

        # Session 2: resume (simulated by calling get_or_create again)
        state2 = get_or_create_crawl_state(repo, iid, "https://example.com")
        assert state2.visited_urls == state.visited_urls
        assert state2.unvisited_urls == state.unvisited_urls
        assert state2.total_pages_crawled == 1

    def test_root_url_change_reseeds(self) -> None:
        """If root URL changes (user updated identity), crawl state is reset."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://old-site.com")
        record_page_visit(repo, iid, "https://old-site.com", summary="Old site")

        state2 = get_or_create_crawl_state(repo, iid, "https://new-site.com")
        assert state2.root_url == normalize_url("https://new-site.com")
        assert state2.total_pages_crawled == 0  # Fresh start

    def test_page_summaries_persist(self) -> None:
        repo = self._make_repo()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")

        state = record_page_visit(
            repo, iid, "https://example.com",
            summary="Creative portfolio landing page",
            design_signals=["minimal", "dark-mode"],
            tone_keywords=["professional", "innovative"],
        )

        normalized = normalize_url("https://example.com")
        assert normalized in state.page_summaries
        page_data = state.page_summaries[normalized]
        assert page_data["summary"] == "Creative portfolio landing page"
        assert "minimal" in page_data["design_signals"]
        assert "professional" in page_data["tone_keywords"]


# ──────────────────────────────────────────────
# Internal link exhaustion
# ──────────────────────────────────────────────


class TestCrawlExhaustion:
    def _make_repo(self) -> InMemoryRepository:
        return InMemoryRepository()

    def test_internal_crawl_exhaustion(self) -> None:
        """After visiting all internal URLs, crawl_status becomes 'exhausted'."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")

        # Visit root, discover one internal link
        state = record_page_visit(
            repo, iid, "https://example.com",
            discovered_links=["/about"],
        )
        assert state.crawl_status == "in_progress"
        assert len(state.unvisited_urls) == 1

        # Visit the only internal link (no new links discovered)
        state = record_page_visit(
            repo, iid, "https://example.com/about",
            discovered_links=["/", "https://external.com/page"],  # / is already visited, external is filtered
        )
        assert state.crawl_status == "exhausted"
        assert state.unvisited_urls == []

    def test_get_next_urls_prioritizes_internal(self) -> None:
        """next_urls returns internal unvisited URLs first."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com",
            discovered_links=["/about", "/work", "/contact"],
        )

        next_urls = get_next_urls_to_crawl(state, batch_size=2)
        assert len(next_urls) == 2
        # All should be internal
        for url in next_urls:
            assert is_same_domain(url, "https://example.com")

    def test_no_duplicate_unvisited(self) -> None:
        """Discovering the same link twice doesn't add duplicates to unvisited."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com",
            discovered_links=["/about", "/about", "/about"],  # duplicate hrefs
        )
        about_url = normalize_url("https://example.com/about")
        about_count = sum(1 for u in state.unvisited_urls if u == about_url)
        assert about_count == 1


# ──────────────────────────────────────────────
# External inspiration transition
# ──────────────────────────────────────────────


class TestExternalInspiration:
    def _make_repo(self) -> InMemoryRepository:
        return InMemoryRepository()

    def test_seed_default_inspiration(self) -> None:
        """After internal exhaustion, seed external inspiration URLs."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com")

        state = seed_external_inspiration(repo, iid)
        assert len(state.external_inspiration_urls) > 0

    def test_seed_custom_inspiration(self) -> None:
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = seed_external_inspiration(
            repo, iid,
            urls=["https://inspiration1.com", "https://inspiration2.com"],
        )
        assert len(state.external_inspiration_urls) == 2

    def test_exhausted_crawl_returns_external_urls(self) -> None:
        """When in inspiration phase with no internal frontier left, next_urls returns external."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com")

        seed_external_inspiration(
            repo, iid,
            urls=["https://awwwards.com", "https://dribbble.com"],
        )
        st = repo.get_crawl_state(iid)
        assert st is not None
        from kmbl_orchestrator.identity.url_normalize import normalize_url as nu

        repo.upsert_crawl_state(
            st.model_copy(
                update={
                    "crawl_phase": "inspiration_expansion",
                    "external_inspiration_urls": [
                        nu("https://awwwards.com"),
                        nu("https://dribbble.com"),
                    ],
                }
            )
        )
        state = repo.get_crawl_state(iid)
        assert state is not None

        next_urls = get_next_urls_to_crawl(state, batch_size=5)
        assert len(next_urls) == 2
        assert any("awwwards" in u for u in next_urls)

    def test_visited_external_not_returned(self) -> None:
        """External URLs that have been visited are excluded from next_urls."""
        repo = self._make_repo()
        iid = uuid4()

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com")

        seed_external_inspiration(
            repo, iid,
            urls=["https://awwwards.com"],
        )
        st = repo.get_crawl_state(iid)
        assert st is not None
        from kmbl_orchestrator.identity.url_normalize import normalize_url as nu

        repo.upsert_crawl_state(
            st.model_copy(
                update={
                    "crawl_phase": "inspiration_expansion",
                    "external_inspiration_urls": [nu("https://awwwards.com")],
                }
            )
        )

        state = record_page_visit(repo, iid, "https://awwwards.com")
        next_urls = get_next_urls_to_crawl(state, batch_size=5)
        assert len(next_urls) == 0  # All exhausted


# ──────────────────────────────────────────────
# Planner crawl context
# ──────────────────────────────────────────────


class TestPlannerCrawlContext:
    def _make_repo(self) -> InMemoryRepository:
        return InMemoryRepository()

    def test_no_crawl_state_returns_unavailable(self) -> None:
        ctx = build_crawl_context_for_planner(None)
        assert ctx["crawl_available"] is False

    def test_context_includes_next_urls(self) -> None:
        repo = self._make_repo()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com",
            summary="Landing page",
            discovered_links=["/about", "/work"],
        )

        ctx = build_crawl_context_for_planner(state)
        assert ctx["crawl_available"] is True
        assert ctx["crawl_status"] == "in_progress"
        assert ctx["total_pages_crawled"] == 1
        assert ctx["visited_count"] == 1
        assert ctx["unvisited_count"] == 2
        assert len(ctx["next_urls_to_crawl"]) == 2
        assert ctx["is_exhausted"] is False

    def test_context_shows_exhaustion(self) -> None:
        repo = self._make_repo()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(repo, iid, "https://example.com")

        ctx = build_crawl_context_for_planner(state)
        assert ctx["is_exhausted"] is True
        assert ctx["crawl_status"] == "exhausted"


# ──────────────────────────────────────────────
# Generator flexibility (expanded output types)
# ──────────────────────────────────────────────


class TestGeneratorFlexibility:
    """Verify that generator can produce WebGL/Three.js/interactive outputs."""

    def test_static_frontend_accepts_js_file(self) -> None:
        from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
            StaticFrontendFileArtifactV1,
        )

        art = StaticFrontendFileArtifactV1.model_validate({
            "role": "static_frontend_file_v1",
            "path": "component/preview/scene.js",
            "content": "import * as THREE from 'three'; const scene = new THREE.Scene();",
        })
        assert art.language == "js"

    def test_static_frontend_accepts_json_file(self) -> None:
        """JSON files are now accepted for 3D model/scene data."""
        from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
            StaticFrontendFileArtifactV1,
        )

        art = StaticFrontendFileArtifactV1.model_validate({
            "role": "static_frontend_file_v1",
            "path": "component/preview/scene-config.json",
            "language": "json",
            "content": '{"camera": {"fov": 75}, "lights": []}',
        })
        assert art.language == "json"

    def test_static_frontend_accepts_glsl_file(self) -> None:
        """GLSL shader files are now accepted."""
        from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
            StaticFrontendFileArtifactV1,
        )

        art = StaticFrontendFileArtifactV1.model_validate({
            "role": "static_frontend_file_v1",
            "path": "component/preview/vertex.glsl",
            "language": "glsl",
            "content": "void main() { gl_Position = vec4(0.0); }",
        })
        assert art.language == "glsl"

    def test_static_frontend_accepts_wgsl_file(self) -> None:
        """WebGPU shader files are now accepted."""
        from kmbl_orchestrator.contracts.static_frontend_artifact_v1 import (
            StaticFrontendFileArtifactV1,
        )

        art = StaticFrontendFileArtifactV1.model_validate({
            "role": "static_frontend_file_v1",
            "path": "component/preview/compute.wgsl",
            "language": "wgsl",
            "content": "@vertex fn main() -> @builtin(position) vec4<f32> { return vec4<f32>(); }",
        })
        assert art.language == "wgsl"

    def test_webgl_experience_mode_clamped_on_static_vertical(self) -> None:
        """Immersive/WebGL experience labels are clamped so OpenClaw static lane does not get webgl_experience surface."""
        from kmbl_orchestrator.runtime.static_vertical_invariants import (
            clamp_experience_mode_for_static_vertical,
        )

        bs = {"type": "static_frontend_file_v1", "experience_mode": "webgl_3d_portfolio"}
        ei = {"constraints": {"canonical_vertical": "static_frontend_file_v1"}}
        fixes = clamp_experience_mode_for_static_vertical(bs, ei)
        assert fixes
        assert bs["experience_mode"] == "flat_editorial_static"

    def test_immersive_mode_clamped_on_static_vertical(self) -> None:
        from kmbl_orchestrator.runtime.static_vertical_invariants import (
            clamp_experience_mode_for_static_vertical,
        )

        bs = {"type": "static_frontend_file_v1", "experience_mode": "immersive_spatial_portfolio"}
        ei = {}
        fixes = clamp_experience_mode_for_static_vertical(bs, ei)
        assert fixes
        assert bs["experience_mode"] == "flat_editorial_static"


# ──────────────────────────────────────────────
# Duplicate detection (evaluator)
# ──────────────────────────────────────────────


class TestDuplicateDetection:
    def test_fingerprint_static_artifacts(self) -> None:
        from kmbl_orchestrator.staging.duplicate_rejection import (
            fingerprint_static_artifacts,
        )

        arts = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html><body>Hello</body></html>",
            }
        ]
        fp = fingerprint_static_artifacts(arts, {})
        assert fp is not None
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex

    def test_same_content_same_fingerprint(self) -> None:
        from kmbl_orchestrator.staging.duplicate_rejection import (
            fingerprint_static_artifacts,
        )

        arts = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html><body>Hello World</body></html>",
            }
        ]
        fp1 = fingerprint_static_artifacts(arts, {})
        fp2 = fingerprint_static_artifacts(arts, {})
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self) -> None:
        from kmbl_orchestrator.staging.duplicate_rejection import (
            fingerprint_static_artifacts,
        )

        arts1 = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html><body>Version 1</body></html>",
            }
        ]
        arts2 = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html><body>Version 2</body></html>",
            }
        ]
        fp1 = fingerprint_static_artifacts(arts1, {})
        fp2 = fingerprint_static_artifacts(arts2, {})
        assert fp1 != fp2

    def test_whitespace_normalized_for_fingerprint(self) -> None:
        from kmbl_orchestrator.staging.duplicate_rejection import (
            fingerprint_static_artifacts,
        )

        arts1 = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html>  <body>  Hello  </body>  </html>",
            }
        ]
        arts2 = [
            {
                "role": "static_frontend_file_v1",
                "path": "component/preview/index.html",
                "language": "html",
                "content": "<html> <body> Hello </body> </html>",
            }
        ]
        fp1 = fingerprint_static_artifacts(arts1, {})
        fp2 = fingerprint_static_artifacts(arts2, {})
        assert fp1 == fp2

    def test_no_static_artifacts_returns_none(self) -> None:
        from kmbl_orchestrator.staging.duplicate_rejection import (
            fingerprint_static_artifacts,
        )

        fp = fingerprint_static_artifacts([{"role": "gallery_image"}], {})
        assert fp is None
