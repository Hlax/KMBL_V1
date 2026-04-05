"""Tests for Playwright wrapper integration, guardrails, and page_visit_log."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from kmbl_orchestrator.domain import AutonomousLoopRecord, CrawlStateRecord, PageVisitLogRecord
from kmbl_orchestrator.identity.crawl_evidence import (
    EvidenceTier,
    match_planner_selections_to_offered,
)
from kmbl_orchestrator.identity.crawl_state import get_or_create_crawl_state, record_page_visit
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def _make_loop(identity_id, **kwargs) -> AutonomousLoopRecord:
    return AutonomousLoopRecord(
        loop_id=uuid4(),
        identity_id=identity_id,
        identity_url="https://example.com",
        status="running",
        phase="graph_cycle",
        iteration_count=1,
        max_iterations=50,
        **kwargs,
    )


class TestMatchPlannerSelections:
    def test_intersection_returns_offered_form(self) -> None:
        offered = [
            "https://example.com/about",
            "https://example.com/contact",
        ]
        planner = ["https://example.com/about/"]
        m = match_planner_selections_to_offered(planner, offered)
        assert m == ["https://example.com/about"]


class TestGuardrails:
    def test_portfolio_blocks_cross_domain(self) -> None:
        from kmbl_orchestrator.browser.crawl_guardrails import url_passes_grounded_visit
        from kmbl_orchestrator.config import Settings
        from kmbl_orchestrator.identity.crawl_state import get_or_create_crawl_state

        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        settings = Settings()
        ok, reason = url_passes_grounded_visit(
            state,
            "https://evil.com/x",
            source_kind="portfolio_internal",
            settings=settings,
        )
        assert ok is False
        assert "not_same_domain" in reason

    def test_inspiration_requires_allowlist(self) -> None:
        from kmbl_orchestrator.browser.crawl_guardrails import url_passes_grounded_visit
        from kmbl_orchestrator.config import Settings
        from kmbl_orchestrator.identity.crawl_state import get_or_create_crawl_state

        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        settings = Settings()
        ok, _ = url_passes_grounded_visit(
            state,
            "https://www.awwwards.com/",
            source_kind="inspiration_external",
            settings=settings,
        )
        assert ok is True


class TestWrapperContract:
    def test_wrapper_payload_to_fetch_parts(self) -> None:
        from kmbl_orchestrator.browser.playwright_client import wrapper_payload_to_fetch_parts

        data = {
            "requested_url": "https://example.com/a",
            "resolved_url": "https://example.com/a",
            "status": "ok",
            "page_title": "T",
            "meta_description": "D",
            "summary": "S",
            "discovered_links": ["https://example.com/b"],
            "traits": {"design_signals": ["grid"], "tone_keywords": ["minimal"]},
            "http_status": 200,
            "timing_ms": 12,
        }
        ok, parts = wrapper_payload_to_fetch_parts(data)
        assert ok is True
        assert parts["summary"] == "S"
        assert "grid" in parts["design_signals"]


class TestPageVisitLogPersistence:
    def test_append_page_visit_log_roundtrip(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        vid = repo.append_page_visit_log(
            PageVisitLogRecord(
                identity_id=iid,
                requested_url="https://example.com/",
                status="ok",
                evidence_source="playwright_wrapper",
            )
        )
        assert vid is not None
        assert len(repo._page_visit_logs) == 1


class TestAdvanceCrawlFrontierPlaywright:
    def test_playwright_success_records_visit_and_log(self) -> None:
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        gid = uuid4()
        tid = uuid4()
        loop = _make_loop(identity_id=iid, current_thread_id=tid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo,
            iid,
            "https://example.com/",
            discovered_links=["https://example.com/about"],
        )

        graph_result = {
            "graph_run_id": str(gid),
            "thread_id": str(tid),
            "build_spec": {
                "selected_urls": ["https://example.com/about"],
            },
        }

        fake_settings = MagicMock()
        fake_settings.kmbl_playwright_wrapper_url = "http://127.0.0.1:3847"
        fake_settings.kmbl_playwright_max_pages_per_loop = 3
        fake_settings.kmbl_playwright_inspiration_domains = (
            "www.awwwards.com,www.siteinspire.com,dribbble.com"
        )
        fake_settings.kmbl_playwright_http_timeout_sec = 45.0

        wrapper = {
            "requested_url": "https://example.com/about",
            "resolved_url": "https://example.com/about",
            "status": "ok",
            "http_status": 200,
            "page_title": "About",
            "meta_description": "desc",
            "summary": "About page",
            "discovered_links": ["https://example.com/contact"],
            "same_domain_links": ["https://example.com/contact"],
            "traits": {"design_signals": ["grid"], "tone_keywords": []},
            "timing_ms": 10,
        }

        with patch("kmbl_orchestrator.autonomous.loop_service.get_settings", return_value=fake_settings):
            with patch(
                "kmbl_orchestrator.browser.playwright_client.visit_page_via_wrapper",
                return_value=wrapper,
            ):
                _advance_crawl_frontier(repo, loop, graph_result)

        post = repo.get_crawl_state(iid)
        assert "https://example.com/about" in post.visited_urls
        prov = post.visit_provenance.get("https://example.com/about")
        assert prov is not None
        assert prov.get("source") == "playwright_wrapper"
        assert prov.get("tier") == EvidenceTier.VERIFIED_FETCH
        assert len(repo._page_visit_logs) == 1
        assert repo._page_visit_logs[0].status == "ok"

    def test_playwright_blocked_skips_visit(self) -> None:
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        gid = uuid4()
        tid = uuid4()
        loop = _make_loop(identity_id=iid, current_thread_id=tid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com/")
        evil = "https://evil.com/nope"
        st = repo.get_crawl_state(iid)
        assert st is not None
        repo.upsert_crawl_state(
            st.model_copy(
                update={
                    "crawl_phase": "inspiration_expansion",
                    "external_inspiration_urls": [evil],
                    "unvisited_urls": [],
                }
            )
        )

        graph_result = {
            "graph_run_id": str(gid),
            "thread_id": str(tid),
            "build_spec": {"selected_urls": [evil]},
        }

        fake_settings = MagicMock()
        fake_settings.kmbl_playwright_wrapper_url = "http://127.0.0.1:3847"
        fake_settings.kmbl_playwright_max_pages_per_loop = 3
        fake_settings.kmbl_playwright_inspiration_domains = "dribbble.com"
        fake_settings.kmbl_playwright_http_timeout_sec = 45.0

        with patch("kmbl_orchestrator.autonomous.loop_service.get_settings", return_value=fake_settings):
            with patch(
                "kmbl_orchestrator.browser.playwright_client.visit_page_via_wrapper",
                return_value={},
            ) as mock_visit:
                _advance_crawl_frontier(repo, loop, graph_result)
                mock_visit.assert_not_called()

        post = repo.get_crawl_state(iid)
        assert "https://evil.com/nope" not in post.visited_urls
        assert len(repo._page_visit_logs) == 1
        assert repo._page_visit_logs[0].status == "blocked"

    def test_bounded_batch_respects_max_pages(self) -> None:
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        gid = uuid4()
        tid = uuid4()
        loop = _make_loop(identity_id=iid, current_thread_id=tid)

        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(
            repo,
            iid,
            "https://example.com/",
            discovered_links=[
                "https://example.com/p1",
                "https://example.com/p2",
                "https://example.com/p3",
                "https://example.com/p4",
            ],
        )

        graph_result = {
            "graph_run_id": str(gid),
            "thread_id": str(tid),
            "build_spec": {
                "selected_urls": [
                    "https://example.com/p1",
                    "https://example.com/p2",
                    "https://example.com/p3",
                    "https://example.com/p4",
                ],
            },
        }

        fake_settings = MagicMock()
        fake_settings.kmbl_playwright_wrapper_url = "http://127.0.0.1:3847"
        fake_settings.kmbl_playwright_max_pages_per_loop = 2
        fake_settings.kmbl_playwright_inspiration_domains = "dribbble.com"
        fake_settings.kmbl_playwright_http_timeout_sec = 45.0

        wrapper = {
            "requested_url": "x",
            "resolved_url": "x",
            "status": "ok",
            "summary": "s",
            "discovered_links": [],
            "same_domain_links": [],
            "traits": {},
            "timing_ms": 1,
        }

        with patch("kmbl_orchestrator.autonomous.loop_service.get_settings", return_value=fake_settings):
            with patch(
                "kmbl_orchestrator.browser.playwright_client.visit_page_via_wrapper",
                return_value=wrapper,
            ) as mock_visit:
                _advance_crawl_frontier(repo, loop, graph_result)
                assert mock_visit.call_count == 2


class TestVisitPageClient:
    def test_missing_base_returns_error_dict(self) -> None:
        from kmbl_orchestrator.browser.playwright_client import visit_page_via_wrapper

        with patch("kmbl_orchestrator.browser.playwright_client.get_settings") as gs:
            m = MagicMock()
            m.kmbl_playwright_wrapper_url = ""
            m.kmbl_playwright_http_timeout_sec = 10.0
            gs.return_value = m
            out = visit_page_via_wrapper({"url": "https://example.com"})
            assert out["status"] == "error"
            assert "not configured" in (out.get("error") or "")
