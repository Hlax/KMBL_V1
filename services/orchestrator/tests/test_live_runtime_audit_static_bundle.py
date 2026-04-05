"""
Live graph wiring audit (stub transport): static bundle rejection terminates at generator.

Proves the session_3-hardened path does not reach evaluator or emit generic evaluator prose
when the model returns checklist-only output for the static vertical.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw_parsing import _apply_role_contract
from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType


def _planner_static_vertical() -> dict:
    return _apply_role_contract(
        "planner",
        {
            "build_spec": {
                "type": "static_frontend_file_v1",
                "title": "live_audit",
                "experience_mode": "flat_editorial_static",
            },
            "success_criteria": ["has_html"],
            "evaluation_targets": ["smoke"],
        },
    )


def _generator_checklist_only() -> dict:
    return _apply_role_contract(
        "generator",
        {
            "proposed_changes": {"checklist_steps": [{"title": "planning_only"}]},
            "artifact_outputs": None,
            "updated_state": {},
        },
    )


def test_static_bundle_rejection_emits_sequence_and_never_invokes_evaluator() -> None:
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=3,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    invoked: dict[str, int] = {"evaluator": 0}

    orig = KiloClawStubClient.invoke_role

    def wrapped(self, role_type, provider_config_key, payload):  # type: ignore[no-untyped-def]
        if role_type == "planner":
            return _planner_static_vertical()
        if role_type == "generator":
            return _generator_checklist_only()
        if role_type == "evaluator":
            invoked["evaluator"] += 1
            return orig(self, role_type, provider_config_key, payload)
        return orig(self, role_type, provider_config_key, payload)

    static_constraints = {"constraints": {"canonical_vertical": "static_frontend_file_v1"}}
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input=static_constraints,
    )

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        with pytest.raises(RoleInvocationFailed) as excinfo:
            run_graph(
                repo=repo,
                invoker=invoker,
                settings=settings,
                initial={
                    "thread_id": tid,
                    "graph_run_id": gid,
                    "event_input": static_constraints,
                },
            )
    assert excinfo.value.phase == "generator"
    assert invoked["evaluator"] == 0

    gr = repo.get_graph_run(UUID(gid))
    assert gr is not None
    assert gr.status == "failed"

    evs = repo.list_graph_run_events(UUID(gid), limit=300)
    types_in_order = [e.event_type for e in evs]

    assert RunEventType.GENERATOR_STATIC_BUNDLE_REJECTED in types_in_order
    assert RunEventType.GRAPH_RUN_FAILED in types_in_order
    assert RunEventType.EVALUATOR_INVOCATION_STARTED not in types_in_order

    gen_idx = types_in_order.index(RunEventType.GENERATOR_STATIC_BUNDLE_REJECTED)
    fail_idx = types_in_order.index(RunEventType.GRAPH_RUN_FAILED)
    assert gen_idx < fail_idx, "rejection should be recorded before graph_run_failed"

    rej_ev = next(e for e in evs if e.event_type == RunEventType.GENERATOR_STATIC_BUNDLE_REJECTED)
    assert rej_ev.payload_json.get("output_class") == "planner_drift_checklist_without_artifacts"

    failed_ev = next(e for e in evs if e.event_type == RunEventType.GRAPH_RUN_FAILED)
    pj = failed_ev.payload_json
    assert pj.get("phase") == "generator"
    assert pj.get("static_frontend_bundle_gate") is True
    assert pj.get("output_class") == "planner_drift_checklist_without_artifacts"
    assert "message_preview" in pj
    assert "artifact_outputs" in (pj.get("message_preview") or "")


def test_stub_success_path_still_reaches_staging() -> None:
    """Control: default stub pipeline completes (valid HTML bundle → evaluator → staging)."""
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=3,
        habitat_image_generation_enabled=False,
        staging_snapshot_policy="always",
    )
    repo = InMemoryRepository()
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
    assert repo.get_graph_run(UUID(gid)).status == "completed"
    assert repo.list_staging_snapshots_for_thread(UUID(tid), limit=3)
