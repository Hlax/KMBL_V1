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
        assert EvidenceTier.label(6) == "frontier_fallback"
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
        assert prov["tier"] == EvidenceTier.BUILD_SPEC_STRUCTURED
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
            provenance_tier=EvidenceTier.BUILD_SPEC_STRUCTURED,
            run_id="run-1",
        )
        state = record_page_visit(
            repo, iid, "https://example.com/b",
            provenance_source="frontier_fallback",
            provenance_tier=EvidenceTier.FRONTIER_FALLBACK,
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
        assert d["final_visited"][0]["tier"] == EvidenceTier.BUILD_SPEC_STRUCTURED
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
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
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
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
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
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
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
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
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
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        # Should visit at most MAX_RAW_PAYLOAD_CREDITS_PER_RUN URLs
        newly_visited = [u for u in state.visited_urls if u in many_urls]
        assert len(newly_visited) <= MAX_RAW_PAYLOAD_CREDITS_PER_RUN


# ---------------------------------------------------------------------------
# FIX 1: selected_by_planner — real tier-2 evidence
# ---------------------------------------------------------------------------


class TestPlannerSelectedUrls:
    """Tests that explicit planner-selected URLs (tier 2) work as real evidence."""

    def test_extract_from_top_level_selected_urls(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["https://example.com/about", "https://example.com/work"]}
        urls = extract_planner_selected_urls(bs)
        assert urls == ["https://example.com/about", "https://example.com/work"]

    def test_extract_from_crawl_actions_nested(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"crawl_actions": {"selected_urls": ["https://example.com/x"]}}
        urls = extract_planner_selected_urls(bs)
        assert urls == ["https://example.com/x"]

    def test_deduplicates_across_locations(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {
            "selected_urls": ["https://example.com/a"],
            "crawl_actions": {"selected_urls": ["https://example.com/a", "https://example.com/b"]},
        }
        urls = extract_planner_selected_urls(bs)
        assert urls.count("https://example.com/a") == 1
        assert "https://example.com/b" in urls

    def test_ignores_non_http(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["not-a-url", "ftp://bad.com", "https://good.com/y"]}
        urls = extract_planner_selected_urls(bs)
        assert urls == ["https://good.com/y"]

    def test_empty_when_absent(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        assert extract_planner_selected_urls({}) == []
        assert extract_planner_selected_urls({"other": "stuff"}) == []

    def test_selected_beats_build_spec_structured(self) -> None:
        """selected_by_planner (tier 2) outranks build_spec_structured (tier 3)."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b"],
            planner_selected_urls=["https://example.com/a"],
            build_spec_urls=["https://example.com/b"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"
        assert len(report.final_visited) == 1
        assert report.final_visited[0].url == "https://example.com/a"
        assert report.final_visited[0].tier == EvidenceTier.SELECTED_BY_PLANNER

    def test_selected_beats_raw_payload(self) -> None:
        """selected_by_planner (tier 2) outranks raw_payload_text (tier 4)."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b"],
            planner_selected_urls=["https://example.com/a"],
            session_selected_urls=["https://example.com/b"],
            build_spec_urls=[],
            raw_payload_urls=["https://example.com/b"],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"

    def test_session_selected_beats_build_spec_when_planner_omitted(self) -> None:
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b"],
            planner_selected_urls=[],
            session_selected_urls=["https://example.com/b"],
            build_spec_urls=["https://example.com/a"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_session_output"
        assert report.final_visited[0].url == "https://example.com/b"

    def test_fallback_not_fired_when_selected_exists(self) -> None:
        """When planner selects URLs, fallback is NOT used."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a", "https://example.com/b"],
            planner_selected_urls=["https://example.com/b"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"
        assert report.final_visited[0].url == "https://example.com/b"

    def test_selected_only_if_in_offered(self) -> None:
        """Planner-selected URLs must also be in the offered set."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a"],
            planner_selected_urls=["https://example.com/NOT_OFFERED"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        # Should fall through to fallback
        assert report.evidence_tier_used == "frontier_fallback"

    def test_planner_selected_urls_in_report(self) -> None:
        """Report captures planner_selected_urls for observability."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a"],
            planner_selected_urls=["https://example.com/a"],
            session_selected_urls=[],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.planner_selected_urls == ["https://example.com/a"]
        d = report.to_dict()
        assert d["planner_selected_urls"] == ["https://example.com/a"]

    def test_session_selected_urls_in_report(self) -> None:
        report = resolve_evidence(
            offered_urls=["https://example.com/a"],
            planner_selected_urls=[],
            session_selected_urls=["https://example.com/a"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.session_selected_urls == ["https://example.com/a"]
        d = report.to_dict()
        assert d["session_selected_urls"] == ["https://example.com/a"]

    def test_integration_selected_by_planner_provenance(self) -> None:
        """End-to-end: planner selected_urls get tier-2 provenance."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/a", "https://example.com/b"]},
        )
        repo.upsert_crawl_state(updated)

        graph_result = {
            "build_spec": {
                "selected_urls": ["https://example.com/b"],
                "note": "chose /b explicitly",
            },
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        assert "https://example.com/b" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/b", {})
        assert prov.get("source") == "selected_by_planner"
        assert prov.get("tier") == EvidenceTier.SELECTED_BY_PLANNER


# ---------------------------------------------------------------------------
# FIX 2: verified_fetch — real tier-1 evidence
# ---------------------------------------------------------------------------


class TestVerifiedFetch:
    """Tests that real HTTP fetch upgrades evidence to verified_fetch (tier 1)."""

    def test_verify_url_fetch_success(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import verify_url_fetch

        fake_page = {
            "url": "https://example.com/about",
            "title": "About Us",
            "description": "Our story",
            "links": ["https://example.com/team"],
            "design_signals": ["minimal"],
            "tone_keywords": ["professional"],
            "status_code": 200,
        }
        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=fake_page,
        ):
            vf = verify_url_fetch("https://example.com/about")

        assert vf.success is True
        assert vf.title == "About Us"
        assert vf.description == "Our story"
        assert vf.resolved_url == "https://example.com/about"
        assert vf.discovered_links == ["https://example.com/team"]

    def test_verify_url_fetch_failure_returns_false(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import verify_url_fetch

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            vf = verify_url_fetch("https://example.com/bad")

        assert vf.success is False
        assert vf.failure_reason != ""

    def test_verify_url_fetch_exception_returns_false(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import verify_url_fetch

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            side_effect=RuntimeError("network down"),
        ):
            vf = verify_url_fetch("https://example.com/err")

        assert vf.success is False
        assert "network down" in vf.failure_reason

    def test_try_upgrade_success_promotes_to_tier_1(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import try_upgrade_to_verified

        ev = UrlEvidence("https://example.com/x", EvidenceTier.BUILD_SPEC_STRUCTURED, "build_spec_structured")
        report = CrawlAdvancementReport()

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value={"url": "https://example.com/x", "title": "X", "description": "", "links": [], "design_signals": [], "tone_keywords": [], "status_code": 200},
        ):
            upgraded, vf = try_upgrade_to_verified(ev, report)

        assert upgraded.tier == EvidenceTier.VERIFIED_FETCH
        assert upgraded.source == "verified_fetch"
        assert vf.success is True
        assert "https://example.com/x" in report.verified_urls
        assert len(report.downgraded_urls) == 0

    def test_try_upgrade_failure_keeps_original_tier(self) -> None:
        from kmbl_orchestrator.identity.crawl_evidence import try_upgrade_to_verified

        ev = UrlEvidence("https://example.com/y", EvidenceTier.SELECTED_BY_PLANNER, "selected_by_planner")
        report = CrawlAdvancementReport()

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            kept, vf = try_upgrade_to_verified(ev, report)

        # Original tier preserved
        assert kept.tier == EvidenceTier.SELECTED_BY_PLANNER
        assert kept.source == "selected_by_planner"
        assert vf.success is False
        assert len(report.downgraded_urls) == 1
        assert report.downgraded_urls[0]["url"] == "https://example.com/y"
        assert report.downgraded_urls[0]["kept_tier"] == "selected_by_planner"
        assert len(report.fetch_failures) == 1

    def test_integration_verified_fetch_provenance(self) -> None:
        """End-to-end: successful fetch upgrades to verified_fetch provenance."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/a"]},
        )
        repo.upsert_crawl_state(updated)

        fake_page = {
            "url": "https://example.com/a",
            "title": "Page A",
            "description": "Desc A",
            "links": [],
            "design_signals": ["grid"],
            "tone_keywords": ["modern"],
            "status_code": 200,
        }

        graph_result = {
            "build_spec": {"selected_urls": ["https://example.com/a"]},
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=fake_page,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        assert "https://example.com/a" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/a", {})
        assert prov.get("source") == "verified_fetch"
        assert prov.get("tier") == EvidenceTier.VERIFIED_FETCH

    def test_integration_failed_fetch_keeps_lower_tier(self) -> None:
        """End-to-end: failed fetch degrades gracefully to original tier."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/a"]},
        )
        repo.upsert_crawl_state(updated)

        graph_result = {
            "build_spec": {"selected_urls": ["https://example.com/a"]},
            "graph_run_id": str(uuid4()),
        }

        # Fetch fails — returns None
        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        assert "https://example.com/a" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/a", {})
        # Should be the original tier, NOT verified_fetch
        assert prov.get("source") == "selected_by_planner"
        assert prov.get("tier") == EvidenceTier.SELECTED_BY_PLANNER


