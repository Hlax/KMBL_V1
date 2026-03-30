"""SupabaseRepository._run transport retries (PostgREST ``Server disconnected``, etc.)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpcore
import httpx
import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.persistence.supabase_repository import (
    SupabaseRepository,
    _is_retryable_supabase_transport,
)


@pytest.fixture
def supabase_repo() -> SupabaseRepository:
    with patch(
        "kmbl_orchestrator.persistence.supabase_repository.create_client",
        return_value=MagicMock(),
    ):
        return SupabaseRepository(
            Settings(
                supabase_url="https://example.supabase.co",
                supabase_service_role_key="test-service-role",
            )
        )


def test_classifier_httpx_remote_protocol_error_retryable() -> None:
    assert _is_retryable_supabase_transport(
        httpx.RemoteProtocolError("Server disconnected")
    )


def test_classifier_httpcore_remote_protocol_error_retryable() -> None:
    assert _is_retryable_supabase_transport(
        httpcore.RemoteProtocolError("Server disconnected")
    )


def test_classifier_existing_transport_errors_still_retryable() -> None:
    assert _is_retryable_supabase_transport(httpx.TimeoutException("t"))
    assert _is_retryable_supabase_transport(httpx.ConnectError("c"))
    assert _is_retryable_supabase_transport(httpx.ReadError("r"))


def test_classifier_non_transport_not_retryable() -> None:
    assert not _is_retryable_supabase_transport(ValueError("x"))


def test_run_retries_remote_protocol_error_then_succeeds(
    supabase_repo: SupabaseRepository,
) -> None:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected")
        return "ok"

    with patch("kmbl_orchestrator.persistence.supabase_repository.time.sleep"):
        assert supabase_repo._run("test_op", "test_table", fn, key="v") == "ok"
    assert len(calls) == 2


def test_run_remote_protocol_error_exhausts_attempts(
    supabase_repo: SupabaseRepository,
) -> None:
    calls: list[int] = []

    def fn() -> None:
        calls.append(1)
        raise httpx.RemoteProtocolError("Server disconnected")

    with patch("kmbl_orchestrator.persistence.supabase_repository.time.sleep"):
        with pytest.raises(RuntimeError, match=r"SupabaseRepository\.test_op\(test_table\) failed"):
            supabase_repo._run("test_op", "test_table", fn, key="v")
    assert len(calls) == 3


def test_run_retries_timeout_exception_then_succeeds(
    supabase_repo: SupabaseRepository,
) -> None:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.TimeoutException("timeout")
        return "done"

    with patch("kmbl_orchestrator.persistence.supabase_repository.time.sleep"):
        assert supabase_repo._run("op", "table", fn) == "done"
    assert len(calls) == 2


def test_run_httpcore_remote_protocol_error_then_succeeds(
    supabase_repo: SupabaseRepository,
) -> None:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise httpcore.RemoteProtocolError("Server disconnected")
        return "ok"

    with patch("kmbl_orchestrator.persistence.supabase_repository.time.sleep"):
        assert supabase_repo._run("op", "table", fn) == "ok"
    assert len(calls) == 2
