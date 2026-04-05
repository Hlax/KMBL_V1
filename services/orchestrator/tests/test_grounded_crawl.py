"""Tests for grounded crawl system — truth loop fixes.

Tests that the crawl frontier advances based on actual planner behavior,
not blind batch marking. Also tests the lightweight page fetcher and
URL extraction utilities.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from kmbl_orchestrator.domain import AutonomousLoopRecord, BuildSpecRecord
from kmbl_orchestrator.identity.crawl_state import (
    build_crawl_context_for_planner,
    get_or_create_crawl_state,
    record_page_visit,
)
from kmbl_orchestrator.identity.page_fetch import (
    extract_urls_from_build_spec,
    extract_urls_from_text,
    filter_crawl_urls,
    _PageDataExtractor,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository


# ---------------------------------------------------------------------------
# URL extraction from planner output
# ---------------------------------------------------------------------------


class TestExtractUrlsFromText:
    def test_extracts_http_urls(self) -> None:
        text = "Check out https://example.com/about and http://other.com/page for inspiration."
        urls = extract_urls_from_text(text)
        assert "https://example.com/about" in urls
        assert "http://other.com/page" in urls

    def test_extracts_urls_from_json_like_text(self) -> None:
        text = '{"url": "https://example.com/portfolio", "reference": "https://example.com/about"}'
        urls = extract_urls_from_text(text)
        assert "https://example.com/portfolio" in urls
        assert "https://example.com/about" in urls

    def test_deduplicates(self) -> None:
        text = "Visit https://example.com and also https://example.com for design."
        urls = extract_urls_from_text(text)
        assert urls.count("https://example.com") == 1

    def test_empty_input(self) -> None:
        assert extract_urls_from_text("") == []
        assert extract_urls_from_text("no urls here") == []

    def test_non_string_input(self) -> None:
        assert extract_urls_from_text(None) == []  # type: ignore[arg-type]
        assert extract_urls_from_text(42) == []  # type: ignore[arg-type]


class TestExtractUrlsFromBuildSpec:
    def test_extracts_from_nested_dict(self) -> None:
        spec = {
            "title": "Portfolio redesign",
            "reference_sites": ["https://example.com/about"],
            "crawl_targets": {
                "primary": "https://example.com/portfolio",
                "secondary": "https://example.com/contact",
            },
        }
        urls = extract_urls_from_build_spec(spec)
        assert len(urls) == 3
        assert "https://example.com/about" in urls
        assert "https://example.com/portfolio" in urls
        assert "https://example.com/contact" in urls

    def test_empty_spec(self) -> None:
        assert extract_urls_from_build_spec({}) == []

    def test_non_dict_input(self) -> None:
        assert extract_urls_from_build_spec(None) == []  # type: ignore[arg-type]
        assert extract_urls_from_build_spec("text") == []  # type: ignore[arg-type]

    def test_deeply_nested_urls(self) -> None:
        spec = {
            "steps": [
                {"action": "analyze", "url": "https://deep.example.com/page"},
                {"action": "build", "references": ["https://deep.example.com/ref"]},
            ]
        }
        urls = extract_urls_from_build_spec(spec)
        assert "https://deep.example.com/page" in urls
        assert "https://deep.example.com/ref" in urls

    def test_urls_in_description_strings(self) -> None:
        spec = {
            "description": "Inspired by https://example.com/gallery layout and https://other.com/style colors"
        }
        urls = extract_urls_from_build_spec(spec)
        assert "https://example.com/gallery" in urls
        assert "https://other.com/style" in urls


class TestFilterCrawlUrls:
    def test_filters_to_offered_only(self) -> None:
        candidates = [
            "https://example.com/about",
            "https://external.com/random",  # not offered
            "https://example.com/contact",
        ]
        offered = [
            "https://example.com/",
            "https://example.com/about",
            "https://example.com/contact",
            "https://example.com/blog",
        ]
        result = filter_crawl_urls(candidates, offered)
        assert result == ["https://example.com/about", "https://example.com/contact"]

    def test_empty_candidates(self) -> None:
        assert filter_crawl_urls([], ["https://example.com/"]) == []

    def test_no_matches(self) -> None:
        assert filter_crawl_urls(
            ["https://external.com/"],
            ["https://example.com/"],
        ) == []


# ---------------------------------------------------------------------------
# Grounded _advance_crawl_frontier
# ---------------------------------------------------------------------------


def _make_loop(identity_id=None, identity_url="https://example.com") -> AutonomousLoopRecord:
    return AutonomousLoopRecord(
        loop_id=uuid4(),
        identity_id=identity_id or uuid4(),
        identity_url=identity_url,
        status="running",
        phase="graph_cycle",
        iteration_count=1,
        max_iterations=50,
    )


class TestGroundedAdvanceCrawlFrontier:
    """Tests that _advance_crawl_frontier only marks URLs that were actually used."""

    def test_only_referenced_urls_marked_visited(self) -> None:
        """If planner references 1 of 3 offered URLs, only that 1 is marked visited."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        # Seed crawl state with 3 unvisited URLs
        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo, iid, "https://example.com/",
            discovered_links=[
                "https://example.com/about",
                "https://example.com/contact",
                "https://example.com/blog",
            ],
        )
        pre_state = repo.get_crawl_state(iid)
        assert len(pre_state.unvisited_urls) == 3

        # Graph result where planner only referenced /about
        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {
                "title": "Portfolio refresh",
                "reference_url": "https://example.com/about",
            },
        }

        # Mock fetch_page_data to avoid real HTTP
        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post_state = repo.get_crawl_state(iid)
        # Only /about should be marked as visited (not /contact or /blog)
        assert "https://example.com/about" in post_state.visited_urls
        assert "https://example.com/contact" in post_state.unvisited_urls
        assert "https://example.com/blog" in post_state.unvisited_urls

    def test_fallback_marks_first_url_for_forward_progress(self) -> None:
        """If planner references no offered URLs, first offered URL is still marked."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        pre_state = repo.get_crawl_state(iid)
        assert len(pre_state.unvisited_urls) == 1  # root URL

        # Graph result where planner doesn't reference any crawl URLs
        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {
                "title": "Fresh portfolio",
                "steps": ["analyze brand", "design homepage"],
            },
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post_state = repo.get_crawl_state(iid)
        # First offered URL should be marked visited (forward progress)
        assert "https://example.com/" in post_state.visited_urls
        assert post_state.total_pages_crawled == 1

    def test_multiple_referenced_urls_all_marked(self) -> None:
        """All planner-referenced URLs from the offered batch are marked visited."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo, iid, "https://example.com/",
            discovered_links=[
                "https://example.com/about",
                "https://example.com/contact",
            ],
        )

        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {
                "reference_sites": [
                    "https://example.com/about",
                    "https://example.com/contact",
                ],
            },
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post_state = repo.get_crawl_state(iid)
        assert "https://example.com/about" in post_state.visited_urls
        assert "https://example.com/contact" in post_state.visited_urls

    def test_real_page_data_used_when_fetch_succeeds(self) -> None:
        """When page fetch succeeds, real data (title, links, signals) is stored."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")

        fake_page = {
            "url": "https://example.com/",
            "title": "Example Portfolio",
            "description": "A creative portfolio",
            "links": ["https://example.com/projects", "https://example.com/blog"],
            "design_signals": ["minimal", "grid"],
            "tone_keywords": ["creative", "modern"],
            "status_code": 200,
        }

        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {},  # No URL reference — fallback to first
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=fake_page,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post_state = repo.get_crawl_state(iid)
        assert "https://example.com/" in post_state.visited_urls
        # Real page data should be stored
        summary = post_state.page_summaries.get("https://example.com/")
        assert summary is not None
        assert "Example Portfolio" in summary["summary"]
        assert "minimal" in summary["design_signals"]
        assert "creative" in summary["tone_keywords"]
        # Discovered links should be added to unvisited
        assert "https://example.com/projects" in post_state.unvisited_urls
        assert "https://example.com/blog" in post_state.unvisited_urls


# ---------------------------------------------------------------------------
# Page data extractor (HTML parser)
# ---------------------------------------------------------------------------


class TestPageDataExtractor:
    def test_extracts_title(self) -> None:
        html = "<html><head><title>My Portfolio</title></head><body></body></html>"
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert parser.title == "My Portfolio"

    def test_extracts_meta_description(self) -> None:
        html = '<html><head><meta name="description" content="A creative portfolio"></head></html>'
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert parser.description == "A creative portfolio"

    def test_extracts_links(self) -> None:
        html = '<html><body><a href="/about">About</a><a href="https://other.com">External</a></body></html>'
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert "https://example.com/about" in parser.links
        assert "https://other.com" in parser.links

    def test_extracts_design_signals_from_classes(self) -> None:
        html = '<html><body><div class="hero grid dark-mode"><section class="flex card"></section></div></body></html>'
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert "hero" in parser.design_signals
        assert "grid" in parser.design_signals
        assert "dark-mode" in parser.design_signals
        assert "flex" in parser.design_signals
        assert "card" in parser.design_signals

    def test_extracts_framework_signals(self) -> None:
        html = '<html><head><link rel="stylesheet" href="https://cdn.tailwindcss.com"></head></html>'
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert "tailwindcss" in parser.design_signals

    def test_extracts_js_library_signals(self) -> None:
        html = '<html><body><script src="https://cdn.three.js/build/three.min.js"></script></body></html>'
        parser = _PageDataExtractor("https://example.com/")
        parser.feed(html)
        assert "threejs" in parser.design_signals


# ---------------------------------------------------------------------------
# build_crawl_context_for_planner — grounding_available flag
# ---------------------------------------------------------------------------


class TestCrawlContextGroundingFlag:
    def test_grounding_false_without_real_data(self) -> None:
        """No design_signals/tone_keywords → grounding_available=False."""
        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        # Record a visit without real page data
        state = record_page_visit(repo, iid, "https://example.com/", summary="Synthetic summary")

        ctx = build_crawl_context_for_planner(state)
        assert ctx["grounding_available"] is False

    def test_grounding_true_with_design_signals(self) -> None:
        """design_signals present → grounding_available=True."""
        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com/",
            summary="Real page data",
            design_signals=["grid", "minimal"],
        )

        ctx = build_crawl_context_for_planner(state)
        assert ctx["grounding_available"] is True

    def test_grounding_true_with_tone_keywords(self) -> None:
        """tone_keywords present → grounding_available=True."""
        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo, iid, "https://example.com/",
            summary="Real tone data",
            tone_keywords=["creative", "modern"],
        )

        ctx = build_crawl_context_for_planner(state)
        assert ctx["grounding_available"] is True

    def test_no_state_returns_unavailable(self) -> None:
        ctx = build_crawl_context_for_planner(None)
        assert ctx["crawl_available"] is False


# ---------------------------------------------------------------------------
# Truth loop: build_spec passthrough and raw_payload enrichment
# ---------------------------------------------------------------------------


def _make_build_spec_record(
    build_spec_id=None,
    spec_json=None,
    raw_payload_json=None,
) -> BuildSpecRecord:
    """Helper to create a BuildSpecRecord for tests."""
    return BuildSpecRecord(
        build_spec_id=build_spec_id or uuid4(),
        thread_id=uuid4(),
        graph_run_id=uuid4(),
        planner_invocation_id=uuid4(),
        spec_json=spec_json or {},
        raw_payload_json=raw_payload_json,
    )


class TestBuildSpecPassthrough:
    """Tests that build_spec is properly forwarded from graph result to crawl frontier."""

    def test_urls_extracted_from_build_spec_in_graph_result(self) -> None:
        """When graph_result contains build_spec, URLs are extracted and grounded."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo, iid, "https://example.com/",
            discovered_links=[
                "https://example.com/about",
                "https://example.com/work",
            ],
        )

        # Simulate graph result WITH build_spec (the fix)
        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {
                "title": "Portfolio",
                "inspiration": "https://example.com/work",
            },
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post = repo.get_crawl_state(iid)
        # /work was referenced in build_spec → should be visited
        assert "https://example.com/work" in post.visited_urls
        # /about was NOT referenced → should remain unvisited
        assert "https://example.com/about" in post.unvisited_urls

    def test_empty_build_spec_falls_back_to_first_url(self) -> None:
        """When build_spec is empty (old-style result), fallback still works."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")

        # graph_result WITHOUT build_spec (simulates old wrapper behavior)
        graph_result = {
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post = repo.get_crawl_state(iid)
        # Fallback: first offered URL marked visited for forward progress
        assert "https://example.com/" in post.visited_urls


class TestRawPayloadEnrichment:
    """Tests that URLs from BuildSpecRecord.raw_payload_json are also extracted."""

    def test_urls_from_raw_payload_enrich_build_spec_urls(self) -> None:
        """URLs in raw_payload_json (e.g. success_criteria) are used for grounding."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo, iid, "https://example.com/",
            discovered_links=[
                "https://example.com/portfolio",
                "https://example.com/contact",
            ],
        )

        # Create a BuildSpecRecord with URLs in raw_payload_json
        bsid = uuid4()
        bsr = _make_build_spec_record(
            build_spec_id=bsid,
            spec_json={"title": "Portfolio"},
            raw_payload_json={
                "build_spec": {"title": "Portfolio"},
                "success_criteria": [
                    "Match the layout of https://example.com/portfolio",
                ],
                "evaluation_targets": [
                    {"url": "https://example.com/contact", "check": "form"},
                ],
            },
        )
        repo.save_build_spec(bsr)

        # Graph result with build_spec (no URLs) but build_spec_id (has URLs in raw)
        graph_result = {
            "graph_run_id": str(uuid4()),
            "build_spec": {"title": "Portfolio"},  # No URLs here
            "build_spec_id": str(bsid),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        post = repo.get_crawl_state(iid)
        # Both URLs should be visited (found in raw_payload_json)
        assert "https://example.com/portfolio" in post.visited_urls
        assert "https://example.com/contact" in post.visited_urls

    def test_missing_build_spec_id_gracefully_degrades(self) -> None:
        """When build_spec_id is missing, extraction returns empty list."""
        from kmbl_orchestrator.autonomous.loop_service import _extract_raw_payload_urls

        repo = InMemoryRepository()

        result = _extract_raw_payload_urls(repo, {})
        assert result == []

    def test_enrichment_deduplicates_urls(self) -> None:
        """Raw payload extraction returns deduplicated URLs."""
        from kmbl_orchestrator.autonomous.loop_service import _extract_raw_payload_urls

        repo = InMemoryRepository()
        bsid = uuid4()
        bsr = _make_build_spec_record(
            build_spec_id=bsid,
            raw_payload_json={
                "note": "Inspired by https://example.com/about and https://example.com/new",
            },
        )
        repo.save_build_spec(bsr)

        result = _extract_raw_payload_urls(
            repo, {"build_spec_id": str(bsid)},
        )
        assert "https://example.com/about" in result
        assert "https://example.com/new" in result
