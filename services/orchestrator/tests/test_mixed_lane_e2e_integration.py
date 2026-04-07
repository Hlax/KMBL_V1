"""End-to-end planner->generator->evaluator mixed-lane routing checks."""

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


class _ScriptedMixedLaneClient:
    def __init__(self) -> None:
        self.generator_calls = 0

    def invoke_role(self, role_type: str, provider_config_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        _ = provider_config_key
        if role_type == "planner":
            return {
                "build_spec": {
                    "type": "interactive_frontend_app_v1",
                    "title": "mixed lane test",
                    "steps": [{"title": "build", "description": "ship interactive scene"}],
                    "experience_mode": "immersive_identity_experience",
                    "execution_contract": {
                        "lane_mix": {
                            "primary_lane": "spatial_gallery",
                            "secondary_lanes": ["editorial_story"],
                            "lane_mix_policy": "bounded_blend",
                        },
                        "canvas_system": {
                            "media_modes": ["image", "captioned"],
                        },
                        "allowed_libraries": ["three"],
                    },
                },
                "constraints": {"canonical_vertical": "interactive_frontend_app_v1"},
                "success_criteria": ["lane mix is visible"],
                "evaluation_targets": [{"kind": "artifact_role", "value": "interactive_frontend_app_v1"}],
            }

        if role_type == "generator":
            self.generator_calls += 1
            if self.generator_calls == 1:
                # First attempt: misses secondary lane evidence and should trigger iterate.
                html = (
                    "<html><head><script src='https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js'></script></head>"
                    "<body><canvas></canvas><h1>Gallery</h1></body></html>"
                )
            else:
                # Second attempt: adds narrative/story signals for secondary lane.
                html = (
                    "<html><head><script src='https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js'></script></head>"
                    "<body><canvas></canvas><section><h2>Story Chapter</h2>"
                    "<article>Narrative beat</article><figure><img src='https://cdn.example.com/i.jpg' /></figure>"
                    "</section></body></html>"
                )
            return {
                "proposed_changes": {"summary": "scripted"},
                "artifact_outputs": [
                    {
                        "role": "interactive_frontend_app_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": html,
                        "entry_for_preview": True,
                    }
                ],
                "updated_state": {"ok": True},
            }

        if role_type == "evaluator":
            # Deterministic evaluator gates do the lane-mix enforcement.
            return {
                "status": "pass",
                "summary": "llm pass",
                "issues": [],
                "artifacts": [],
                "metrics": {},
            }

        raise AssertionError(role_type)


def test_mixed_lane_fail_iterate_then_stage_e2e() -> None:
    repo = InMemoryRepository()
    client = _ScriptedMixedLaneClient()
    invoker = DefaultRoleInvoker(client=client)
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=2,
        habitat_image_generation_enabled=False,
        staging_snapshot_policy="always",
    )

    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={"thread_id": tid, "graph_run_id": gid, "event_input": {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}},
    )

    assert final.get("decision") == "stage"
    assert client.generator_calls >= 2

    ev_rows = repo.list_evaluation_reports_for_graph_run(UUID(gid), limit=10)
    assert len(ev_rows) >= 2
    first_codes = {str(i.get("code")) for i in (ev_rows[0].issues_json or []) if isinstance(i, dict)}
    assert "lane_mix_mismatch" in first_codes

    evs = repo.list_graph_run_events(UUID(gid), limit=200)
    decision_evs = [e for e in evs if e.event_type == RunEventType.DECISION_MADE]
    assert len(decision_evs) >= 2
    first_policy = (decision_evs[0].payload_json or {}).get("mixed_lane_failure_policy_v1") or {}
    assert first_policy.get("route") in ("iterate", "pivot")
    assert "lane_mix_mismatch" in (first_policy.get("matched_codes") or [])


class _ScriptedMixedLaneSuccessClient:
    def invoke_role(self, role_type: str, provider_config_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        _ = provider_config_key
        if role_type == "planner":
            return {
                "build_spec": {
                    "type": "interactive_frontend_app_v1",
                    "title": "mixed lane success",
                    "steps": [{"title": "build", "description": "ship interactive scene"}],
                    "execution_contract": {
                        "lane_mix": {
                            "primary_lane": "spatial_gallery",
                            "secondary_lanes": ["editorial_story"],
                        },
                        "canvas_system": {"media_modes": ["image"]},
                        "allowed_libraries": ["three"],
                    },
                },
                "constraints": {"canonical_vertical": "interactive_frontend_app_v1"},
                "success_criteria": ["lane mix and media present"],
                "evaluation_targets": [{"kind": "artifact_role", "value": "interactive_frontend_app_v1"}],
            }
        if role_type == "generator":
            return {
                "proposed_changes": {"summary": "scripted"},
                "artifact_outputs": [
                    {
                        "role": "interactive_frontend_app_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": "<html><head><script src='https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js'></script></head><body><canvas></canvas><section><h2>Story</h2><article>Narrative</article><img src='https://cdn.example.com/i.jpg' /></section></body></html>",
                        "entry_for_preview": True,
                    }
                ],
                "updated_state": {"ok": True},
            }
        if role_type == "evaluator":
            return {
                "status": "pass",
                "summary": "llm pass",
                "issues": [],
                "artifacts": [],
                "metrics": {},
            }
        raise AssertionError(role_type)


def test_mixed_lane_success_stages_e2e() -> None:
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(client=_ScriptedMixedLaneSuccessClient())
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
        staging_snapshot_policy="always",
    )
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={"thread_id": tid, "graph_run_id": gid, "event_input": {"constraints": {"canonical_vertical": "interactive_frontend_app_v1"}}},
    )
    assert final.get("decision") == "stage"
