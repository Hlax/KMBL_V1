"""Crawl URL policy, planner memory shaping, and visit-log pruning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from kmbl_orchestrator.domain import PageVisitLogRecord
from kmbl_orchestrator.identity.crawl_state import (
    build_crawl_context_for_planner,
    get_or_create_crawl_state,
    record_page_visit,
)
from kmbl_orchestrator.identity.crawl_url_policy import (
    filter_frontier_candidate_urls,
    is_low_value_crawl_url,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository


class TestCrawlUrlPolicy:
    def test_blocks_social_hosts(self) -> None:
        assert is_low_value_crawl_url("https://www.linkedin.com/in/foo") is True
        assert is_low_value_crawl_url("https://twitter.com/x/status/1") is True

    def test_blocks_auth_and_legal_paths(self) -> None:
        assert is_low_value_crawl_url("https://example.com/login") is True
        assert is_low_value_crawl_url("https://example.com/legal/privacy-policy") is True

    def test_allows_typical_site_pages(self) -> None:
        assert is_low_value_crawl_url("https://example.com/work/project") is False
        assert is_low_value_crawl_url("https://example.com/about") is False

    def test_filter_frontier_keeps_internal_good_links(self) -> None:
        root = "https://example.com/"
        out = filter_frontier_candidate_urls(
            [
                "https://example.com/about",
                "https://example.com/login",
                "https://linkedin.com/in/x",
            ],
            root_url=root,
        )
        assert out == ["https://example.com/about"]


class TestFrontierEnqueueFiltered:
    def test_privacy_not_added_to_unvisited(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")
        state = record_page_visit(
            repo,
            iid,
            "https://example.com/",
            discovered_links=[
                "https://example.com/about",
                "https://example.com/privacy",
            ],
        )
        assert "https://example.com/about" in state.unvisited_urls
        assert "https://example.com/privacy" not in state.unvisited_urls


class TestPlannerCrawlContextShaping:
    def test_portfolio_vs_inspiration_split(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com/", summary="home")
        record_page_visit(
            repo,
            iid,
            "https://www.awwwards.com/x",
            summary="offsite",
        )
        state = repo.get_crawl_state(iid)
        assert state is not None
        ctx = build_crawl_context_for_planner(state)
        ports = ctx.get("recent_portfolio_summaries") or []
        insp = ctx.get("recent_inspiration_summaries") or []
        assert any("example.com" in (x.get("url") or "") for x in ports)
        assert any("awwwards.com" in (x.get("url") or "") for x in insp)
        for x in ports + insp:
            assert x.get("origin") in ("portfolio", "inspiration")
        assert ctx.get("resume", {}).get("has_prior_crawl_memory") is True
        assert "operational visit logs" in (ctx.get("memory_contract") or "")

    def test_combined_recent_is_capped(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")
        record_page_visit(repo, iid, "https://example.com/", summary="a")
        state = record_page_visit(repo, iid, "https://example.com/about", summary="b")
        ctx = build_crawl_context_for_planner(state)
        assert len(ctx.get("recent_page_summaries") or []) <= 5


class TestPageVisitLogPrune:
    def test_in_memory_prune_drops_old_rows(self) -> None:
        repo = InMemoryRepository()
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        repo.append_page_visit_log(
            PageVisitLogRecord(
                identity_id=uuid4(),
                requested_url="https://example.com/",
                status="ok",
                created_at=old,
            )
        )
        repo.append_page_visit_log(
            PageVisitLogRecord(
                identity_id=uuid4(),
                requested_url="https://example.com/about",
                status="ok",
            )
        )
        n = repo.prune_page_visit_logs_older_than(older_than_days=30)
        assert n >= 1
        assert len(repo._page_visit_logs) == 1
