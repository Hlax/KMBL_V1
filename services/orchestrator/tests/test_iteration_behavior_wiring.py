"""
Wiring for iteration behavior: identity_url → planner, preview_url → evaluator,
previous_evaluation_report on later iterations. No Playwright simulation.
"""

from __future__ import annotations

from unittest.mock import patch

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw import KiloClawStubClient
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.session_staging_links import resolve_evaluator_preview_url


def test_resolve_evaluator_preview_url_prefers_orchestrator() -> None:
    s = Settings(orchestrator_public_base_url="http://127.0.0.1:8010")
    u = resolve_evaluator_preview_url(
        s,
        graph_run_id="g1",
        thread_id="t1",
        build_candidate={"preview_url": "https://candidate.example/preview"},
    )
    assert u == "http://127.0.0.1:8010/orchestrator/runs/g1/staging-preview"


def test_resolve_evaluator_preview_url_falls_back_to_candidate() -> None:
    s = Settings()
    u = resolve_evaluator_preview_url(
        s,
        graph_run_id="g1",
        thread_id="t1",
        build_candidate={"preview_url": "https://candidate.example/preview"},
    )
    assert u == "https://candidate.example/preview"


def test_evaluator_payload_includes_preview_and_iteration_context() -> None:
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=3,
        orchestrator_public_base_url="http://127.0.0.1:8010",
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    payloads: list[dict] = []

    orig = KiloClawStubClient.invoke_role

    def wrapped(self: KiloClawStubClient, role_type, provider_config_key, payload):  # type: ignore[no-untyped-def]
        if role_type == "evaluator":
            payloads.append(dict(payload))
        return orig(self, role_type, provider_config_key, payload)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        tid_s, gid_s = persist_graph_run_start(
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
            initial={
                "thread_id": tid_s,
                "graph_run_id": gid_s,
                "event_input": {},
            },
        )

    assert len(payloads) >= 2
    assert payloads[0]["preview_url"] == (
        f"http://127.0.0.1:8010/orchestrator/runs/{gid_s}/staging-preview"
    )
    assert payloads[0]["iteration_context"]["iteration_index"] == 0
    assert payloads[0]["iteration_context"]["has_previous_evaluation_report"] is False
    assert payloads[0].get("previous_evaluation_report") is None

    assert payloads[1]["iteration_context"]["iteration_index"] == 1
    assert payloads[1]["iteration_context"]["has_previous_evaluation_report"] is True
    assert isinstance(payloads[1].get("previous_evaluation_report"), dict)


def test_planner_payload_includes_identity_url() -> None:
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    seen: dict | None = None

    orig = KiloClawStubClient.invoke_role

    def wrapped(self: KiloClawStubClient, role_type, provider_config_key, payload):  # type: ignore[no-untyped-def]
        nonlocal seen
        if role_type == "planner":
            seen = dict(payload)
        return orig(self, role_type, provider_config_key, payload)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        tid_s, gid_s = persist_graph_run_start(
            repo,
            thread_id=None,
            graph_run_id=None,
            identity_id=None,
            trigger_type="prompt",
            event_input={"identity_url": "https://identity.example.com/"},
        )
        run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": tid_s,
                "graph_run_id": gid_s,
                "event_input": {"identity_url": "https://identity.example.com/"},
            },
        )

    assert seen is not None
    assert seen.get("identity_url") == "https://identity.example.com/"


def test_stub_persisted_build_spec_has_site_archetype() -> None:
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    tid_s, gid_s = persist_graph_run_start(
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
        initial={
            "thread_id": tid_s,
            "graph_run_id": gid_s,
            "event_input": {},
        },
    )
    from uuid import UUID

    gr = repo.get_graph_run(UUID(gid_s))
    assert gr is not None
    spec = repo.get_latest_build_spec_for_graph_run(UUID(gid_s))
    assert spec is not None
    raw = spec.raw_payload_json or {}
    bs = raw.get("build_spec") or {}
    assert bs.get("site_archetype") == "editorial"


def test_stub_generator_persists_primary_move_metadata() -> None:
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=1,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    tid_s, gid_s = persist_graph_run_start(
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
        initial={
            "thread_id": tid_s,
            "graph_run_id": gid_s,
            "event_input": {},
        },
    )
    from uuid import UUID

    cand = repo.get_latest_build_candidate_for_graph_run(UUID(gid_s))
    assert cand is not None
    raw = cand.raw_payload_json or {}
    pm = raw.get("_kmbl_primary_move")
    assert isinstance(pm, dict)
    assert pm.get("move_type") == "composition"


def test_evaluator_output_contract_accepts_scope_overreach_issue() -> None:
    from kmbl_orchestrator.contracts.role_outputs import validate_role_contract

    out = validate_role_contract(
        "evaluator",
        {
            "status": "partial",
            "summary": "too much surface area",
            "issues": [
                {"type": "scope_overreach", "detail": "Too many changes for a single iteration"}
            ],
            "artifacts": [],
            "metrics": {"scope_overreach": True},
        },
    )
    assert out["issues"][0]["type"] == "scope_overreach"


def test_validate_role_input_accepts_evaluator_preview_fields() -> None:
    from kmbl_orchestrator.contracts.role_inputs import validate_role_input

    out = validate_role_input(
        "evaluator",
        {
            "thread_id": "t",
            "build_candidate": {},
            "success_criteria": [],
            "evaluation_targets": [],
            "iteration_hint": 1,
            "preview_url": "http://x/preview",
            "iteration_context": {"iteration_index": 1, "has_previous_evaluation_report": True},
            "previous_evaluation_report": {"status": "partial", "summary": "x"},
        },
    )
    assert out["preview_url"] == "http://x/preview"
    assert out["previous_evaluation_report"]["status"] == "partial"
