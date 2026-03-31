"""Tests for thread-level advisory locking on InMemoryRepository."""

from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from kmbl_orchestrator.persistence.repository import InMemoryRepository


class TestThreadLockAcquisitionRelease:
    """Basic acquire / release semantics."""

    def test_acquire_and_release(self):
        repo = InMemoryRepository()
        tid = uuid4()

        assert repo.try_acquire_thread_lock(tid, locked_by="w1") is True
        # Holder is tracked
        assert repo._thread_lock_holders[str(tid)] == "w1"
        repo.release_thread_lock(tid)
        assert str(tid) not in repo._thread_lock_holders

    def test_double_release_is_safe(self):
        repo = InMemoryRepository()
        tid = uuid4()

        repo.try_acquire_thread_lock(tid, locked_by="w1")
        repo.release_thread_lock(tid)
        # Second release should not raise
        repo.release_thread_lock(tid)

    def test_release_without_acquire_is_safe(self):
        repo = InMemoryRepository()
        tid = uuid4()
        # Should not raise
        repo.release_thread_lock(tid)


class TestConcurrentSameThreadBlocking:
    """Two workers on the same thread_id must serialize."""

    def test_second_caller_blocks(self):
        repo = InMemoryRepository()
        tid = uuid4()
        entered = threading.Event()
        proceed = threading.Event()
        second_started = threading.Event()
        order: list[str] = []

        def first():
            repo.try_acquire_thread_lock(tid, locked_by="first")
            entered.set()
            proceed.wait(timeout=5)
            order.append("first_done")
            repo.release_thread_lock(tid)

        def second():
            entered.wait(timeout=5)
            second_started.set()
            # This should block until first releases
            acquired = repo.try_acquire_thread_lock(
                tid, locked_by="second", timeout_seconds=5,
            )
            assert acquired
            order.append("second_done")
            repo.release_thread_lock(tid)

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        entered.wait(timeout=3)
        second_started.wait(timeout=3)
        # Give second thread a moment to block on acquire
        time.sleep(0.1)
        # second should NOT have acquired yet
        assert "second_done" not in order
        # Release first
        proceed.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert order == ["first_done", "second_done"]


class TestLockTimeout:
    """Lock acquisition must respect timeout."""

    def test_timeout_returns_false(self):
        repo = InMemoryRepository()
        tid = uuid4()

        # Acquire and hold indefinitely
        repo.try_acquire_thread_lock(tid, locked_by="holder")

        def contender():
            return repo.try_acquire_thread_lock(
                tid, locked_by="contender", timeout_seconds=0,
            )

        # Run in separate thread to avoid blocking test runner
        result = [None]

        def run():
            result[0] = contender()

        t = threading.Thread(target=run)
        t.start()
        t.join(timeout=3)

        assert result[0] is False
        repo.release_thread_lock(tid)

    def test_context_manager_timeout_raises(self):
        repo = InMemoryRepository()
        tid = uuid4()

        repo.try_acquire_thread_lock(tid, locked_by="holder")

        def contender():
            with pytest.raises(TimeoutError):
                with repo.thread_lock(tid, timeout_seconds=0):
                    pass  # pragma: no cover

        t = threading.Thread(target=contender)
        t.start()
        t.join(timeout=3)

        repo.release_thread_lock(tid)

    def test_different_threads_no_contention(self):
        repo = InMemoryRepository()
        tid1 = uuid4()
        tid2 = uuid4()

        assert repo.try_acquire_thread_lock(tid1, locked_by="a") is True
        assert repo.try_acquire_thread_lock(tid2, locked_by="b") is True

        repo.release_thread_lock(tid1)
        repo.release_thread_lock(tid2)

    def test_lock_released_on_exception_in_context(self):
        repo = InMemoryRepository()
        tid = uuid4()

        with pytest.raises(ValueError):
            with repo.thread_lock(tid, timeout_seconds=2):
                raise ValueError("fail")

        # Should be acquirable again immediately
        assert repo.try_acquire_thread_lock(tid, locked_by="after", timeout_seconds=0) is True
        repo.release_thread_lock(tid)
