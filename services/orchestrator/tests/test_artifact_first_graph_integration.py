"""Graph integration checks for artifact-first staging (requires langgraph)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytest.importorskip("langgraph")

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType


class _PartialEval:
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
                "proposed_changes": {},
                "artifact_outputs": [
                    {
                        "path": "index.html",
                        "role": "entry",
                        "content": "<!doctype html><html><body>hi</body></html>",
                    }
                ],
                "updated_state": {},
                "preview_url": "https://preview.example/x",
            }
        if role_type == "evaluator":
            return {
                "status": "partial",
                "summary": "needs polish",
                "issues": [{"code": "x"}],
                "artifacts": [],
                "metrics": {},
            }
        raise AssertionError(role_type)


def test_always_partial_skips_staging_snapshot_by_default() -> None:
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=_PartialEval())
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="always",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
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
    assert repo.list_staging_snapshots_for_thread(UUID(tid), limit=5) == []
    evs = repo.list_graph_run_events(UUID(gid), limit=200)
    skipped = [e for e in evs if e.event_type == RunEventType.STAGING_SNAPSHOT_SKIPPED]
    assert skipped
    assert skipped[-1].payload_json.get("skip_reason") == "always_partial_excluded_default"


def test_always_partial_creates_snapshot_when_flag_enabled() -> None:
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=_PartialEval())
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="always",
        kmbl_staging_snapshot_always_include_partial=True,
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
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
    snaps = repo.list_staging_snapshots_for_thread(UUID(tid), limit=5)
    assert snaps


def test_stub_pass_first_generator_save_is_wire_compact() -> None:
    """Earliest durable generator save must be compact (not only the post-normalization save)."""
    repo = InMemoryRepository()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="always",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    invoker = DefaultRoleInvoker(settings=settings)
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
    invs = [
        r
        for r in repo.list_role_invocations_for_graph_run(UUID(gid))
        if r.role_type == "generator"
    ]
    assert invs
    first = invs[0]
    ao0 = (first.output_payload_json or {}).get("artifact_outputs")
    assert isinstance(ao0, list) and ao0
    assert "content" not in ao0[0]
    assert ao0[0].get("content_omitted") is True
    ps = (first.routing_metadata_json or {}).get("kmbl_generator_persistence_shape_v1") or {}
    assert ps.get("wire_compacted") is True
    assert ps.get("first_durable_save_pre_normalize") is True


def test_debug_flag_persists_raw_on_generator_invocations() -> None:
    repo = InMemoryRepository()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="always",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
        kmbl_persist_raw_generator_output_for_debug=True,
    )
    invoker = DefaultRoleInvoker(settings=settings)
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
    invs = [
        r
        for r in repo.list_role_invocations_for_graph_run(UUID(gid))
        if r.role_type == "generator"
    ]
    assert invs
    first = invs[0]
    ao0 = (first.output_payload_json or {}).get("artifact_outputs")
    assert isinstance(ao0, list) and ao0
    assert isinstance(ao0[0].get("content"), str) and len(ao0[0]["content"]) > 20
    wc = (first.routing_metadata_json or {}).get("kmbl_generator_wire_compaction_v1") or {}
    assert wc.get("skipped") is True
    bc = repo.get_latest_build_candidate_for_graph_run(UUID(gid))
    assert bc is not None
    assert len((bc.artifact_refs_json or [{}])[0].get("content", "")) > 20


def test_stub_pass_generator_invocation_final_output_is_wire_compact() -> None:
    repo = InMemoryRepository()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="always",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    invoker = DefaultRoleInvoker(settings=settings)
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
    invs = [
        r
        for r in repo.list_role_invocations_for_graph_run(UUID(gid))
        if r.role_type == "generator"
    ]
    assert invs
    last = invs[-1]
    out = last.output_payload_json or {}
    ao = out.get("artifact_outputs")
    assert isinstance(ao, list) and ao
    assert "content" not in ao[0]
    assert ao[0].get("content_omitted") is True
    wc = (last.routing_metadata_json or {}).get("kmbl_generator_wire_compaction_v1") or {}
    assert wc and wc.get("skipped") is not True
    bc = repo.get_latest_build_candidate_for_graph_run(UUID(gid))
    assert bc is not None
    full = list(bc.artifact_refs_json or [])
    assert full and isinstance(full[0].get("content"), str) and len(full[0]["content"]) > 50


def test_evaluator_stub_payload_omits_snippets_when_preview_grounded() -> None:
    captured: list[dict[str, Any]] = []
    repo = InMemoryRepository()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        staging_snapshot_policy="on_nomination",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    invoker = DefaultRoleInvoker(settings=settings)
    orig = DefaultRoleInvoker.invoke

    def _cap(self: Any, **kwargs: Any):
        if kwargs.get("role_type") == "evaluator":
            captured.append(dict(kwargs.get("input_payload") or {}))
        return orig(self, **kwargs)

    DefaultRoleInvoker.invoke = _cap  # type: ignore[method-assign]
    try:
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
    finally:
        DefaultRoleInvoker.invoke = orig  # type: ignore[method-assign]

    assert captured
    payload = captured[0]
    assert "kmbl_evaluator_artifact_snippets_v1" not in payload
    assert "kmbl_evaluator_artifact_snippets_v1" not in (payload.get("build_candidate") or {})
    ev_invs = [
        r
        for r in repo.list_role_invocations_for_graph_run(UUID(gid))
        if r.role_type == "evaluator" and r.status == "completed"
    ]
    assert ev_invs
    tel = (ev_invs[-1].routing_metadata_json or {}).get("kmbl_payload_telemetry_v1") or {}
    pol = tel.get("kmbl_evaluator_snippet_policy_v1") or {}
    assert pol.get("snippets_suppressed_for_llm") is True
    assert pol.get("reason_code") == "summary_v2_preview_grounding_sufficient"
