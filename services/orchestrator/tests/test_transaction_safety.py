"""Tests for InMemoryRepository in_memory_write_snapshot() (process-local snapshot/rollback)."""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest

from kmbl_orchestrator.domain import (
    BuildSpecRecord,
    CheckpointRecord,
    GraphRunEventRecord,
    RoleInvocationRecord,
    ThreadRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository


def _make_thread(tid=None):
    tid = tid or uuid4()
    return ThreadRecord(
        thread_id=tid,
        thread_kind="prompt",
        status="active",
        identity_id=None,
        current_checkpoint_id=None,
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
    )


def _make_checkpoint(tid, gid):
    return CheckpointRecord(
        checkpoint_id=uuid4(),
        thread_id=tid,
        graph_run_id=gid,
        checkpoint_kind="post_step",
        state_json={"x": 1},
        context_compaction_json=None,
    )


def _make_role_invocation(gid, tid):
    return RoleInvocationRecord(
        role_invocation_id=uuid4(),
        graph_run_id=gid,
        thread_id=tid,
        role_type="planner",
        provider="openclaw",
        provider_config_key="test",
        input_payload_json={},
        routing_metadata_json={},
        output_payload_json=None,
        status="completed",
        iteration_index=0,
        started_at="2025-01-01T00:00:00+00:00",
        ended_at="2025-01-01T00:00:01+00:00",
    )


class TestInMemoryWriteSnapshotRollback:
    """in_memory_write_snapshot() must roll back all writes on exception (InMemoryRepository only)."""

    def test_rollback_on_exception(self):
        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()
        thread = _make_thread(tid)
        repo.ensure_thread(thread)

        # Pre-state: 1 thread, no checkpoints
        assert repo.get_thread(tid) is not None
        assert len(repo._checkpoints) == 0

        with pytest.raises(RuntimeError):
            with repo.in_memory_write_snapshot():
                repo.save_checkpoint(_make_checkpoint(tid, gid))
                repo.save_role_invocation(_make_role_invocation(gid, tid))
                assert len(repo._checkpoints) == 1
                assert len(repo._role_invocations) == 1
                raise RuntimeError("simulated crash")

        # All writes rolled back
        assert len(repo._checkpoints) == 0
        assert len(repo._role_invocations) == 0
        # Pre-existing data intact
        assert repo.get_thread(tid) is not None

    def test_commit_on_success(self):
        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()
        repo.ensure_thread(_make_thread(tid))

        with repo.in_memory_write_snapshot():
            repo.save_checkpoint(_make_checkpoint(tid, gid))
            repo.save_role_invocation(_make_role_invocation(gid, tid))

        # All writes committed
        assert len(repo._checkpoints) == 1
        assert len(repo._role_invocations) == 1

    def test_nested_transaction_rollback(self):
        """Inner transaction failure should roll back inner writes only."""
        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()
        repo.ensure_thread(_make_thread(tid))

        with repo.in_memory_write_snapshot():
            repo.save_checkpoint(_make_checkpoint(tid, gid))
            try:
                with repo.in_memory_write_snapshot():
                    repo.save_role_invocation(_make_role_invocation(gid, tid))
                    raise ValueError("inner failure")
            except ValueError:
                pass
            # Inner writes rolled back, outer checkpoint still present
            assert len(repo._role_invocations) == 0
            assert len(repo._checkpoints) == 1

        # Outer transaction committed
        assert len(repo._checkpoints) == 1
        assert len(repo._role_invocations) == 0

    def test_rollback_preserves_preexisting_data(self):
        repo = InMemoryRepository()
        tid = uuid4()
        gid = uuid4()
        repo.ensure_thread(_make_thread(tid))
        repo.save_checkpoint(_make_checkpoint(tid, gid))

        assert len(repo._checkpoints) == 1

        with pytest.raises(RuntimeError):
            with repo.in_memory_write_snapshot():
                repo.save_checkpoint(_make_checkpoint(tid, gid))
                assert len(repo._checkpoints) == 2
                raise RuntimeError("boom")

        # Only the pre-existing checkpoint survives
        assert len(repo._checkpoints) == 1


class TestConcurrentSameThreadBlocked:
    """Two graph runs on the same thread_id must not interleave."""

    def test_same_thread_blocked(self):
        repo = InMemoryRepository()
        tid = uuid4()
        barrier = threading.Barrier(2, timeout=5)
        results: list[str] = []

        def worker(name: str):
            with repo.thread_lock(tid, timeout_seconds=5):
                barrier.wait()
                results.append(f"{name}_start")
                # Simulate work
                results.append(f"{name}_end")

        t1 = threading.Thread(target=worker, args=("A",))
        t2 = threading.Thread(target=worker, args=("B",))

        # One thread will get the lock; the other blocks until first releases.
        # With barrier inside lock, the second thread can't reach barrier.
        # So use a simpler test: measure that both eventually complete.
        acquired = threading.Event()
        released = threading.Event()
        order: list[str] = []

        def holder():
            with repo.thread_lock(tid, timeout_seconds=5):
                acquired.set()
                order.append("holder_in")
                released.wait(timeout=3)
                order.append("holder_out")

        def waiter():
            acquired.wait(timeout=3)
            with repo.thread_lock(tid, timeout_seconds=5):
                order.append("waiter_in")

        th = threading.Thread(target=holder)
        tw = threading.Thread(target=waiter)
        th.start()
        tw.start()
        acquired.wait(timeout=3)
        released.set()
        th.join(timeout=5)
        tw.join(timeout=5)

        assert order == ["holder_in", "holder_out", "waiter_in"]

    def test_different_threads_independent(self):
        repo = InMemoryRepository()
        tid1 = uuid4()
        tid2 = uuid4()
        order: list[str] = []
        barrier = threading.Barrier(2, timeout=5)

        def worker(name: str, tid):
            with repo.thread_lock(tid, timeout_seconds=5):
                order.append(f"{name}_in")
                barrier.wait()
                order.append(f"{name}_out")

        t1 = threading.Thread(target=worker, args=("A", tid1))
        t2 = threading.Thread(target=worker, args=("B", tid2))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both should enter concurrently (barrier would deadlock otherwise)
        assert "A_in" in order
        assert "B_in" in order
        assert "A_out" in order
        assert "B_out" in order

    def test_lock_released_on_failure(self):
        repo = InMemoryRepository()
        tid = uuid4()

        with pytest.raises(RuntimeError):
            with repo.thread_lock(tid, timeout_seconds=2):
                raise RuntimeError("boom")

        # Lock should be released — can re-acquire immediately
        acquired = repo.try_acquire_thread_lock(tid, locked_by="test", timeout_seconds=1)
        assert acquired
        repo.release_thread_lock(tid)
