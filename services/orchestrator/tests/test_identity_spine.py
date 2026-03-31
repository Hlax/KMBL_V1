"""Minimal identity spine: persistence, hydration, planner payload."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import (
    IdentityProfileRecord,
    IdentitySourceRecord,
)
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.identity.hydrate import build_planner_identity_context
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def test_identity_source_and_profile_roundtrip() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    sid = uuid4()
    repo.create_identity_source(
        IdentitySourceRecord(
            identity_source_id=sid,
            identity_id=iid,
            source_type="text",
            raw_text="hello world",
            metadata_json={"k": 1},
        )
    )
    rows = repo.list_identity_sources(iid)
    assert len(rows) == 1
    assert rows[0].raw_text == "hello world"
    repo.upsert_identity_profile(
        IdentityProfileRecord(
            identity_id=iid,
            profile_summary="A test profile",
            facets_json={"voice": "calm"},
            open_questions_json=["q1"],
        )
    )
    p = repo.get_identity_profile(iid)
    assert p is not None
    assert p.profile_summary == "A test profile"
    assert p.facets_json.get("voice") == "calm"


def test_hydrate_includes_counts_and_profile() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    repo.create_identity_source(
        IdentitySourceRecord(
            identity_source_id=uuid4(),
            identity_id=iid,
            source_type="note",
            raw_text="alpha",
        )
    )
    repo.upsert_identity_profile(
        IdentityProfileRecord(
            identity_id=iid,
            profile_summary="S",
            facets_json={"a": 1},
        )
    )
    ctx = build_planner_identity_context(repo, iid)
    assert ctx["identity_id"] == str(iid)
    assert ctx["profile_summary"] == "S"
    assert ctx["source_count"] == 1
    assert len(ctx["recent_source_summaries"]) == 1
    assert ctx["facets_json"]["a"] == 1


def test_hydrate_empty_without_identity() -> None:
    repo = InMemoryRepository()
    assert build_planner_identity_context(repo, None) == {}


def test_hydrate_identity_unresolved_without_fallback() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    s = Settings.model_construct(identity_allow_fallback_profile=False)
    ctx = build_planner_identity_context(repo, iid, settings=s)
    assert ctx.get("identity_unresolved") is True
    assert ctx.get("identity_unresolved_reason") == "no_profile_or_facets"


def test_run_without_identity_id_empty_identity_context() -> None:
    class Cap:
        def __init__(self) -> None:
            self.last_planner_payload: dict[str, Any] | None = None

        def invoke_role(
            self,
            role_type: str,
            provider_config_key: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            _ = provider_config_key
            if role_type == "planner":
                self.last_planner_payload = payload
                return {
                    "build_spec": {"type": "generic", "title": "T", "steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {"x": 1},
                    "artifact_outputs": [],
                    "updated_state": {},
                    "preview_url": "https://x.example/p",
                }
            if role_type == "evaluator":
                return {
                    "status": "pass",
                    "summary": "",
                    "issues": [],
                    "artifacts": [],
                    "metrics": {},
                }
            raise AssertionError(role_type)

    cap = Cap()
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=cap)
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={"thread_id": tid, "graph_run_id": gid, "event_input": {}},
    )
    assert cap.last_planner_payload is not None
    assert cap.last_planner_payload.get("identity_context") == {}


def test_run_with_identity_id_planner_gets_hydrated_context() -> None:
    iid = uuid4()

    class Cap:
        def __init__(self) -> None:
            self.last_planner_payload: dict[str, Any] | None = None

        def invoke_role(
            self,
            role_type: str,
            provider_config_key: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            _ = provider_config_key
            if role_type == "planner":
                self.last_planner_payload = payload
                return {
                    "build_spec": {"type": "generic", "title": "T", "steps": []},
                    "constraints": {},
                    "success_criteria": [],
                    "evaluation_targets": [],
                }
            if role_type == "generator":
                return {
                    "proposed_changes": {"x": 1},
                    "artifact_outputs": [],
                    "updated_state": {},
                    "preview_url": "https://x.example/p",
                }
            if role_type == "evaluator":
                return {
                    "status": "pass",
                    "summary": "",
                    "issues": [],
                    "artifacts": [],
                    "metrics": {},
                }
            raise AssertionError(role_type)

    cap = Cap()
    repo = InMemoryRepository()
    repo.upsert_identity_profile(
        IdentityProfileRecord(
            identity_id=iid,
            profile_summary="Hello identity",
            facets_json={"tone": "warm"},
        )
    )
    invoker = DefaultRoleInvoker(client=cap)
    settings = Settings.model_construct(kiloclaw_transport="stub")
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=str(iid),
        trigger_type="prompt",
        event_input={},
    )
    run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid,
            "graph_run_id": gid,
            "identity_id": str(iid),
            "event_input": {},
        },
    )
    assert cap.last_planner_payload is not None
    ic = cap.last_planner_payload.get("identity_context")
    assert isinstance(ic, dict)
    assert ic.get("identity_id") == str(iid)
    assert ic.get("profile_summary") == "Hello identity"
    assert ic.get("facets_json", {}).get("tone") == "warm"
    gr = repo.get_graph_run(UUID(gid))
    assert gr is not None
    assert gr.identity_id == iid
    invs = repo.list_role_invocations_for_graph_run(UUID(gid))
    planner = next(r for r in invs if r.role_type == "planner")
    assert (planner.input_payload_json or {}).get("identity_context", {}).get(
        "identity_id"
    ) == str(iid)


def test_graph_run_persisted_identity_matches_thread() -> None:
    repo = InMemoryRepository()
    iid = uuid4()
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=str(iid),
        trigger_type="prompt",
        event_input={},
    )
    th = repo.get_thread(UUID(tid))
    assert th is not None and th.identity_id == iid
    gr = repo.get_graph_run(UUID(gid))
    assert gr is not None and gr.identity_id == iid
