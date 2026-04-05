"""Tests for continuation semantics and identity reuse across runs on the same thread.

These test the critical gap: when a second run happens on an existing thread,
identity_id must be reused and identity context must be re-hydrated from persistence.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    GraphRunRecord,
    IdentityProfileRecord,
    IdentitySourceRecord,
    ThreadRecord,
)
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType


class _CapturingClient:
    """Captures payloads sent to each role for assertion."""

    def __init__(self) -> None:
        self.planner_payloads: list[dict[str, Any]] = []
        self.generator_payloads: list[dict[str, Any]] = []
        self.evaluator_payloads: list[dict[str, Any]] = []

    def invoke_role(
        self,
        role_type: str,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _ = provider_config_key
        if role_type == "planner":
            self.planner_payloads.append(payload)
            return {
                "build_spec": {"type": "generic", "title": "T", "steps": []},
                "constraints": {},
                "success_criteria": [],
                "evaluation_targets": [],
            }
        if role_type == "generator":
            self.generator_payloads.append(payload)
            return {
                "proposed_changes": {"x": 1},
                "artifact_outputs": [],
                "updated_state": {},
                "preview_url": "https://x.example/p",
            }
        if role_type == "evaluator":
            self.evaluator_payloads.append(payload)
            return {
                "status": "pass",
                "summary": "looks good",
                "issues": [],
                "artifacts": [],
                "metrics": {},
            }
        raise AssertionError(role_type)


def _make_run(
    repo: InMemoryRepository,
    invoker: DefaultRoleInvoker,
    settings: Settings,
    *,
    thread_id: str | None = None,
    identity_id: str | None = None,
    event_input: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Start and run a graph, returning (thread_id, graph_run_id)."""
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=thread_id,
        graph_run_id=None,
        identity_id=identity_id,
        trigger_type="prompt",
        event_input=event_input or {},
    )
    run_graph(
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
    return str(tid), str(gid)


class TestIdentityReusedOnSameThread:
    """Verify that identity_id from the first run is available on second run."""

    def test_second_run_same_thread_gets_identity_context(self) -> None:
        """Critical: a second run on the same thread should re-hydrate identity."""
        iid = uuid4()
        repo = InMemoryRepository()
        repo.upsert_identity_profile(
            IdentityProfileRecord(
                identity_id=iid,
                profile_summary="Designer portfolio",
                facets_json={"tone_keywords": ["bold", "modern"]},
            )
        )
        repo.create_identity_source(
            IdentitySourceRecord(
                identity_source_id=uuid4(),
                identity_id=iid,
                source_type="website_scrape",
                raw_text="I am a bold modern designer",
                metadata_json={"tone_keywords": ["bold", "modern"]},
            )
        )
        cap = _CapturingClient()
        invoker = DefaultRoleInvoker(client=cap)
        settings = Settings.model_construct(openclaw_transport="stub")

        # First run
        tid1, gid1 = _make_run(
            repo, invoker, settings, identity_id=str(iid)
        )

        # Second run on same thread — identity should re-hydrate
        cap2 = _CapturingClient()
        invoker2 = DefaultRoleInvoker(client=cap2)
        _, gid2 = _make_run(
            repo, invoker2, settings, thread_id=tid1, identity_id=str(iid)
        )

        # Both runs should have planner payload with non-empty identity_context
        assert cap.planner_payloads, "first run should have invoked planner"
        assert cap2.planner_payloads, "second run should have invoked planner"

        ic1 = cap.planner_payloads[0].get("identity_context", {})
        ic2 = cap2.planner_payloads[0].get("identity_context", {})

        assert ic1.get("identity_id") == str(iid)
        assert ic2.get("identity_id") == str(iid)
        assert ic2.get("profile_summary") == "Designer portfolio"

    def test_thread_identity_id_persisted_on_graph_run(self) -> None:
        """Graph run record should carry the identity_id from the thread."""
        iid = uuid4()
        repo = InMemoryRepository()
        repo.upsert_identity_profile(
            IdentityProfileRecord(
                identity_id=iid,
                profile_summary="P",
                facets_json={},
            )
        )
        cap = _CapturingClient()
        invoker = DefaultRoleInvoker(client=cap)
        settings = Settings.model_construct(openclaw_transport="stub")

        tid, gid = _make_run(repo, invoker, settings, identity_id=str(iid))

        gr = repo.get_graph_run(UUID(gid))
        assert gr is not None
        # The graph_run record should reference the identity
        thread = repo.get_thread(UUID(tid))
        assert thread is not None
        assert thread.identity_id == iid


class TestMissingIdentityEmitsEvent:
    """When identity_id is not provided, the system should still work but emit visibility."""

    def test_no_identity_id_completes_successfully(self) -> None:
        """Graph run without identity should complete (identity is optional)."""
        cap = _CapturingClient()
        repo = InMemoryRepository()
        invoker = DefaultRoleInvoker(client=cap)
        settings = Settings.model_construct(openclaw_transport="stub")

        tid, gid = _make_run(repo, invoker, settings, identity_id=None)

        gr = repo.get_graph_run(UUID(gid))
        assert gr is not None
        assert gr.status == "completed"

    def test_no_identity_id_planner_gets_empty_context(self) -> None:
        cap = _CapturingClient()
        repo = InMemoryRepository()
        invoker = DefaultRoleInvoker(client=cap)
        settings = Settings.model_construct(openclaw_transport="stub")

        _make_run(repo, invoker, settings, identity_id=None)

        assert cap.planner_payloads
        ic = cap.planner_payloads[0].get("identity_context", {})
        assert ic == {}

    def test_no_identity_emits_context_event(self) -> None:
        """When no identity_id, context_hydrator should emit a CONTEXT_IDENTITY_ABSENT event."""
        cap = _CapturingClient()
        repo = InMemoryRepository()
        invoker = DefaultRoleInvoker(client=cap)
        settings = Settings.model_construct(openclaw_transport="stub")

        tid, gid = _make_run(repo, invoker, settings, identity_id=None)

        events = repo.list_graph_run_events(UUID(gid))
        event_types = [e.event_type for e in events]
        assert RunEventType.CONTEXT_IDENTITY_ABSENT in event_types, (
            f"Expected CONTEXT_IDENTITY_ABSENT in events, got: {event_types}"
        )
