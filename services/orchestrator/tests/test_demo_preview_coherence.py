"""
Targeted tests for the demo-path preview coherence story.

Covers:
    P1  Evaluator preview URL resolves to the same canonical surface used by materialized
        preview in demo mode (candidate_preview → orchestrator_candidate_preview_url).
    P2  Demo mode surfaces preview-materialization failure clearly via
        HABITAT_MATERIALIZATION_FAILED event.
    P3  Playwright-enriched crawl evidence actually appears in planner-relevant context
        selection and gets a ranking boost.
    P4  Candidate / staging / live preview resolution is coherent rather than accidental.
    P5  Canonical demo preview helper produces a single URL consistent with evaluator resolution.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.identity.crawl_ranking import rank_summaries_for_planner, summary_strength
from kmbl_orchestrator.identity.crawl_state import build_crawl_context_for_planner
from kmbl_orchestrator.domain import CrawlStateRecord
from kmbl_orchestrator.runtime.habitat_lifecycle import (
    clear_registry_for_tests,
    register_materialization,
)
from kmbl_orchestrator.runtime.run_events import RunEventType
from kmbl_orchestrator.runtime.session_staging_links import (
    resolve_canonical_demo_preview,
    resolve_evaluator_preview_resolution,
)


@pytest.fixture(autouse=True)
def _reset_habitat_registry() -> None:
    clear_registry_for_tests()


# ---------------------------------------------------------------------------
# P1: Evaluator preview URL points at the same surface as canonical demo preview
# ---------------------------------------------------------------------------


class TestEvaluatorPreviewCoherence:
    """Evaluator preview_url and canonical demo preview must agree."""

    def test_both_resolve_to_candidate_preview_with_configured_base(self) -> None:
        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        gid = str(uuid4())
        tid = str(uuid4())

        ev_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        canon = resolve_canonical_demo_preview(s, graph_run_id=gid, thread_id=tid)

        # Both must resolve to the same candidate-preview URL
        expected_candidate = f"https://demo.example.com/orchestrator/runs/{gid}/candidate-preview"
        assert ev_res["preview_url"] == expected_candidate
        assert canon["canonical_preview_url"] == expected_candidate

    def test_both_resolve_with_derived_local_base(self) -> None:
        s = Settings(
            orchestrator_public_base_url="",
            orchestrator_port=9090,
            kmbl_env="development",
        )
        gid = str(uuid4())
        tid = str(uuid4())

        ev_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        canon = resolve_canonical_demo_preview(s, graph_run_id=gid, thread_id=tid)

        expected = f"http://127.0.0.1:9090/orchestrator/runs/{gid}/candidate-preview"
        # Canonical preview resolves; evaluator browser URL is blocked (localhost not
        # browser-reachable), but operator_preview_url still points at the same surface.
        assert canon["canonical_preview_url"] == expected
        assert ev_res["operator_preview_url"] == expected
        # Browser preview_url is None because localhost is not browser-reachable by default
        assert ev_res["preview_url"] is None
        assert ev_res["preview_grounding_mode"] == "operator_local_only"

    def test_no_base_produces_none_for_both(self) -> None:
        s = Settings(
            orchestrator_public_base_url="",
            kmbl_env="production",
        )
        gid = str(uuid4())
        tid = str(uuid4())

        ev_res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )
        canon = resolve_canonical_demo_preview(s, graph_run_id=gid, thread_id=tid)

        assert ev_res["preview_url"] is None
        assert canon["canonical_preview_url"] is None


# ---------------------------------------------------------------------------
# P2: Materialization failure is surfaced, not swallowed
# ---------------------------------------------------------------------------


class TestMaterializationFailureEvent:
    """HABITAT_MATERIALIZATION_FAILED event type exists and can be emitted."""

    def test_event_type_exists(self) -> None:
        assert hasattr(RunEventType, "HABITAT_MATERIALIZATION_FAILED")
        assert RunEventType.HABITAT_MATERIALIZATION_FAILED == "habitat_materialization_failed"


# ---------------------------------------------------------------------------
# P3: Playwright-enriched crawl evidence has ranking advantage
# ---------------------------------------------------------------------------


class TestPlaywrightRankingBoost:
    """Pages with reference_sketch (Playwright data) rank higher."""

    def test_summary_strength_boosted_by_reference_sketch(self) -> None:
        plain = {
            "summary": "A portfolio page",
            "design_signals": ["grid", "hero"],
            "tone_keywords": ["modern"],
        }
        enriched = {
            **plain,
            "reference_sketch": {"layout": "asymmetric", "motion": "scroll-reveal"},
        }

        plain_score = summary_strength(plain)
        enriched_score = summary_strength(enriched)
        assert enriched_score > plain_score
        assert enriched_score >= plain_score + 0.20  # at least +0.20 from boost

    def test_empty_reference_sketch_no_boost(self) -> None:
        data = {
            "summary": "A page",
            "design_signals": ["grid"],
            "tone_keywords": [],
            "reference_sketch": {},
        }
        no_sketch = {
            "summary": "A page",
            "design_signals": ["grid"],
            "tone_keywords": [],
        }
        assert summary_strength(data) == summary_strength(no_sketch)

    def test_ranking_prefers_playwright_enriched_pages(self) -> None:
        items = [
            {
                "url": "https://site.com/about",
                "summary": "About page",
                "design_signals": ["grid"],
                "tone_keywords": ["modern"],
                "origin": "portfolio",
            },
            {
                "url": "https://site.com/work",
                "summary": "Work page with rich layout",
                "design_signals": ["grid", "hero"],
                "tone_keywords": ["creative"],
                "origin": "portfolio",
                "reference_sketch": {"layout": "masonry", "motion": "parallax"},
            },
        ]
        ranked = rank_summaries_for_planner(
            items, root_url="https://site.com", origin="portfolio", limit=5
        )
        # The enriched page should rank first
        assert ranked[0]["url"] == "https://site.com/work"
        assert ranked[0].get("crawl_rank", 0) > ranked[1].get("crawl_rank", 0)


# ---------------------------------------------------------------------------
# P3b: Playwright evidence appears in planner crawl context with flag
# ---------------------------------------------------------------------------


class TestPlaywrightInPlannerContext:
    """build_crawl_context_for_planner must surface has_rendered_evidence flag."""

    def _make_crawl_state(self, *, with_sketch: bool = False) -> CrawlStateRecord:
        summaries = {
            "https://site.com/": {
                "summary": "Homepage",
                "design_signals": ["hero", "grid"],
                "tone_keywords": ["modern"],
                "crawled_at": "2026-04-06T00:00:00+00:00",
                "origin": "portfolio",
            },
            "https://site.com/work": {
                "summary": "Work page",
                "design_signals": ["masonry", "carousel"],
                "tone_keywords": ["creative"],
                "crawled_at": "2026-04-06T00:01:00+00:00",
                "origin": "portfolio",
            },
        }
        if with_sketch:
            summaries["https://site.com/work"]["reference_sketch"] = {
                "layout": "masonry-grid",
                "motion": "scroll-triggered",
            }

        return CrawlStateRecord(
            identity_id=uuid4(),
            root_url="https://site.com/",
            site_key="site.com",
            visited_urls=["https://site.com/", "https://site.com/work"],
            unvisited_urls=["https://site.com/about"],
            page_summaries=summaries,
            crawl_status="in_progress",
            crawl_phase="identity_grounding",
            total_pages_crawled=2,
        )

    def test_rendered_evidence_flag_present_when_sketch_exists(self) -> None:
        state = self._make_crawl_state(with_sketch=True)
        ctx = build_crawl_context_for_planner(state)

        # Find the work page in top_identity_pages or recent summaries
        all_items = ctx.get("top_identity_pages", []) + ctx.get("recent_portfolio_summaries", [])
        work_items = [i for i in all_items if i.get("url") == "https://site.com/work"]
        assert work_items, "work page should appear in planner context"
        assert work_items[0]["has_rendered_evidence"] is True
        assert "reference_sketch" in work_items[0]

    def test_rendered_evidence_flag_false_without_sketch(self) -> None:
        state = self._make_crawl_state(with_sketch=False)
        ctx = build_crawl_context_for_planner(state)

        all_items = ctx.get("top_identity_pages", []) + ctx.get("recent_portfolio_summaries", [])
        work_items = [i for i in all_items if i.get("url") == "https://site.com/work"]
        assert work_items
        assert work_items[0]["has_rendered_evidence"] is False
        assert "reference_sketch" not in work_items[0]

    def test_rendered_evidence_count_in_context(self) -> None:
        state = self._make_crawl_state(with_sketch=True)
        ctx = build_crawl_context_for_planner(state)
        assert ctx["rendered_evidence_count"] == 1

    def test_rendered_evidence_count_zero_without_sketches(self) -> None:
        state = self._make_crawl_state(with_sketch=False)
        ctx = build_crawl_context_for_planner(state)
        assert ctx["rendered_evidence_count"] == 0


# ---------------------------------------------------------------------------
# P4: Candidate / staging / live materialization coherence
# ---------------------------------------------------------------------------


class TestMaterializationCoherence:
    """Preview resolution includes materialization status."""

    def test_coherence_flags_after_registration(self) -> None:
        tid = uuid4()
        gid = uuid4()

        register_materialization(
            thread_id=tid,
            local_path=f"/tmp/cp/{tid}",
            materialization_kind="candidate_preview",
            graph_run_id=gid,
            can_rehydrate_from_persistence=True,
        )
        register_materialization(
            thread_id=tid,
            local_path=f"/tmp/ws/{tid}",
            materialization_kind="live_habitat",
            graph_run_id=gid,
            can_rehydrate_from_persistence=True,
        )

        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        res = resolve_evaluator_preview_resolution(
            s,
            graph_run_id=str(gid),
            thread_id=str(tid),
            build_candidate={},
        )

        assert res["candidate_preview_materialized"] is True
        assert res["live_habitat_materialized"] is True
        assert res["preview_materialization_coherent"] is True

    def test_coherence_flags_without_registration(self) -> None:
        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        gid = str(uuid4())
        tid = str(uuid4())

        res = resolve_evaluator_preview_resolution(
            s, graph_run_id=gid, thread_id=tid, build_candidate={}
        )

        assert res["candidate_preview_materialized"] is False
        assert res["live_habitat_materialized"] is False
        assert res["preview_materialization_coherent"] is False


# ---------------------------------------------------------------------------
# P5: Canonical demo preview fallback diagnostics
# ---------------------------------------------------------------------------


class TestCanonicalDemoPreviewDiagnostics:
    """resolve_canonical_demo_preview must provide explicit fallback info."""

    def test_canonical_preview_no_fallback_with_base(self) -> None:
        s = Settings(orchestrator_public_base_url="https://demo.example.com")
        gid = str(uuid4())
        tid = str(uuid4())

        result = resolve_canonical_demo_preview(s, graph_run_id=gid, thread_id=tid)
        assert result["canonical_preview_url"] is not None
        assert result["canonical_preview_fallback"] is False
        assert "candidate_preview" in result["canonical_preview_source"]

    def test_canonical_preview_none_without_base(self) -> None:
        s = Settings(
            orchestrator_public_base_url="",
            kmbl_env="production",
        )
        gid = str(uuid4())
        tid = str(uuid4())

        result = resolve_canonical_demo_preview(s, graph_run_id=gid, thread_id=tid)
        assert result["canonical_preview_url"] is None
        assert result["canonical_preview_source"] == "none"
