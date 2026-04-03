"""Tests for DEGRADED_STAGING event emission and detail read model failure_info / last_meaningful_event."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    BuildCandidateRecord,
    BuildSpecRecord,
    CheckpointRecord,
    EvaluationReportRecord,
    GraphRunEventRecord,
    GraphRunRecord,
    IdentityProfileRecord,
    RoleInvocationRecord,
    StagingSnapshotRecord,
    ThreadRecord,
)
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.graph_run_detail_read_model import (
    build_graph_run_detail_read_model,
)
from kmbl_orchestrator.runtime.run_events import RunEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _IteratingClient:
    """Returns partial/fail from evaluator to force iteration, then eventually pass or exhaust."""

    def __init__(self, *, evaluator_status: str = "partial", max_pass_at: int | None = None) -> None:
        self._eval_status = evaluator_status
        self._max_pass_at = max_pass_at
        self._eval_count = 0

    def invoke_role(self, role_type: str, provider_config_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        _ = provider_config_key
        if role_type == "planner":
            return {
                "build_spec": {"type": "generic", "title": "T", "steps": []},
                "constraints": {},
                "success_criteria": [],
                "evaluation_targets": [],
            }
        if role_type == "generator":
            return {
                "proposed_changes": {"x": self._eval_count},
                "artifact_outputs": [],
                "updated_state": {},
                "preview_url": "https://x.example/p",
            }
        if role_type == "evaluator":
            self._eval_count += 1
            status = self._eval_status
            if self._max_pass_at is not None and self._eval_count >= self._max_pass_at:
                status = "pass"
            return {
                "status": status,
                "summary": f"eval #{self._eval_count}",
                "issues": [{"type": "style"}] if status != "pass" else [],
                "artifacts": [],
                "metrics": {},
            }
        raise AssertionError(role_type)


# ---------------------------------------------------------------------------
# DEGRADED_STAGING event tests
# ---------------------------------------------------------------------------


class TestDegradedStagingEvent:
    def test_partial_at_max_iterations_emits_degraded_staging(self) -> None:
        """When evaluator returns 'partial' and we exhaust max_iterations, DEGRADED_STAGING must appear."""
        repo = InMemoryRepository()
        client = _IteratingClient(evaluator_status="partial")
        invoker = DefaultRoleInvoker(client=client)
        settings = Settings.model_construct(
            kiloclaw_transport="stub",
            graph_max_iterations_default=1,  # Only 1 retry allowed
        )
        tid, gid = persist_graph_run_start(
            repo, thread_id=None, graph_run_id=None,
            identity_id=None, trigger_type="prompt", event_input={},
        )
        run_graph(
            repo=repo, invoker=invoker, settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
        events = repo.list_graph_run_events(UUID(gid))
        event_types = [e.event_type for e in events]
        assert RunEventType.DEGRADED_STAGING in event_types, (
            f"Expected DEGRADED_STAGING in events, got: {event_types}"
        )
        degraded = next(e for e in events if e.event_type == RunEventType.DEGRADED_STAGING)
        payload = degraded.payload_json
        assert payload["evaluation_status"] == "partial"
        assert "max iterations" in payload["message"].lower() or "max_iterations" in payload["message"]

    def test_pass_does_not_emit_degraded_staging(self) -> None:
        """A clean pass should NOT emit DEGRADED_STAGING."""
        repo = InMemoryRepository()
        client = _IteratingClient(evaluator_status="pass")
        invoker = DefaultRoleInvoker(client=client)
        settings = Settings.model_construct(kiloclaw_transport="stub")
        tid, gid = persist_graph_run_start(
            repo, thread_id=None, graph_run_id=None,
            identity_id=None, trigger_type="prompt", event_input={},
        )
        run_graph(
            repo=repo, invoker=invoker, settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
        events = repo.list_graph_run_events(UUID(gid))
        event_types = [e.event_type for e in events]
        assert RunEventType.DEGRADED_STAGING not in event_types

    def test_fail_at_max_iterations_emits_degraded_staging(self) -> None:
        """Evaluator 'fail' at max iterations should also emit DEGRADED_STAGING."""
        repo = InMemoryRepository()
        client = _IteratingClient(evaluator_status="fail")
        invoker = DefaultRoleInvoker(client=client)
        settings = Settings.model_construct(
            kiloclaw_transport="stub",
            graph_max_iterations_default=1,
        )
        tid, gid = persist_graph_run_start(
            repo, thread_id=None, graph_run_id=None,
            identity_id=None, trigger_type="prompt", event_input={},
        )
        run_graph(
            repo=repo, invoker=invoker, settings=settings,
            initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
        )
        events = repo.list_graph_run_events(UUID(gid))
        event_types = [e.event_type for e in events]
        assert RunEventType.DEGRADED_STAGING in event_types


# ---------------------------------------------------------------------------
# Detail read model — failure_info and last_meaningful_event
# ---------------------------------------------------------------------------


class TestDetailReadModelFailureInfo:
    def _make_detail(
        self,
        *,
        status: str = "completed",
        invocations: list[RoleInvocationRecord] | None = None,
        events: list[GraphRunEventRecord] | None = None,
    ) -> dict[str, Any]:
        tid = uuid4()
        gid = uuid4()
        gr = GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status=status,
            started_at="2026-01-01T00:00:00+00:00",
        )
        thread = ThreadRecord(thread_id=tid, thread_kind="build", status="active")
        return build_graph_run_detail_read_model(
            thread=thread,
            gr=gr,
            invocations=invocations or [],
            staging_rows=[],
            publications=[],
            events=events or [],
            latest_checkpoint=None,
            has_interrupt_signal=False,
            bs=None,
            bc=None,
            ev=None,
        )

    def test_completed_run_has_null_failure_info(self) -> None:
        detail = self._make_detail(status="completed")
        fi = detail["failure_info"]
        assert fi["failure_phase"] is None
        assert fi["error_kind"] is None
        assert fi["error_message"] is None

    def test_failed_run_with_role_invocation_shows_phase(self) -> None:
        tid = uuid4()
        gid = uuid4()
        inv = RoleInvocationRecord(
            role_invocation_id=uuid4(),
            graph_run_id=gid,
            thread_id=tid,
            role_type="generator",
            status="failed",
            iteration_index=0,
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:00:01+00:00",
            provider_config_key="stub",
            input_payload_json={},
            output_payload_json={
                "error_kind": "provider_error",
                "message": "KiloClaw timed out",
            },
        )
        gr = GraphRunRecord(
            graph_run_id=gid, thread_id=tid, trigger_type="prompt",
            status="failed", started_at="2026-01-01T00:00:00+00:00",
        )
        thread = ThreadRecord(thread_id=tid, thread_kind="build", status="active")
        detail = build_graph_run_detail_read_model(
            thread=thread, gr=gr, invocations=[inv],
            staging_rows=[], publications=[],
            events=[], latest_checkpoint=None,
            has_interrupt_signal=False, bs=None, bc=None, ev=None,
        )
        fi = detail["failure_info"]
        assert fi["failure_phase"] == "generator"
        assert fi["error_kind"] == "provider_error"
        assert "timed out" in fi["error_message"].lower()

    def test_failed_run_without_invocation_uses_event(self) -> None:
        tid = uuid4()
        gid = uuid4()
        ev = GraphRunEventRecord(
            graph_run_event_id=uuid4(),
            graph_run_id=gid,
            thread_id=tid,
            event_type=RunEventType.GRAPH_RUN_FAILED,
            payload_json={"error_kind": "staging_integrity", "phase": "evaluator", "error_message": "preview missing"},
        )
        detail = self._make_detail(status="failed", events=[ev])
        fi = detail["failure_info"]
        assert fi["error_kind"] == "staging_integrity"
        assert fi["failure_phase"] == "evaluator"

    def test_last_meaningful_event_populated(self) -> None:
        gid = uuid4()
        ev1 = GraphRunEventRecord(
            graph_run_event_id=uuid4(), graph_run_id=gid,
            event_type=RunEventType.GRAPH_RUN_STARTED,
            payload_json={},
            created_at="2026-01-01T00:00:00+00:00",
        )
        ev2 = GraphRunEventRecord(
            graph_run_event_id=uuid4(), graph_run_id=gid,
            event_type=RunEventType.DECISION_MADE,
            payload_json={"decision": "stage"},
            created_at="2026-01-01T00:00:05+00:00",
        )
        detail = self._make_detail(events=[ev1, ev2])
        lme = detail["last_meaningful_event"]
        assert lme is not None
        assert lme["event_type"] == RunEventType.DECISION_MADE
        assert lme["payload"]["decision"] == "stage"

    def test_no_meaningful_events_returns_none(self) -> None:
        gid = uuid4()
        ev = GraphRunEventRecord(
            graph_run_event_id=uuid4(), graph_run_id=gid,
            event_type="some_random_internal_event",
            payload_json={},
        )
        detail = self._make_detail(events=[ev])
        assert detail["last_meaningful_event"] is None
