"""
End-to-end integration test for the full graph pipeline using the stub transport.

Exercises the complete flow:
  persist_graph_run_start → run_graph →
    planner → generator → evaluator → decision_router → staging_node

Validates:
- Final state has expected fields
- Normalization rescue events are emitted when applicable
- Evaluator→identity feedback is upserted after staging
- rating_trend appears in working_staging_facts after rated snapshots
- pass_count is tracked in decision events
- Publication delivery produces valid HTML from a snapshot payload
- build_graph_context / get_compiled_graph helpers work correctly
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.app import (
    build_graph_context,
    get_compiled_graph,
    persist_graph_run_start,
    run_graph,
)
from kmbl_orchestrator.identity.hydrate import (
    persist_identity_from_seed,
    upsert_identity_evolution_signal,
)
from kmbl_orchestrator.identity.seed import IdentitySeed
from kmbl_orchestrator.normalize.generator import normalize_generator_output
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType
from kmbl_orchestrator.staging.facts import (
    WorkingStagingFacts,
    _compute_rating_trend,
    build_working_staging_facts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings() -> Settings:
    return Settings.model_construct(
        kiloclaw_transport="stub",
        graph_max_iterations_default=3,
        habitat_image_generation_enabled=False,
        # Integration expects a review snapshot row each pass; product default is on_nomination.
        staging_snapshot_policy="always",
    )


def _run_full_pipeline(
    repo: InMemoryRepository,
    identity_id: str | None = None,
    event_input: dict[str, Any] | None = None,
) -> tuple[str, str, Any]:
    """Persist start + run full graph. Returns (thread_id, graph_run_id, final_state)."""
    settings = _make_settings()
    invoker = DefaultRoleInvoker(settings=settings)
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=identity_id,
        trigger_type="prompt",
        event_input=event_input or {},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid,
            "graph_run_id": gid,
            "identity_id": identity_id,
            "event_input": event_input or {},
        },
    )
    return tid, gid, final


# ---------------------------------------------------------------------------
# 1. Full pipeline smoke test
# ---------------------------------------------------------------------------

class TestFullPipelineStub:
    def test_run_completes_and_stages(self) -> None:
        """Full stub pipeline produces a staging_snapshot and graph_run_id."""
        repo = InMemoryRepository()
        tid, gid, final = _run_full_pipeline(repo)

        # Status should be completed
        gr = repo.get_graph_run(UUID(gid))
        assert gr is not None
        assert gr.status == "completed"

        # At least one staging snapshot must exist
        snaps = repo.list_staging_snapshots_for_thread(UUID(tid), limit=5)
        assert snaps, "expected at least one staging snapshot"

        # Staging snapshot linked to the correct graph run
        assert str(snaps[0].graph_run_id) == gid

    def test_run_emits_expected_event_types(self) -> None:
        """Core event types must appear in the run timeline."""
        repo = InMemoryRepository()
        tid, gid, _ = _run_full_pipeline(repo)

        evs = repo.list_graph_run_events(UUID(gid), limit=200)
        ev_types = {e.event_type for e in evs}

        assert RunEventType.GRAPH_RUN_STARTED in ev_types
        assert RunEventType.PLANNER_INVOCATION_COMPLETED in ev_types
        assert RunEventType.GENERATOR_INVOCATION_COMPLETED in ev_types
        assert RunEventType.EVALUATOR_INVOCATION_COMPLETED in ev_types
        assert RunEventType.DECISION_MADE in ev_types
        assert RunEventType.STAGING_SNAPSHOT_CREATED in ev_types

    def test_decision_event_has_pass_count(self) -> None:
        """DECISION_MADE events must carry a pass_count field."""
        repo = InMemoryRepository()
        tid, gid, _ = _run_full_pipeline(repo)
        evs = repo.list_graph_run_events(UUID(gid), limit=200)
        decision_evs = [e for e in evs if e.event_type == RunEventType.DECISION_MADE]
        assert decision_evs, "no DECISION_MADE events found"
        for ev in decision_evs:
            assert "pass_count" in (ev.payload_json or {}), (
                f"DECISION_MADE event missing pass_count: {ev.payload_json}"
            )


# ---------------------------------------------------------------------------
# 2. Normalization rescue observability
# ---------------------------------------------------------------------------

class TestNormalizationRescueObservability:
    def test_rescue_paths_tracked_in_raw_payload(self) -> None:
        """When generator output needs recovery, _normalization_rescues is set in raw_payload_json."""
        # Build a raw output where content is in proposed_changes not artifact_outputs
        raw = {
            "artifact_outputs": [],
            "proposed_changes": {
                "files": [
                    {
                        "path": "component/preview/index.html",
                        "content": "<html><body>Hello</body></html>",
                    }
                ]
            },
        }
        tid = uuid4()
        gid = uuid4()
        inv_id = uuid4()
        bsid = uuid4()
        cand = normalize_generator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=inv_id,
            build_spec_id=bsid,
        )
        rescues = (cand.raw_payload_json or {}).get("_normalization_rescues")
        assert rescues is not None, "expected _normalization_rescues in raw_payload_json"
        assert any("recover_from_proposed_changes" in r for r in rescues), (
            f"expected recover_from_proposed_changes in {rescues}"
        )

    def test_no_rescue_paths_for_clean_output(self) -> None:
        """Clean artifact output should not trigger any rescue path."""
        raw = {
            "artifact_outputs": [
                {
                    "role": "static_frontend_file_v1",
                    "path": "component/preview/index.html",
                    "language": "html",
                    "content": "<html><body>clean</body></html>",
                    "entry_for_preview": True,
                }
            ],
        }
        tid = uuid4()
        gid = uuid4()
        inv_id = uuid4()
        bsid = uuid4()
        cand = normalize_generator_output(
            raw,
            thread_id=tid,
            graph_run_id=gid,
            generator_invocation_id=inv_id,
            build_spec_id=bsid,
        )
        rescues = (cand.raw_payload_json or {}).get("_normalization_rescues")
        # Content index is not a rescue, other paths should not fire for clean output
        assert not any(
            k in (rescues or [])
            for k in ["recover_from_proposed_changes", "recover_from_updated_state",
                      "artifact_norm_fallback", "post_recovery_norm_fallback"]
        ), f"unexpected rescues for clean output: {rescues}"

    def test_normalization_rescue_event_emitted_in_graph(self) -> None:
        """When the generator stub produces a recoverable output, a NORMALIZATION_RESCUE event appears."""
        # The stub transport produces a standard output so this tests the no-rescue path.
        # We verify the event is NOT spuriously emitted for clean stub output.
        repo = InMemoryRepository()
        tid, gid, _ = _run_full_pipeline(repo)
        evs = repo.list_graph_run_events(UUID(gid), limit=200)
        rescue_evs = [e for e in evs if e.event_type == RunEventType.NORMALIZATION_RESCUE]
        # Stub output is clean — should produce zero rescue events
        assert len(rescue_evs) == 0, (
            f"unexpected rescue events for stub transport: {[e.payload_json for e in rescue_evs]}"
        )


# ---------------------------------------------------------------------------
# 3. Evaluator → identity feedback loop
# ---------------------------------------------------------------------------

class TestEvaluatorIdentityFeedbackLoop:
    def test_evolution_signal_upserted_after_staging(self) -> None:
        """After a full run with identity_id, identity_profile gains evolution_signals."""
        repo = InMemoryRepository()
        # Create identity
        seed = IdentitySeed(
            source_url="https://example-portfolio.test",
            display_name="Test Creator",
            tone_keywords=["bold"],
            confidence=0.7,
        )
        identity_id = persist_identity_from_seed(repo, seed)

        _run_full_pipeline(repo, identity_id=str(identity_id))

        profile = repo.get_identity_profile(identity_id)
        assert profile is not None
        facets = profile.facets_json
        signals = facets.get("evolution_signals")
        assert signals, "expected evolution_signals in identity_profile.facets_json"
        assert isinstance(signals, list)
        assert len(signals) >= 1
        first = signals[0]
        assert "evaluation_status" in first
        assert "graph_run_id" in first
        assert "recorded_at" in first

    def test_quality_trend_derived_from_signals(self) -> None:
        """After multiple runs, recent_quality_trend is set in identity_profile.facets_json."""
        repo = InMemoryRepository()
        seed = IdentitySeed(source_url="https://example.test", confidence=0.5)
        identity_id = persist_identity_from_seed(repo, seed)

        # Simulate several upserts directly
        settings = _make_settings()
        gid1, gid2, gid3 = uuid4(), uuid4(), uuid4()
        for gid, status in [(gid1, "partial"), (gid2, "partial"), (gid3, "pass")]:
            upsert_identity_evolution_signal(
                repo,
                identity_id,
                graph_run_id=gid,
                evaluation_status=status,
                evaluation_summary="test",
                issue_count=0,
            )

        profile = repo.get_identity_profile(identity_id)
        assert profile is not None
        facets = profile.facets_json
        trend = facets.get("recent_quality_trend")
        # With pass at end, should trend improving or mixed
        assert trend in ("improving", "mixed"), f"unexpected trend: {trend}"

    def test_identity_feedback_event_emitted(self) -> None:
        """IDENTITY_FEEDBACK_UPSERT event must appear in timeline after staging."""
        repo = InMemoryRepository()
        seed = IdentitySeed(source_url="https://portfolio.test", confidence=0.6)
        identity_id = persist_identity_from_seed(repo, seed)

        tid, gid, _ = _run_full_pipeline(repo, identity_id=str(identity_id))

        evs = repo.list_graph_run_events(UUID(gid), limit=200)
        fb_evs = [e for e in evs if e.event_type == RunEventType.IDENTITY_FEEDBACK_UPSERT]
        assert fb_evs, "expected IDENTITY_FEEDBACK_UPSERT event in timeline"
        payload = fb_evs[0].payload_json or {}
        assert payload.get("identity_id") == str(identity_id)
        assert "evaluation_status" in payload


# ---------------------------------------------------------------------------
# 4. Rating trend in working_staging_facts
# ---------------------------------------------------------------------------

class TestRatingTrend:
    def test_compute_rating_trend_improving(self) -> None:
        assert _compute_rating_trend([2, 2, 3, 4, 5]) == "improving"

    def test_compute_rating_trend_declining(self) -> None:
        assert _compute_rating_trend([5, 4, 3, 2, 1]) == "declining"

    def test_compute_rating_trend_flat(self) -> None:
        assert _compute_rating_trend([3, 3, 3, 3]) == "flat"

    def test_compute_rating_trend_single(self) -> None:
        assert _compute_rating_trend([4]) == "none"

    def test_compute_rating_trend_empty(self) -> None:
        assert _compute_rating_trend([]) == "none"

    def test_rating_trend_in_facts(self) -> None:
        """WorkingStagingFacts includes rating_trend when recent_user_ratings provided."""
        from kmbl_orchestrator.domain import WorkingStagingRecord

        ws = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
        )
        facts = build_working_staging_facts(ws, recent_user_ratings=[2, 3, 4, 5])
        assert facts.rating_trend == "improving"
        assert facts.recent_user_ratings == [2, 3, 4, 5]

    def test_no_rating_trend_without_ratings(self) -> None:
        """WorkingStagingFacts has no rating_trend when no ratings given."""
        from kmbl_orchestrator.domain import WorkingStagingRecord

        ws = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
        )
        facts = build_working_staging_facts(ws)
        assert facts.rating_trend is None
        assert facts.recent_user_ratings == []


# ---------------------------------------------------------------------------
# 5. build_graph_context / get_compiled_graph public helpers
# ---------------------------------------------------------------------------

class TestGraphContextHelpers:
    def test_build_graph_context_creates_context(self) -> None:
        """build_graph_context returns a GraphContext with correct repo and settings."""
        from kmbl_orchestrator.graph.app import GraphContext

        repo = InMemoryRepository()
        settings = _make_settings()
        ctx = build_graph_context(settings, repo)
        assert isinstance(ctx, GraphContext)
        assert ctx.repo is repo
        assert ctx.settings is settings

    def test_get_compiled_graph_returns_compilable_graph(self) -> None:
        """get_compiled_graph returns an object with an invoke method (compiled LangGraph)."""
        repo = InMemoryRepository()
        settings = _make_settings()
        ctx = build_graph_context(settings, repo)
        graph = get_compiled_graph(ctx)
        assert hasattr(graph, "invoke"), "expected compiled graph to have .invoke()"


# ---------------------------------------------------------------------------
# 6. Publication delivery
# ---------------------------------------------------------------------------

class TestPublicationDelivery:
    def _make_snapshot_payload(self) -> dict[str, Any]:
        """Minimal v1 staging payload with a static HTML file."""
        return {
            "version": 1,
            "artifacts": {
                "artifact_refs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": "<html><head></head><body><h1>Hello KMBL</h1></body></html>",
                        "entry_for_preview": True,
                        "bundle_id": "preview",
                    },
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/styles.css",
                        "language": "css",
                        "content": "body { margin: 0; }",
                        "bundle_id": "preview",
                    },
                ]
            },
            "evaluation": {"status": "pass", "summary": "ok"},
        }

    def _make_publication_snapshot(self) -> Any:
        from kmbl_orchestrator.domain import PublicationSnapshotRecord

        return PublicationSnapshotRecord(
            publication_snapshot_id=uuid4(),
            thread_id=uuid4(),
            source_staging_snapshot_id=uuid4(),
            payload_json=self._make_snapshot_payload(),
        )

    def test_delivery_returns_html(self) -> None:
        """deliver_publication_snapshot returns non-empty HTML for a valid payload."""
        from kmbl_orchestrator.publication.delivery import deliver_publication_snapshot

        snap = self._make_publication_snapshot()
        result = deliver_publication_snapshot(snap)
        assert result.delivered, f"expected delivered=True, reason={result.reason}"
        assert result.html_content
        assert "Hello KMBL" in result.html_content

    def test_delivery_sets_public_url_when_base_url_given(self) -> None:
        """deliver_publication_snapshot sets public_url when base_url provided."""
        from kmbl_orchestrator.publication.delivery import deliver_publication_snapshot

        snap = self._make_publication_snapshot()
        result = deliver_publication_snapshot(
            snap, base_url="https://pub.example.com"
        )
        assert result.delivered
        assert result.public_url is not None
        assert result.public_url.startswith("https://pub.example.com/")
        assert result.public_url.endswith(".html")

    def test_delivery_fails_gracefully_for_empty_payload(self) -> None:
        """deliver_publication_snapshot returns delivered=False for empty payload."""
        from kmbl_orchestrator.domain import PublicationSnapshotRecord
        from kmbl_orchestrator.publication.delivery import deliver_publication_snapshot

        snap = PublicationSnapshotRecord(
            publication_snapshot_id=uuid4(),
            thread_id=uuid4(),
            source_staging_snapshot_id=uuid4(),
            payload_json={},
        )
        result = deliver_publication_snapshot(snap)
        assert not result.delivered

    def test_delivery_writes_html_to_output_dir(self, tmp_path) -> None:
        """deliver_publication_snapshot writes an HTML file when output_dir is given."""
        from kmbl_orchestrator.publication.delivery import deliver_publication_snapshot

        snap = self._make_publication_snapshot()
        result = deliver_publication_snapshot(snap, output_dir=str(tmp_path))
        assert result.delivered
        assert result.output_path is not None
        from pathlib import Path

        p = Path(result.output_path)
        assert p.exists()
        assert p.read_text(encoding="utf-8") == result.html_content
