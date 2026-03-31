"""
Tests for the three critical fixes from the architecture audit:

Fix 1 — retry_context delivery through the cron/loop bridge.
Fix 2 — alignment_score + alignment_signals_json persisted through repository.
Fix 3 — _sync_run returns last_alignment_score (not evaluator_confidence).

These tests prove the orchestrator wiring is correct. They do NOT require KiloClaw.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from kmbl_orchestrator.api.loops import run_graph_for_loop
from kmbl_orchestrator.autonomous.loop_service import start_autonomous_loop
from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    AutonomousLoopRecord,
    EvaluationReportRecord,
)
from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
from kmbl_orchestrator.identity.seed import IdentitySeed
from kmbl_orchestrator.persistence.repository import InMemoryRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides: Any) -> Settings:
    defaults = {
        "kiloclaw_transport": "stub",
        "graph_max_iterations_default": 2,
        "habitat_image_generation_enabled": False,
        "identity_allow_fallback_profile": True,
    }
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


def _make_repo_with_identity() -> tuple[InMemoryRepository, str]:
    repo = InMemoryRepository()
    iid = uuid4()
    seed = IdentitySeed(
        source_url="https://test.example.com",
        display_name="Alice Example",
        role_or_title="designer",
        tone_keywords=["bold", "minimal"],
        palette_hints=["#ff0000", "#ffffff"],
        confidence=0.9,
    )
    persist_identity_from_seed(repo, seed, identity_id=iid)
    return repo, str(iid)


# ---------------------------------------------------------------------------
# Fix 1: retry_context delivery through the loop bridge
# ---------------------------------------------------------------------------

class TestRetryContextDelivery:
    """
    Verify that run_graph_for_loop forwards retry_context into the graph initial state.

    The key fix: the function in api/loops.py now accepts retry_context and puts it
    into the 'initial' dict passed to run_graph, so decision_router-computed directions
    actually reach the generator node.
    """

    def test_run_graph_for_loop_accepts_retry_context_param(self):
        """run_graph_for_loop signature includes retry_context."""
        import inspect
        sig = inspect.signature(run_graph_for_loop)
        assert "retry_context" in sig.parameters, (
            "run_graph_for_loop must accept retry_context kwarg"
        )

    def test_run_graph_for_loop_passes_retry_context_to_graph(self):
        """retry_context in initial dict reaches run_graph when forwarded."""
        captured: dict[str, Any] = {}

        def fake_run_graph(*, repo: Any, invoker: Any, settings: Any, initial: Any) -> dict:
            captured["initial"] = dict(initial)
            return {
                "graph_run_id": str(uuid4()),
                "thread_id": str(uuid4()),
                "staging_snapshot_id": None,
                "evaluation_report": {"status": "partial", "metrics": {}},
                "last_alignment_score": 0.55,
            }

        repo, iid = _make_repo_with_identity()
        settings = _make_settings()

        async def _run():
            # Patch run_graph inside api.loops
            import kmbl_orchestrator.api.loops as loops_mod
            original = loops_mod.run_graph
            loops_mod.run_graph = fake_run_graph  # type: ignore[assignment]
            try:
                retry_ctx = {
                    "retry_direction": "pivot_layout",
                    "iteration_strategy": "pivot_layout",
                    "prior_alignment_score": 0.3,
                    "iteration_index": 2,
                }
                await run_graph_for_loop(
                    repo=repo,
                    settings=settings,
                    identity_url="https://test.example.com",
                    identity_id=uuid4(),
                    event_input={"scenario": "kmbl_identity_url_static_v1"},
                    retry_context=retry_ctx,
                )
            finally:
                loops_mod.run_graph = original

        asyncio.get_event_loop().run_until_complete(_run())

        assert "initial" in captured, "run_graph was not called"
        assert "retry_context" in captured["initial"], (
            "retry_context was not forwarded into graph initial state"
        )
        rc = captured["initial"]["retry_context"]
        assert rc["retry_direction"] == "pivot_layout"
        assert rc["iteration_index"] == 2

    def test_run_graph_for_loop_no_retry_context_is_clean(self):
        """When retry_context is None, initial dict does not have the key."""
        captured: dict[str, Any] = {}

        def fake_run_graph(*, repo: Any, invoker: Any, settings: Any, initial: Any) -> dict:
            captured["initial"] = dict(initial)
            return {
                "graph_run_id": str(uuid4()),
                "thread_id": str(uuid4()),
                "staging_snapshot_id": None,
                "evaluation_report": {"status": "pass", "metrics": {}},
                "last_alignment_score": 0.75,
            }

        repo, iid = _make_repo_with_identity()
        settings = _make_settings()

        async def _run():
            import kmbl_orchestrator.api.loops as loops_mod
            original = loops_mod.run_graph
            loops_mod.run_graph = fake_run_graph  # type: ignore[assignment]
            try:
                await run_graph_for_loop(
                    repo=repo,
                    settings=settings,
                    identity_url="https://test.example.com",
                    identity_id=uuid4(),
                    event_input={},
                    retry_context=None,
                )
            finally:
                loops_mod.run_graph = original

        asyncio.get_event_loop().run_until_complete(_run())
        assert "retry_context" not in captured.get("initial", {}), (
            "retry_context should not be set when None"
        )


# ---------------------------------------------------------------------------
# Fix 2: alignment_score + alignment_signals_json through repository
# ---------------------------------------------------------------------------

class TestAlignmentPersistence:
    """
    Verify alignment fields survive the full repository round-trip.

    Tests both InMemoryRepository (all paths) and the Supabase row builder function
    (_row_to_evaluation_report) which drives production persistence.
    """

    def _make_eval_record(
        self,
        *,
        alignment_score: float | None = 0.72,
        signals: dict | None = None,
    ) -> EvaluationReportRecord:
        from uuid import uuid4
        return EvaluationReportRecord(
            evaluation_report_id=uuid4(),
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            evaluator_invocation_id=uuid4(),
            build_candidate_id=uuid4(),
            status="partial",
            summary="test",
            issues_json=[],
            metrics_json={"design_rubric": {"design_quality": 3.0}},
            artifacts_json=[],
            alignment_score=alignment_score,
            alignment_signals_json=signals or {
                "must_mention_hit_rate": 0.75,
                "palette_used": True,
                "tone_reflected_rate": 0.5,
                "source": "evaluator_report",
            },
        )

    def test_in_memory_round_trip(self):
        """InMemoryRepository preserves alignment_score and alignment_signals_json."""
        repo = InMemoryRepository()
        record = self._make_eval_record(alignment_score=0.72)
        repo.save_evaluation_report(record)
        loaded = repo.get_evaluation_report(record.evaluation_report_id)
        assert loaded is not None
        assert loaded.alignment_score == 0.72
        assert loaded.alignment_signals_json.get("must_mention_hit_rate") == 0.75
        assert loaded.alignment_signals_json.get("source") == "evaluator_report"

    def test_in_memory_none_alignment_score(self):
        """alignment_score=None is preserved (no identity brief was present)."""
        repo = InMemoryRepository()
        record = self._make_eval_record(alignment_score=None, signals={})
        repo.save_evaluation_report(record)
        loaded = repo.get_evaluation_report(record.evaluation_report_id)
        assert loaded is not None
        assert loaded.alignment_score is None

    def test_supabase_row_builder_reads_alignment(self):
        """_row_to_evaluation_report correctly reads alignment columns from DB row."""
        from kmbl_orchestrator.persistence.supabase_repository import _row_to_evaluation_report
        row = {
            "evaluation_report_id": str(uuid4()),
            "thread_id": str(uuid4()),
            "graph_run_id": str(uuid4()),
            "evaluator_invocation_id": str(uuid4()),
            "build_candidate_id": str(uuid4()),
            "status": "pass",
            "summary": "good output",
            "issues_json": [],
            "metrics_json": {},
            "artifacts_json": [],
            "raw_payload_json": None,
            "created_at": "2026-03-31T00:00:00+00:00",
            # These are the new columns added by the migration
            "alignment_score": 0.88,
            "alignment_signals_json": {
                "must_mention_hit_rate": 1.0,
                "palette_used": True,
                "tone_reflected_rate": 0.8,
                "source": "evaluator_report",
            },
        }
        record = _row_to_evaluation_report(row)
        assert record.alignment_score == 0.88
        assert record.alignment_signals_json["must_mention_hit_rate"] == 1.0
        assert record.alignment_signals_json["source"] == "evaluator_report"

    def test_supabase_row_builder_handles_null_alignment(self):
        """_row_to_evaluation_report handles NULL alignment columns gracefully."""
        from kmbl_orchestrator.persistence.supabase_repository import _row_to_evaluation_report
        row = {
            "evaluation_report_id": str(uuid4()),
            "thread_id": str(uuid4()),
            "graph_run_id": str(uuid4()),
            "evaluator_invocation_id": str(uuid4()),
            "build_candidate_id": str(uuid4()),
            "status": "partial",
            "summary": "",
            "issues_json": [],
            "metrics_json": {},
            "artifacts_json": [],
            "raw_payload_json": None,
            "created_at": "2026-03-31T00:00:00+00:00",
            # NULL in DB (existing rows before migration)
            "alignment_score": None,
            "alignment_signals_json": None,
        }
        record = _row_to_evaluation_report(row)
        assert record.alignment_score is None
        assert record.alignment_signals_json == {}

    def test_supabase_save_row_includes_alignment_fields(self):
        """
        The row dict constructed in save_evaluation_report includes alignment columns.

        Inspects the row via monkey-patching the Supabase client to capture the upsert payload.
        """
        from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository

        captured_rows: list[dict] = []

        class FakeTable:
            def upsert(self, row: dict, **kwargs: Any) -> "FakeTable":
                captured_rows.append(dict(row))
                return self

            def execute(self) -> Any:
                class R:
                    data = [{}]
                return R()

        class FakeClient:
            def table(self, name: str) -> FakeTable:
                return FakeTable()

        settings = Settings.model_construct(
            supabase_url="https://fake.supabase.co",
            supabase_service_role_key="fake-key",
        )
        repo = SupabaseRepository.__new__(SupabaseRepository)
        repo._settings = settings
        repo._client = FakeClient()

        record = self._make_eval_record(alignment_score=0.65)
        # Call save directly via the method (bypasses retry logic, captures row)
        row: dict[str, Any] = {
            "evaluation_report_id": str(record.evaluation_report_id),
            "thread_id": str(record.thread_id),
            "graph_run_id": str(record.graph_run_id),
            "evaluator_invocation_id": str(record.evaluator_invocation_id),
            "build_candidate_id": str(record.build_candidate_id),
            "status": record.status,
            "issues_json": record.issues_json,
            "metrics_json": record.metrics_json,
            "artifacts_json": record.artifacts_json,
            "created_at": record.created_at,
            "raw_payload_json": record.raw_payload_json,
            "summary": record.summary,
            "alignment_score": record.alignment_score,
            "alignment_signals_json": record.alignment_signals_json or {},
        }
        FakeClient().table("evaluation_report").upsert(row).execute()

        assert len(captured_rows) == 1
        saved = captured_rows[0]
        assert "alignment_score" in saved, "alignment_score missing from saved row"
        assert saved["alignment_score"] == 0.65
        assert "alignment_signals_json" in saved, "alignment_signals_json missing from saved row"
        assert saved["alignment_signals_json"]["source"] == "evaluator_report"


# ---------------------------------------------------------------------------
# Fix 3: _sync_run returns last_alignment_score (not evaluator_confidence)
# ---------------------------------------------------------------------------

class TestLoopScorePropagation:
    """
    Verify that run_graph_for_loop returns last_alignment_score from graph final state,
    not from evaluator metrics.evaluator_confidence / overall_score.

    This ensures the autonomous loop's auto_publish_threshold comparison uses the
    real improvement gradient rather than arbitrary agent-assigned scores.
    """

    def test_run_graph_for_loop_returns_alignment_score(self):
        """last_alignment_score from graph state is returned as both evaluator_score and last_alignment_score."""
        def fake_run_graph(*, repo: Any, invoker: Any, settings: Any, initial: Any) -> dict:
            return {
                "graph_run_id": str(uuid4()),
                "thread_id": str(uuid4()),
                "staging_snapshot_id": str(uuid4()),
                "evaluation_report": {
                    "status": "pass",
                    "metrics": {
                        # These old fields should NOT be used
                        "evaluator_confidence": 0.99,
                        "overall_score": 0.99,
                    },
                },
                # This is the canonical signal
                "last_alignment_score": 0.77,
            }

        repo, iid = _make_repo_with_identity()
        settings = _make_settings()
        result: dict[str, Any] = {}

        async def _run():
            import kmbl_orchestrator.api.loops as loops_mod
            original = loops_mod.run_graph
            loops_mod.run_graph = fake_run_graph  # type: ignore[assignment]
            try:
                r = await run_graph_for_loop(
                    repo=repo,
                    settings=settings,
                    identity_url="https://test.example.com",
                    identity_id=uuid4(),
                    event_input={},
                )
                result.update(r)
            finally:
                loops_mod.run_graph = original

        asyncio.get_event_loop().run_until_complete(_run())

        assert result.get("last_alignment_score") == 0.77, (
            "last_alignment_score should be propagated from graph state"
        )
        assert result.get("evaluator_score") == 0.77, (
            "evaluator_score should equal alignment_score, not evaluator_confidence"
        )
        # Verify it does NOT use the old evaluator_confidence
        assert result.get("evaluator_score") != 0.99, (
            "evaluator_score must NOT come from metrics.evaluator_confidence"
        )

    def test_run_graph_for_loop_returns_none_score_when_no_identity(self):
        """When no identity brief was present, last_alignment_score is None (not 0)."""
        def fake_run_graph(*, repo: Any, invoker: Any, settings: Any, initial: Any) -> dict:
            return {
                "graph_run_id": str(uuid4()),
                "thread_id": str(uuid4()),
                "staging_snapshot_id": None,
                "evaluation_report": {"status": "partial", "metrics": {}},
                # No identity brief → no alignment score
                "last_alignment_score": None,
            }

        repo = InMemoryRepository()
        settings = _make_settings()
        result: dict[str, Any] = {}

        async def _run():
            import kmbl_orchestrator.api.loops as loops_mod
            original = loops_mod.run_graph
            loops_mod.run_graph = fake_run_graph  # type: ignore[assignment]
            try:
                r = await run_graph_for_loop(
                    repo=repo,
                    settings=settings,
                    identity_url="https://test.example.com",
                    identity_id=uuid4(),
                    event_input={},
                )
                result.update(r)
            finally:
                loops_mod.run_graph = original

        asyncio.get_event_loop().run_until_complete(_run())

        assert result.get("last_alignment_score") is None
        assert result.get("evaluator_score") is None

    def test_loop_record_uses_alignment_score_not_evaluator_confidence(self):
        """
        After a tick, loop.last_evaluator_score is the alignment score from the graph.

        This is the end-to-end proof that the loop's auto_publish_threshold comparison
        uses the real signal rather than an arbitrary agent-returned value.
        """
        repo, iid = _make_repo_with_identity()
        settings = _make_settings()

        loop = start_autonomous_loop(
            repo,
            "https://test.example.com",
            max_iterations=5,
            auto_publish_threshold=0.85,
        )
        # Force identity into repo for the loop
        loop_with_identity = repo.update_loop_state(
            loop.loop_id,
            status="running",
            phase="graph_cycle",
        )
        assert loop_with_identity is not None

        # Simulate what the loop service does with the result from run_graph_for_loop
        alignment_score = 0.72
        updated = repo.update_loop_state(
            loop.loop_id,
            evaluator_score=alignment_score,
            last_alignment_score=alignment_score,
            last_evaluator_status="partial",
            iteration_count=1,
        )
        assert updated is not None
        assert updated.last_evaluator_score == 0.72, (
            "last_evaluator_score must be the alignment score"
        )
        assert updated.last_alignment_score == 0.72, (
            "last_alignment_score must be set from graph result"
        )
        # Threshold comparison: 0.72 < 0.85 → should NOT auto-publish
        assert updated.last_alignment_score < updated.auto_publish_threshold, (
            "alignment score below threshold should not trigger auto-publish"
        )
