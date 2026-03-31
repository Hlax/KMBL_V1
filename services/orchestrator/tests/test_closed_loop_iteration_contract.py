"""
Closed-loop iteration contract (orchestrator side).

Proves the stub transport advances ``iteration_hint`` across evaluator calls.
Live KiloClaw HTTP quality improvement is environment-dependent — run gateway
integration tests manually with ``KILOCLAW_API_KEY`` (see docs/18_DURABLE_GRAPH_RUNS.md).
"""

from __future__ import annotations

from unittest.mock import patch

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw import KiloClawStubClient
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def test_stub_evaluator_receives_incrementing_iteration_hints() -> None:
    settings = Settings.model_construct(
        kiloclaw_transport="stub",
        graph_max_iterations_default=3,
        habitat_image_generation_enabled=False,
    )
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    hints: list[int] = []

    orig = KiloClawStubClient.invoke_role

    def wrapped(self: KiloClawStubClient, role_type, provider_config_key, payload):  # type: ignore[no-untyped-def]
        if role_type == "evaluator":
            hints.append(int(payload.get("iteration_hint", -1)))
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

    assert hints == [0, 1], f"expected evaluator iteration_hint 0 then 1, got {hints}"
