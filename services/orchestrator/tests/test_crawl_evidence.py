"""Tests for auditable crawl progression — evidence tiers, provenance, and guards.

Covers:
- Evidence tier priority ordering
- Raw payload over-credit prevention (per-run cap + domain filter)
- Provenance recording in crawl state
- Fallback only when no higher-confidence evidence exists
- Same-domain / allowed-source filtering
- CrawlAdvancementReport serialisation
- Integration with _advance_crawl_frontier (end-to-end)
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from kmbl_orchestrator.domain import (
    AutonomousLoopRecord,
    BuildSpecRecord,
    GraphRunRecord,
)
from kmbl_orchestrator.identity.crawl_evidence import (
    MAX_RAW_PAYLOAD_CREDITS_PER_RUN,
    CrawlAdvancementReport,
    EvidenceTier,
    UrlEvidence,
    cap_urls,
    filter_same_domain_or_allowed,
    resolve_evidence,
)
from kmbl_orchestrator.identity.crawl_state import (
    get_or_create_crawl_state,
    record_page_visit,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.runtime.run_events import RunEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(identity_id=None, loop_id=None):
    return AutonomousLoopRecord(
        loop_id=loop_id or uuid4(),
        identity_id=identity_id or uuid4(),
        identity_url="https://example.com",
        status="running",
        phase="graph_cycle",
        iteration_count=1,
        max_iterations=50,
    )


def _make_build_spec_record(*, build_spec_id=None, raw_payload_json=None, **kw):
    return BuildSpecRecord(
        build_spec_id=build_spec_id or uuid4(),
        thread_id=kw.get("thread_id", uuid4()),
        graph_run_id=kw.get("graph_run_id", uuid4()),
        planner_invocation_id=kw.get("planner_invocation_id", uuid4()),
        spec_json=kw.get("spec_json", {}),
        raw_payload_json=raw_payload_json,
    )


# ---------------------------------------------------------------------------
# EvidenceTier basics
# ---------------------------------------------------------------------------


class TestEvidenceTier:
    def test_verified_is_strongest(self) -> None:
        assert EvidenceTier.VERIFIED_FETCH < EvidenceTier.SELECTED_BY_PLANNER
        assert EvidenceTier.SELECTED_BY_PLANNER < EvidenceTier.BUILD_SPEC_STRUCTURED
        assert EvidenceTier.BUILD_SPEC_STRUCTURED < EvidenceTier.RAW_PAYLOAD_TEXT
        assert EvidenceTier.RAW_PAYLOAD_TEXT < EvidenceTier.FRONTIER_FALLBACK

    def test_labels(self) -> None:
        assert EvidenceTier.label(1) == "verified_fetch"
        assert EvidenceTier.label(5) == "frontier_fallback"
        assert "unknown" in EvidenceTier.label(99)


# ---------------------------------------------------------------------------
# resolve_evidence — priority ordering
# ---------------------------------------------------------------------------


class TestResolveEvidence:
    """Tests that resolve_evidence picks the highest-confidence evidence."""

    def test_build_spec_beats_raw_payload(self) -> None:
        """build_spec_structured (tier 3) wins over raw_payload_text (tier 4)."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b"],
            build_spec_urls=["https://example.com/a"],
            raw_payload_urls=["https://example.com/b"],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "build_spec_structured"
        assert len(report.final_visited) == 1
        assert report.final_visited[0].url == "https://example.com/a"

    def test_raw_payload_used_when_no_build_spec_match(self) -> None:
        """raw_payload_text used when build_spec doesn't match any offered URL."""
        report = resolve_evidence(
            offered_urls=["https://example.com/page1"],
            build_spec_urls=["https://other.com/unrelated"],
            raw_payload_urls=["https://example.com/page1"],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "raw_payload_text"
        assert report.final_visited[0].url == "https://example.com/page1"

    def test_fallback_when_no_evidence(self) -> None:
        """frontier_fallback used when neither source matches."""
        report = resolve_evidence(
            offered_urls=["https://example.com/x", "https://example.com/y"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "frontier_fallback"
        assert len(report.final_visited) == 1
        assert report.final_visited[0].url == "https://example.com/x"

    def test_fallback_when_all_filtered_out(self) -> None:
        """Fallback when raw_payload URLs exist but are filtered by domain."""
        report = resolve_evidence(
            offered_urls=["https://example.com/page"],
            build_spec_urls=[],
            raw_payload_urls=["https://evil.com/page"],  # wrong domain
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "frontier_fallback"

    def test_empty_offered_returns_empty(self) -> None:
        report = resolve_evidence(
            offered_urls=[],
            build_spec_urls=["https://example.com/a"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.final_visited == []
        assert report.evidence_tier_used == ""

    def test_multiple_build_spec_urls_all_kept(self) -> None:
        """All matching build_spec URLs are marked (not just the first)."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            build_spec_urls=["https://example.com/a", "https://example.com/b"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert len(report.final_visited) == 2
        visited_urls = {e.url for e in report.final_visited}
        assert visited_urls == {"https://example.com/a", "https://example.com/b"}


# ---------------------------------------------------------------------------
# Same-domain / allowed-source filtering
# ---------------------------------------------------------------------------


class TestDomainFiltering:
    def test_same_domain_kept(self) -> None:
        kept, dropped = filter_same_domain_or_allowed(
            ["https://example.com/a", "https://example.com/b"],
            "https://example.com",
        )
        assert len(kept) == 2
        assert dropped == 0

    def test_different_domain_dropped(self) -> None:
        kept, dropped = filter_same_domain_or_allowed(
            ["https://example.com/a", "https://evil.com/x"],
            "https://example.com",
        )
        assert kept == ["https://example.com/a"]
        assert dropped == 1

    def test_allowed_domain_kept(self) -> None:
        kept, dropped = filter_same_domain_or_allowed(
            ["https://example.com/a", "https://trusted.com/x"],
            "https://example.com",
            allowed_domains={"trusted.com"},
        )
        assert len(kept) == 2
        assert dropped == 0

    def test_www_prefix_stripped(self) -> None:
        """www.example.com and example.com are treated as same domain."""
        kept, dropped = filter_same_domain_or_allowed(
            ["https://www.example.com/page"],
            "https://example.com",
        )
        assert len(kept) == 1
        assert dropped == 0

    def test_duplicates_dropped(self) -> None:
        kept, dropped = filter_same_domain_or_allowed(
            ["https://example.com/a", "https://example.com/a"],
            "https://example.com",
        )
        assert len(kept) == 1
        assert dropped == 1


# ---------------------------------------------------------------------------
# Over-credit prevention (cap)
# ---------------------------------------------------------------------------


class TestOverCreditPrevention:
    def test_cap_enforced(self) -> None:
        urls = [f"https://example.com/page{i}" for i in range(10)]
        capped, excess = cap_urls(urls, MAX_RAW_PAYLOAD_CREDITS_PER_RUN)
        assert len(capped) == MAX_RAW_PAYLOAD_CREDITS_PER_RUN
        assert excess == 10 - MAX_RAW_PAYLOAD_CREDITS_PER_RUN

    def test_under_cap_no_trim(self) -> None:
        urls = ["https://example.com/a"]
        capped, excess = cap_urls(urls, MAX_RAW_PAYLOAD_CREDITS_PER_RUN)
        assert capped == urls
        assert excess == 0

    def test_raw_payload_capped_in_resolve(self) -> None:
        """resolve_evidence caps raw_payload URLs per run."""
        offered = [f"https://example.com/p{i}" for i in range(10)]
        raw_payload = list(offered)  # all match

        report = resolve_evidence(
            offered_urls=offered,
            build_spec_urls=[],
            raw_payload_urls=raw_payload,
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "raw_payload_text"
        assert len(report.final_visited) == MAX_RAW_PAYLOAD_CREDITS_PER_RUN
        assert report.capped_count == 10 - MAX_RAW_PAYLOAD_CREDITS_PER_RUN

    def test_raw_payload_domain_filtered_then_capped(self) -> None:
        """Domain filter runs before cap, so cross-domain URLs don't consume cap budget."""
        offered = [
            "https://example.com/a",
            "https://evil.com/b",
            "https://example.com/c",
            "https://example.com/d",
            "https://example.com/e",
        ]
        raw_payload = list(offered)

        report = resolve_evidence(
            offered_urls=offered,
            build_spec_urls=[],
            raw_payload_urls=raw_payload,
            root_url="https://example.com",
        )
        # evil.com/b filtered, then 4 same-domain URLs capped to MAX
        assert report.domain_filtered_count == 1
        final_urls = {e.url for e in report.final_visited}
        assert "https://evil.com/b" not in final_urls


# ---------------------------------------------------------------------------
# Provenance recording
# ---------------------------------------------------------------------------


class TestProvenanceRecording:
    def test_provenance_stored_on_visit(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")

        state = record_page_visit(
            repo,
            iid,
            "https://example.com",
            summary="Test page",
            provenance_source="build_spec_structured",
            provenance_tier=EvidenceTier.BUILD_SPEC_STRUCTURED,
            run_id="run-123",
        )
        # URL is normalized (trailing slash added for root)
        norm_url = "https://example.com/"
        assert norm_url in state.visit_provenance
        prov = state.visit_provenance[norm_url]
        assert prov["source"] == "build_spec_structured"
        assert prov["tier"] == 3
        assert prov["run_id"] == "run-123"
        assert "recorded_at" in prov

    def test_provenance_empty_when_not_provided(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")

        state = record_page_visit(
            repo, iid, "https://example.com", summary="No provenance",
        )
        # No provenance recorded when source not given
        assert state.visit_provenance == {}

    def test_provenance_persists_across_visits(self) -> None:
        repo = InMemoryRepository()
        iid = uuid4()
        get_or_create_crawl_state(repo, iid, "https://example.com")

        record_page_visit(
            repo, iid, "https://example.com/a",
            provenance_source="build_spec_structured",
            provenance_tier=3,
            run_id="run-1",
        )
        state = record_page_visit(
            repo, iid, "https://example.com/b",
            provenance_source="frontier_fallback",
            provenance_tier=5,
            run_id="run-2",
        )
        # Both provenance entries exist
        assert len(state.visit_provenance) == 2


# ---------------------------------------------------------------------------
# CrawlAdvancementReport
# ---------------------------------------------------------------------------


class TestCrawlAdvancementReport:
    def test_to_dict_roundtrip(self) -> None:
        report = CrawlAdvancementReport(
            offered_urls=["https://a.com"],
            mentioned_urls=["https://a.com"],
            final_visited=[
                UrlEvidence("https://a.com", EvidenceTier.BUILD_SPEC_STRUCTURED, "build_spec_structured"),
            ],
            evidence_tier_used="build_spec_structured",
        )
        d = report.to_dict()
        assert d["offered_urls"] == ["https://a.com"]
        assert d["evidence_tier_used"] == "build_spec_structured"
        assert d["final_visited"][0]["tier"] == 3
        assert d["final_visited"][0]["source"] == "build_spec_structured"


# ---------------------------------------------------------------------------
# CRAWL_FRONTIER_ADVANCED event type
# ---------------------------------------------------------------------------


class TestCrawlFrontierEvent:
    def test_event_type_exists(self) -> None:
        assert RunEventType.CRAWL_FRONTIER_ADVANCED == "crawl_frontier_advanced"


# ---------------------------------------------------------------------------
# Integration: _advance_crawl_frontier with evidence tiers
# ---------------------------------------------------------------------------


class TestAdvanceCrawlFrontierEvidence:
    """End-to-end tests proving _advance_crawl_frontier uses tiered evidence."""

    def _setup(self):
        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        # Seed unvisited URLs
        updated = state.model_copy(
            update={
                "unvisited_urls": [
                    "https://example.com/a",
                    "https://example.com/b",
                    "https://example.com/c",
                ],
            },
        )
        repo.upsert_crawl_state(updated)
        return repo, iid, loop

    def test_build_spec_url_gets_structured_provenance(self) -> None:
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo, iid, loop = self._setup()
        graph_result = {
            "build_spec": {"inspiration": "See https://example.com/b for design"},
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        assert "https://example.com/b" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/b", {})
        assert prov.get("source") == "build_spec_structured"

    def test_fallback_gets_frontier_provenance(self) -> None:
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo, iid, loop = self._setup()
        graph_result = {
            "build_spec": {"note": "No URLs here"},
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        # First offered URL should be visited as fallback
        assert "https://example.com/a" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/a", {})
        assert prov.get("source") == "frontier_fallback"

    def test_raw_payload_same_domain_only(self) -> None:
        """Raw payload URLs from a different domain are NOT credited."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo, iid, loop = self._setup()

        # Add a cross-domain URL to unvisited (simulating weird frontier state)
        state = repo.get_crawl_state(iid)
        updated = state.model_copy(
            update={
                "unvisited_urls": [
                    "https://example.com/a",
                    "https://evil.com/phish",
                ],
            },
        )
        repo.upsert_crawl_state(updated)

        bsid = uuid4()
        bsr = _make_build_spec_record(
            build_spec_id=bsid,
            raw_payload_json={
                "reasoning": "Inspired by https://evil.com/phish and https://example.com/a",
            },
        )
        repo.save_build_spec(bsr)

        graph_result = {
            "build_spec": {},
            "build_spec_id": str(bsid),
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        # example.com/a should be visited via raw_payload_text
        assert "https://example.com/a" in state.visited_urls
        prov_a = state.visit_provenance.get("https://example.com/a", {})
        assert prov_a.get("source") == "raw_payload_text"

    def test_emits_crawl_frontier_event(self) -> None:
        """CRAWL_FRONTIER_ADVANCED event is emitted with full report."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo, iid, loop = self._setup()
        grun_id = uuid4()
        graph_result = {
            "build_spec": {"ref": "https://example.com/a"},
            "graph_run_id": grun_id,
        }

        # Need a graph run record for the event to attach to
        repo.save_graph_run(GraphRunRecord(
            graph_run_id=grun_id,
            thread_id=uuid4(),
            identity_id=iid,
            trigger_type="autonomous_loop",
            status="completed",
        ))

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        # Check that event was emitted
        events = repo.list_graph_run_events(grun_id)
        crawl_events = [
            e for e in events
            if e.event_type == RunEventType.CRAWL_FRONTIER_ADVANCED
        ]
        assert len(crawl_events) == 1
        payload = crawl_events[0].payload_json
        assert "evidence_tier_used" in payload
        assert "offered_urls" in payload
        assert "final_visited" in payload

    def test_raw_payload_capped_in_integration(self) -> None:
        """Integration: raw payload URLs capped at MAX_RAW_PAYLOAD_CREDITS_PER_RUN."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        get_or_create_crawl_state(repo, iid, "https://example.com")

        # Set up many unvisited same-domain URLs
        many_urls = [f"https://example.com/page{i}" for i in range(10)]
        state = repo.get_crawl_state(iid)
        updated = state.model_copy(update={"unvisited_urls": many_urls})
        repo.upsert_crawl_state(updated)

        bsid = uuid4()
        # Raw payload references all of them
        bsr = _make_build_spec_record(
            build_spec_id=bsid,
            raw_payload_json={
                "reasoning": " ".join(many_urls),
            },
        )
        repo.save_build_spec(bsr)

        graph_result = {
            "build_spec": {},  # no structured match
            "build_spec_id": str(bsid),
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.autonomous.loop_service._try_fetch_page",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        # Should visit at most MAX_RAW_PAYLOAD_CREDITS_PER_RUN URLs
        newly_visited = [u for u in state.visited_urls if u in many_urls]
        assert len(newly_visited) <= MAX_RAW_PAYLOAD_CREDITS_PER_RUN
