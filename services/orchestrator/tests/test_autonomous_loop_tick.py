"""Autonomous loop tick — async identity extract, identity_id binding, graph_cycle phase."""

from __future__ import annotations

import asyncio
from unittest.mock import patch
from kmbl_orchestrator.autonomous.loop_service import start_autonomous_loop, tick_loop
from kmbl_orchestrator.identity.seed import IdentitySeed
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def test_identity_fetch_persists_seed_under_loop_identity_id() -> None:
    repo = InMemoryRepository()
    loop = start_autonomous_loop(repo, "https://example.com")
    seed = IdentitySeed(
        source_url="https://example.com",
        display_name="Fixture",
        confidence=0.95,
    )

    async def _run() -> None:
        with patch(
            "kmbl_orchestrator.autonomous.loop_service.extract_identity_from_url",
            return_value=seed,
        ):
            row = repo.get_autonomous_loop(loop.loop_id)
            assert row is not None
            out = await tick_loop(repo, row)
            assert out.action == "identity_fetched"
            assert out.phase_after == "graph_cycle"

    asyncio.run(_run())

    updated = repo.get_autonomous_loop(loop.loop_id)
    assert updated is not None
    assert updated.phase == "graph_cycle"
    prof = repo.get_identity_profile(loop.identity_id)
    assert prof is not None
    assert "Fixture" in (prof.profile_summary or "")


def test_graph_tick_resets_error_counter_on_success() -> None:
    repo = InMemoryRepository()
    loop = start_autonomous_loop(repo, "https://example.com")
    seed = IdentitySeed(source_url="https://example.com", confidence=0.95)

    async def _identity() -> None:
        with patch(
            "kmbl_orchestrator.autonomous.loop_service.extract_identity_from_url",
            return_value=seed,
        ):
            row = repo.get_autonomous_loop(loop.loop_id)
            assert row is not None
            await tick_loop(repo, row)

    asyncio.run(_identity())

    row = repo.get_autonomous_loop(loop.loop_id)
    assert row is not None

    async def _ok(**_: object) -> dict:
        return {
            "graph_run_id": "00000000-0000-0000-0000-000000000001",
            "thread_id": "00000000-0000-0000-0000-000000000002",
            "staging_snapshot_id": "00000000-0000-0000-0000-000000000003",
            "evaluator_status": "partial",
            "evaluator_score": 0.5,
        }

    async def _graph() -> None:
        cur = repo.get_autonomous_loop(loop.loop_id)
        assert cur is not None
        out = await tick_loop(repo, cur, run_graph_fn=_ok)
        assert out.action == "graph_iteration_completed"

    asyncio.run(_graph())

    again = repo.get_autonomous_loop(loop.loop_id)
    assert again is not None
    assert again.consecutive_graph_failures == 0
    assert again.last_error is None