# ---------------------------------------------------------------------------
# FIX 3: Normalized URL matching
# ---------------------------------------------------------------------------


class TestNormalizedUrlMatching:
    """Tests that URL normalization prevents false negatives in evidence matching."""

    def test_trailing_slash_mismatch_resolved(self) -> None:
        """Offered URL has trailing slash, planner omits it — still matches."""
        report = resolve_evidence(
            offered_urls=["https://example.com/about/"],
            planner_selected_urls=["https://example.com/about"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"
        # Returns the offered form of the URL
        assert report.final_visited[0].url == "https://example.com/about/"

    def test_fragment_stripped_for_matching(self) -> None:
        """Fragment (#section) in planner URL doesn't break matching."""
        report = resolve_evidence(
            offered_urls=["https://example.com/page"],
            planner_selected_urls=[],
            build_spec_urls=["https://example.com/page#section2"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "build_spec_structured"

    def test_tracking_params_stripped_for_matching(self) -> None:
        """UTM params in planner URL don't break matching."""
        report = resolve_evidence(
            offered_urls=["https://example.com/work"],
            planner_selected_urls=[],
            build_spec_urls=["https://example.com/work?utm_source=crawl&utm_medium=bot"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "build_spec_structured"

    def test_scheme_case_normalization(self) -> None:
        """HTTP vs HTTPS or case differences don't break matching."""
        report = resolve_evidence(
            offered_urls=["https://example.com/page"],
            planner_selected_urls=["HTTPS://EXAMPLE.COM/page"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"

    def test_default_port_stripped(self) -> None:
        """Port 443 on HTTPS doesn't break matching."""
        report = resolve_evidence(
            offered_urls=["https://example.com/page"],
            planner_selected_urls=["https://example.com:443/page"],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"

    def test_fetched_resolved_url_credits_original(self) -> None:
        """Fetched URL redirects but same domain — still verified."""
        from kmbl_orchestrator.identity.crawl_evidence import verify_url_fetch

        # Fetch returns a slightly different resolved URL (same domain, different path)
        fake_page = {
            "url": "https://example.com/about-us",  # redirect from /about
            "title": "About",
            "description": "",
            "links": [],
            "design_signals": [],
            "tone_keywords": [],
            "status_code": 200,
        }
        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=fake_page,
        ):
            vf = verify_url_fetch("https://example.com/about")

        # Same domain redirect is still considered success
        assert vf.success is True
        assert vf.resolved_url == "https://example.com/about-us"

    def test_cross_domain_redirect_fails_verification(self) -> None:
        """Fetch redirecting to different domain fails verification."""
        from kmbl_orchestrator.identity.crawl_evidence import verify_url_fetch

        fake_page = {
            "url": "https://different-domain.com/page",
            "title": "X",
            "description": "",
            "links": [],
            "design_signals": [],
            "tone_keywords": [],
            "status_code": 200,
        }
        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=fake_page,
        ):
            vf = verify_url_fetch("https://example.com/page")

        assert vf.success is False
        assert "different domain" in vf.failure_reason


# ---------------------------------------------------------------------------
# FIX 4: Observability / honesty
# ---------------------------------------------------------------------------


class TestObservabilityEnhancements:
    """Tests that the report clearly distinguishes earned vs degraded evidence."""

    def test_report_includes_downgraded_urls(self) -> None:
        """Report captures fetch failures as downgraded_urls."""
        from kmbl_orchestrator.identity.crawl_evidence import try_upgrade_to_verified

        ev = UrlEvidence("https://example.com/z", EvidenceTier.BUILD_SPEC_STRUCTURED, "build_spec_structured")
        report = CrawlAdvancementReport()

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            try_upgrade_to_verified(ev, report)

        d = report.to_dict()
        assert len(d["downgraded_urls"]) == 1
        assert d["downgraded_urls"][0]["kept_tier"] == "build_spec_structured"
        assert len(d["fetch_failures"]) == 1

    def test_report_includes_verified_urls(self) -> None:
        """Report captures successfully verified URLs."""
        from kmbl_orchestrator.identity.crawl_evidence import try_upgrade_to_verified

        ev = UrlEvidence("https://example.com/v", EvidenceTier.SELECTED_BY_PLANNER, "selected_by_planner")
        report = CrawlAdvancementReport()

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value={"url": "https://example.com/v", "title": "V", "description": "", "links": [], "design_signals": [], "tone_keywords": [], "status_code": 200},
        ):
            try_upgrade_to_verified(ev, report)

        d = report.to_dict()
        assert "https://example.com/v" in d["verified_urls"]
        assert len(d["downgraded_urls"]) == 0

    def test_report_to_dict_has_all_fields(self) -> None:
        """to_dict includes all new observability fields."""
        report = CrawlAdvancementReport(
            planner_selected_urls=["https://a.com"],
            downgraded_urls=[{"url": "https://b.com", "kept_tier": "build_spec_structured", "reason": "timeout"}],
            fetch_failures=[{"url": "https://b.com", "reason": "timeout"}],
        )
        d = report.to_dict()
        assert "planner_selected_urls" in d
        assert "downgraded_urls" in d
        assert "fetch_failures" in d

    def test_integration_event_shows_verified_tier(self) -> None:
        """End-to-end: CRAWL_FRONTIER_ADVANCED event reflects verified tier."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/a"]},
        )
        repo.upsert_crawl_state(updated)

        grun_id = uuid4()
        repo.save_graph_run(GraphRunRecord(
            graph_run_id=grun_id,
            thread_id=uuid4(),
            identity_id=iid,
            trigger_type="autonomous_loop",
            status="completed",
        ))

        fake_page = {
            "url": "https://example.com/a",
            "title": "A",
            "description": "test",
            "links": [],
            "design_signals": [],
            "tone_keywords": [],
            "status_code": 200,
        }

        graph_result = {
            "build_spec": {"selected_urls": ["https://example.com/a"]},
            "graph_run_id": grun_id,
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=fake_page,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        events = repo.list_graph_run_events(grun_id)
        crawl_events = [e for e in events if e.event_type == RunEventType.CRAWL_FRONTIER_ADVANCED]
        assert len(crawl_events) == 1
        payload = crawl_events[0].payload_json
        assert payload["evidence_tier_used"] == "verified_fetch"
        assert "https://example.com/a" in payload["verified_urls"]


# ---------------------------------------------------------------------------
# FIX 4 (planner contract): selected_urls + relative resolution + guardrails
# ---------------------------------------------------------------------------


class TestPlannerContractSelectedUrls:
    """Tests that planner contract and relative URL resolution work end-to-end."""

    def test_absolute_selected_urls_trigger_tier2(self) -> None:
        """Planner output with explicit absolute selected_urls triggers tier-2 evidence."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["https://example.com/about", "https://example.com/work"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")
        assert urls == ["https://example.com/about", "https://example.com/work"]

        report = resolve_evidence(
            offered_urls=["https://example.com/about", "https://example.com/work"],
            planner_selected_urls=urls,
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"
        assert len(report.final_visited) == 2
        assert all(e.tier == EvidenceTier.SELECTED_BY_PLANNER for e in report.final_visited)

    def test_relative_slash_about_resolved(self) -> None:
        """Planner emitting '/about' resolves to absolute URL and triggers tier-2."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["/about"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")
        assert urls == ["https://example.com/about"]

        report = resolve_evidence(
            offered_urls=["https://example.com/about"],
            planner_selected_urls=urls,
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"

    def test_relative_no_slash_resolved(self) -> None:
        """Planner emitting 'work/project-a' resolves against root."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["work/project-a"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com/")
        assert urls == ["https://example.com/work/project-a"]

    def test_dot_slash_relative_resolved(self) -> None:
        """Planner emitting './contact' resolves against root."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["./contact"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com/")
        assert urls == ["https://example.com/contact"]

    def test_fragment_only_rejected(self) -> None:
        """Fragment-only (#section) is rejected — not a page URL."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["#section-2"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")
        assert urls == []

    def test_non_http_schemes_rejected(self) -> None:
        """Non-http schemes (ftp, mailto, javascript, data) are rejected."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": [
            "ftp://example.com/file",
            "mailto:test@example.com",
            "javascript:void(0)",
            "data:text/html,<h1>hi</h1>",
        ]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")
        assert urls == []

    def test_outside_offered_set_not_credited(self) -> None:
        """Planner-selected URLs not in offered set fall through to lower tiers."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["https://example.com/invented-page"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")
        assert urls == ["https://example.com/invented-page"]

        # But resolve_evidence won't credit it because it's not offered
        report = resolve_evidence(
            offered_urls=["https://example.com/real-page"],
            planner_selected_urls=urls,
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "frontier_fallback"

    def test_empty_selected_urls_degrades_gracefully(self) -> None:
        """Empty selected_urls degrades to lower evidence tiers."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a"],
            planner_selected_urls=[],
            build_spec_urls=["https://example.com/a"],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "build_spec_structured"

    def test_empty_selected_urls_degrades_to_fallback(self) -> None:
        """Empty selected_urls with no other evidence falls to frontier_fallback."""
        report = resolve_evidence(
            offered_urls=["https://example.com/a"],
            planner_selected_urls=[],
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "frontier_fallback"

    def test_relative_url_matches_offered_after_resolution(self) -> None:
        """Relative URL resolved then matched against offered via normalization."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["/about"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")

        report = resolve_evidence(
            offered_urls=["https://example.com/about"],
            planner_selected_urls=urls,
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"
        assert report.final_visited[0].url == "https://example.com/about"

    def test_tracking_param_relative_resolved_and_matched(self) -> None:
        """Relative URL with tracking params resolves and matches after normalization."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["/work?utm_source=planner"]}
        urls = extract_planner_selected_urls(bs, root_url="https://example.com")

        report = resolve_evidence(
            offered_urls=["https://example.com/work"],
            planner_selected_urls=urls,
            build_spec_urls=[],
            raw_payload_urls=[],
            root_url="https://example.com",
        )
        assert report.evidence_tier_used == "selected_by_planner"

    def test_no_root_url_skips_relative_resolution(self) -> None:
        """Without root_url, relative paths are silently dropped."""
        from kmbl_orchestrator.identity.crawl_evidence import extract_planner_selected_urls

        bs = {"selected_urls": ["/about", "https://example.com/abs"]}
        urls = extract_planner_selected_urls(bs, root_url=None)
        assert urls == ["https://example.com/abs"]

    def test_integration_relative_urls_in_advance_frontier(self) -> None:
        """End-to-end: relative planner URLs resolved and credited in advance_crawl_frontier."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/about", "https://example.com/work"]},
        )
        repo.upsert_crawl_state(updated)

        # Planner emits relative URL
        graph_result = {
            "build_spec": {
                "selected_urls": ["/about"],
                "note": "used about page",
            },
            "graph_run_id": str(uuid4()),
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        state = repo.get_crawl_state(iid)
        assert "https://example.com/about" in state.visited_urls
        prov = state.visit_provenance.get("https://example.com/about", {})
        assert prov.get("source") == "selected_by_planner"
        assert prov.get("tier") == EvidenceTier.SELECTED_BY_PLANNER


class TestPlannerOutputHoisting:
    """Tests that top-level selected_urls are hoisted into build_spec."""

    def test_hoist_merges_top_level_into_build_spec(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.planner import _hoist_selected_urls_into_build_spec

        raw = {
            "selected_urls": ["https://example.com/a", "https://example.com/b"],
            "build_spec": {},
        }
        _hoist_selected_urls_into_build_spec(raw)
        assert raw["build_spec"]["selected_urls"] == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    def test_hoist_deduplicates(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.planner import _hoist_selected_urls_into_build_spec

        raw = {
            "selected_urls": ["https://example.com/a"],
            "build_spec": {"selected_urls": ["https://example.com/a"]},
        }
        _hoist_selected_urls_into_build_spec(raw)
        assert raw["build_spec"]["selected_urls"] == ["https://example.com/a"]

    def test_hoist_preserves_existing(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.planner import _hoist_selected_urls_into_build_spec

        raw = {
            "selected_urls": ["https://example.com/c"],
            "build_spec": {"selected_urls": ["https://example.com/a"]},
        }
        _hoist_selected_urls_into_build_spec(raw)
        assert raw["build_spec"]["selected_urls"] == [
            "https://example.com/a",
            "https://example.com/c",
        ]

    def test_hoist_noop_without_top_level(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.planner import _hoist_selected_urls_into_build_spec

        raw = {"build_spec": {"other": "stuff"}}
        _hoist_selected_urls_into_build_spec(raw)
        assert "selected_urls" not in raw["build_spec"]

    def test_hoist_noop_without_build_spec(self) -> None:
        from kmbl_orchestrator.graph.nodes_pkg.planner import _hoist_selected_urls_into_build_spec

        raw = {"selected_urls": ["https://example.com/a"]}
        _hoist_selected_urls_into_build_spec(raw)
        # No crash, no build_spec created
        assert "build_spec" not in raw


class TestCrawlContextPlannerInstruction:
    """Tests that crawl_context includes planner instructions."""

    def test_selected_urls_contract_present(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import (
            build_crawl_context_for_planner,
            get_or_create_crawl_state,
        )

        repo = InMemoryRepository()
        iid = uuid4()
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        ctx = build_crawl_context_for_planner(state)
        assert "selected_urls_contract" in ctx
        contract = ctx["selected_urls_contract"]
        assert "instruction" in contract
        assert "selected_urls" in contract["instruction"]
        assert "examples" in contract
        assert len(contract["examples"]) >= 2
        assert "forbidden" in contract

    def test_selected_urls_contract_absent_when_no_state(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import build_crawl_context_for_planner

        ctx = build_crawl_context_for_planner(None)
        assert ctx.get("crawl_available") is False
        assert "selected_urls_contract" not in ctx


class TestPlannerRoleOutputContract:
    """Tests that the planner output contract supports selected_urls."""

    def test_selected_urls_accepted_in_output(self) -> None:
        from kmbl_orchestrator.contracts.role_outputs import PlannerRoleOutput

        out = PlannerRoleOutput.model_validate({
            "build_spec": {"type": "test"},
            "selected_urls": ["https://example.com/about"],
        })
        assert out.selected_urls == ["https://example.com/about"]

    def test_selected_urls_defaults_to_empty(self) -> None:
        from kmbl_orchestrator.contracts.role_outputs import PlannerRoleOutput

        out = PlannerRoleOutput.model_validate({
            "build_spec": {"type": "test"},
        })
        assert out.selected_urls == []

    def test_selected_urls_empty_list_valid(self) -> None:
        from kmbl_orchestrator.contracts.role_outputs import PlannerRoleOutput

        out = PlannerRoleOutput.model_validate({
            "build_spec": {"type": "test"},
            "selected_urls": [],
        })
        assert out.selected_urls == []


# ---------------------------------------------------------------------------
# Planner compliance metrics (FIX 2)
# ---------------------------------------------------------------------------


class TestPlannerComplianceMetrics:
    """Tests that compliance metrics capture planner behavior accurately."""

    def test_compliant_planner_with_selected_urls(self) -> None:
        """When planner returns valid selected_urls matching offered, metrics reflect compliance."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about", "https://example.com/work"],
            raw_planner_selected=["https://example.com/about"],
            resolved_planner_selected=["https://example.com/about"],
            matched_count=1,
            build_spec_urls=["https://example.com/about"],
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_present"] is True
        assert compliance["selected_urls_count"] == 1
        assert compliance["selected_urls_valid_count"] == 1
        assert compliance["selected_urls_matched_count"] == 1
        assert compliance["selected_urls_rejected_count"] == 0
        assert compliance["tier2_evidence_fired"] is True
        assert compliance["frontier_was_offered"] is True
        assert compliance["omitted_despite_frontier"] is False

    def test_planner_omits_selected_urls_despite_frontier(self) -> None:
        """When planner omits selected_urls but frontier was offered → non-compliance flagged."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about"],
            raw_planner_selected=[],
            resolved_planner_selected=[],
            matched_count=0,
            build_spec_urls=[],
            evidence_tier_used="frontier_fallback",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_present"] is False
        assert compliance["omitted_despite_frontier"] is True
        assert compliance["tier2_evidence_fired"] is False
        assert compliance["degraded_to_tier"] == "frontier_fallback"

    def test_planner_selected_urls_rejected_count(self) -> None:
        """When planner selects URLs not in offered set → rejected_count > 0."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about"],
            raw_planner_selected=["https://example.com/about", "https://example.com/INVENTED"],
            resolved_planner_selected=["https://example.com/about", "https://example.com/INVENTED"],
            matched_count=1,
            build_spec_urls=[],
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_count"] == 2
        assert compliance["selected_urls_valid_count"] == 2
        assert compliance["selected_urls_matched_count"] == 1
        assert compliance["selected_urls_rejected_count"] == 1

    def test_no_frontier_offered(self) -> None:
        """When no frontier URLs were offered, no non-compliance flagged."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=[],
            raw_planner_selected=[],
            resolved_planner_selected=[],
            matched_count=0,
            build_spec_urls=[],
            evidence_tier_used="",
            root_url="https://example.com",
        )
        assert compliance["frontier_was_offered"] is False
        assert compliance["omitted_despite_frontier"] is False

    def test_degraded_tier_is_none_when_tier2_fires(self) -> None:
        """degraded_to_tier should be None when tier-2 fires."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/a"],
            raw_planner_selected=["https://example.com/a"],
            resolved_planner_selected=["https://example.com/a"],
            matched_count=1,
            build_spec_urls=[],
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["degraded_to_tier"] is None

    def test_degraded_to_build_spec_structured(self) -> None:
        """When planner selects but none match, degrades to build_spec_structured."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/a"],
            raw_planner_selected=["https://example.com/NOT_OFFERED"],
            resolved_planner_selected=["https://example.com/NOT_OFFERED"],
            matched_count=0,
            build_spec_urls=["https://example.com/a"],
            evidence_tier_used="build_spec_structured",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_present"] is True
        assert compliance["tier2_evidence_fired"] is False
        assert compliance["degraded_to_tier"] == "build_spec_structured"


# ---------------------------------------------------------------------------
# Consistency signal (FIX 3)
# ---------------------------------------------------------------------------


class TestSelectedUrlsConsistencySignal:
    """Tests that selected_urls_consistent_with_output is computed correctly."""

    def test_consistent_when_selected_in_build_spec(self) -> None:
        """selected URL also appears in build_spec → consistent."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about"],
            raw_planner_selected=["https://example.com/about"],
            resolved_planner_selected=["https://example.com/about"],
            matched_count=1,
            build_spec_urls=["https://example.com/about", "https://example.com/work"],
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_consistent_with_output"] is True

    def test_inconsistent_when_selected_not_in_build_spec(self) -> None:
        """selected URL is not referenced anywhere in build_spec → inconsistent."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about"],
            raw_planner_selected=["https://example.com/about"],
            resolved_planner_selected=["https://example.com/about"],
            matched_count=1,
            build_spec_urls=["https://example.com/work"],  # different!
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_consistent_with_output"] is False

    def test_consistent_false_when_no_selected(self) -> None:
        """No selected URLs → consistent is False."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about"],
            raw_planner_selected=[],
            resolved_planner_selected=[],
            matched_count=0,
            build_spec_urls=["https://example.com/about"],
            evidence_tier_used="build_spec_structured",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_consistent_with_output"] is False

    def test_consistent_with_normalized_urls(self) -> None:
        """Normalization (trailing slash, etc.) shouldn't break consistency check."""
        from kmbl_orchestrator.identity.crawl_evidence import compute_planner_compliance

        compliance = compute_planner_compliance(
            offered_urls=["https://example.com/about/"],
            raw_planner_selected=["https://example.com/about"],
            resolved_planner_selected=["https://example.com/about"],
            matched_count=1,
            build_spec_urls=["https://example.com/about/"],  # trailing slash
            evidence_tier_used="selected_by_planner",
            root_url="https://example.com",
        )
        assert compliance["selected_urls_consistent_with_output"] is True


# ---------------------------------------------------------------------------
# Integration: compliance events in _advance_crawl_frontier
# ---------------------------------------------------------------------------


class TestComplianceEventIntegration:
    """Tests that _advance_crawl_frontier emits compliance events."""

    def test_compliance_event_emitted_on_advance(self) -> None:
        """PLANNER_CRAWL_COMPLIANCE event is emitted with metrics."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/about"]},
        )
        repo.upsert_crawl_state(updated)

        grun_id = uuid4()
        repo.save_graph_run(GraphRunRecord(
            graph_run_id=grun_id,
            thread_id=uuid4(),
            identity_id=iid,
            trigger_type="autonomous_loop",
            status="completed",
        ))

        graph_result = {
            "build_spec": {
                "selected_urls": ["https://example.com/about"],
            },
            "graph_run_id": grun_id,
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        events = repo.list_graph_run_events(grun_id)
        compliance_events = [
            e for e in events
            if e.event_type == RunEventType.PLANNER_CRAWL_COMPLIANCE
        ]
        assert len(compliance_events) == 1
        payload = compliance_events[0].payload_json
        assert payload["selected_urls_present"] is True
        assert payload["selected_urls_count"] == 1
        assert payload["tier2_evidence_fired"] is True
        assert payload["omitted_despite_frontier"] is False

    def test_compliance_event_non_compliant_planner(self) -> None:
        """When planner omits selected_urls, compliance event captures non-compliance."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/about"]},
        )
        repo.upsert_crawl_state(updated)

        grun_id = uuid4()
        repo.save_graph_run(GraphRunRecord(
            graph_run_id=grun_id,
            thread_id=uuid4(),
            identity_id=iid,
            trigger_type="autonomous_loop",
            status="completed",
        ))

        # Planner did not return selected_urls at all
        graph_result = {
            "build_spec": {
                "title": "test build",
            },
            "graph_run_id": grun_id,
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        events = repo.list_graph_run_events(grun_id)
        compliance_events = [
            e for e in events
            if e.event_type == RunEventType.PLANNER_CRAWL_COMPLIANCE
        ]
        assert len(compliance_events) == 1
        payload = compliance_events[0].payload_json
        assert payload["selected_urls_present"] is False
        assert payload["omitted_despite_frontier"] is True
        assert payload["tier2_evidence_fired"] is False

    def test_compliance_in_report_to_dict(self) -> None:
        """CrawlAdvancementReport.to_dict() includes planner_compliance."""
        report = CrawlAdvancementReport(
            planner_compliance={"selected_urls_present": True, "tier2_evidence_fired": True},
        )
        d = report.to_dict()
        assert "planner_compliance" in d
        assert d["planner_compliance"]["selected_urls_present"] is True

    def test_compliance_defaults_to_empty_dict(self) -> None:
        """Default planner_compliance is empty dict."""
        report = CrawlAdvancementReport()
        assert report.planner_compliance == {}
        d = report.to_dict()
        assert d["planner_compliance"] == {}

    def test_consistency_signal_in_integration(self) -> None:
        """End-to-end: consistency signal computed when selected matches build_spec."""
        from kmbl_orchestrator.autonomous.loop_service import _advance_crawl_frontier

        repo = InMemoryRepository()
        iid = uuid4()
        loop = _make_loop(identity_id=iid)
        state = get_or_create_crawl_state(repo, iid, "https://example.com")
        updated = state.model_copy(
            update={"unvisited_urls": ["https://example.com/about"]},
        )
        repo.upsert_crawl_state(updated)

        grun_id = uuid4()
        repo.save_graph_run(GraphRunRecord(
            graph_run_id=grun_id,
            thread_id=uuid4(),
            identity_id=iid,
            trigger_type="autonomous_loop",
            status="completed",
        ))

        # Planner selected /about AND referenced it in build_spec
        graph_result = {
            "build_spec": {
                "selected_urls": ["https://example.com/about"],
                "reference_urls": ["https://example.com/about"],
                "sections": [{"url": "https://example.com/about"}],
            },
            "graph_run_id": grun_id,
        }

        with patch(
            "kmbl_orchestrator.identity.page_fetch.fetch_page_data",
            return_value=None,
        ):
            _advance_crawl_frontier(repo, loop, graph_result)

        events = repo.list_graph_run_events(grun_id)
        compliance_events = [
            e for e in events
            if e.event_type == RunEventType.PLANNER_CRAWL_COMPLIANCE
        ]
        assert len(compliance_events) == 1
        payload = compliance_events[0].payload_json
        assert payload["selected_urls_consistent_with_output"] is True


# ---------------------------------------------------------------------------
# Contract examples in crawl_context
# ---------------------------------------------------------------------------


class TestSelectedUrlsContractExamples:
    """Tests that the selected_urls_contract has properly structured examples."""

    def test_contract_has_absolute_url_example(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import _SELECTED_URLS_CONTRACT

        examples = _SELECTED_URLS_CONTRACT["examples"]
        # At least one example uses absolute URLs
        abs_example = next(
            (e for e in examples if any(
                u.startswith("https://") for u in e["correct_output"]["selected_urls"]
            )),
            None,
        )
        assert abs_example is not None

    def test_contract_has_relative_url_example(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import _SELECTED_URLS_CONTRACT

        examples = _SELECTED_URLS_CONTRACT["examples"]
        # At least one example uses relative paths
        rel_example = next(
            (e for e in examples if any(
                u.startswith("/") for u in e["correct_output"]["selected_urls"]
            )),
            None,
        )
        assert rel_example is not None

    def test_contract_has_empty_example(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import _SELECTED_URLS_CONTRACT

        examples = _SELECTED_URLS_CONTRACT["examples"]
        # At least one example with empty selected_urls
        empty_example = next(
            (e for e in examples if e["correct_output"]["selected_urls"] == []),
            None,
        )
        assert empty_example is not None

    def test_contract_forbids_invented_urls(self) -> None:
        from kmbl_orchestrator.identity.crawl_state import _SELECTED_URLS_CONTRACT

        forbidden = _SELECTED_URLS_CONTRACT["forbidden"]
        assert "not in" in forbidden.lower() or "invented" in forbidden.lower()
