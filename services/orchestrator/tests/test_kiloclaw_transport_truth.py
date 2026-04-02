"""KiloClaw transport resolution, stub policy, and observability."""

from __future__ import annotations

from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw import (
    KiloclawTransportConfigError,
    compute_kiloclaw_resolution,
    get_kiloclaw_client,
    get_kiloclaw_client_with_trace,
)
from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError
from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()


def test_explicit_stub_uses_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    monkeypatch.setenv("KMBL_ENV", "development")
    s = Settings()
    r = compute_kiloclaw_resolution(s)
    assert r.resolved == "stub"
    assert r.stub_mode is True
    c, trace = get_kiloclaw_client_with_trace(s)
    assert isinstance(c, KiloClawStubClient)
    assert trace["kiloclaw_transport_resolved"] == "stub"


def test_http_without_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "http")
    monkeypatch.setenv("KILOCLAW_API_KEY", "")
    s = Settings()
    with pytest.raises(KiloclawTransportConfigError, match="KILOCLAW_API_KEY"):
        compute_kiloclaw_resolution(s)
    with pytest.raises(KiloclawTransportConfigError):
        get_kiloclaw_client(s)


def test_http_with_placeholder_base_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "http")
    monkeypatch.setenv("KILOCLAW_API_KEY", "x")
    monkeypatch.setenv("KILOCLAW_BASE_URL", "https://kiloclaw.example.invalid")
    s = Settings()
    with pytest.raises(KiloclawTransportConfigError, match="placeholder"):
        compute_kiloclaw_resolution(s)


def test_openclaw_cli_without_executable_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "openclaw_cli")
    monkeypatch.setenv("KILOCLAW_OPENCLAW_EXECUTABLE", "nonexistent_openclaw_binary_xyz")
    monkeypatch.setenv("PATH", "")
    s = Settings()
    with pytest.raises(KiloclawTransportConfigError, match="not found"):
        compute_kiloclaw_resolution(s)


def test_auto_no_key_resolves_stub_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "auto")
    monkeypatch.setenv("KILOCLAW_API_KEY", "")
    monkeypatch.setenv("KMBL_ENV", "development")
    s = Settings()
    r = compute_kiloclaw_resolution(s)
    assert r.resolved == "stub"
    assert r.auto_resolution_note == "no_api_key_auto_stub"


def test_auto_no_key_production_forbids_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "auto")
    monkeypatch.setenv("KILOCLAW_API_KEY", "")
    monkeypatch.setenv("KMBL_ENV", "production")
    s = Settings()
    with pytest.raises(KiloclawTransportConfigError, match="stub transport is not allowed"):
        compute_kiloclaw_resolution(s)


def test_production_allows_stub_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "auto")
    monkeypatch.setenv("KILOCLAW_API_KEY", "")
    monkeypatch.setenv("KMBL_ENV", "production")
    monkeypatch.setenv("ALLOW_STUB_TRANSPORT", "true")
    s = Settings()
    r = compute_kiloclaw_resolution(s)
    assert r.resolved == "stub"


def test_invoker_merges_transport_trace_into_routing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    monkeypatch.setenv("KMBL_ENV", "development")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker()
    gid = uuid4()
    tid = uuid4()
    rec, _ = invoker.invoke(
        graph_run_id=gid,
        thread_id=tid,
        role_type="planner",
        provider_config_key="kmbl-planner",
        input_payload={
            "thread_id": str(tid),
            "event_input": {},
        },
        iteration_index=0,
        routing_metadata={"generator_route_kind": "test"},
    )
    assert rec.status == "completed"
    rm = rec.routing_metadata_json or {}
    assert rm.get("kiloclaw_transport_resolved") == "stub"
    assert rm.get("kiloclaw_stub_mode") is True
    assert rm.get("generator_route_kind") == "test"


def test_production_stub_transport_disallowed_raises_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config forbids stub in production; invoke fails before any stub client use."""
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KMBL_ENV", "production")
    monkeypatch.setenv("ALLOW_STUB_TRANSPORT", "false")
    monkeypatch.setenv("KILOCLAW_API_KEY", "")
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    s = Settings()
    stub = KiloClawStubClient(settings=s)
    invoker = DefaultRoleInvoker(client=stub, settings=s)
    gid = uuid4()
    tid = uuid4()
    with pytest.raises(KiloclawRoleInvocationForbiddenError):
        invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key="kmbl-planner",
            input_payload={
                "thread_id": str(tid),
                "event_input": {},
            },
            iteration_index=0,
        )


def test_production_injected_stub_client_fails_when_http_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved transport is HTTP but an injected stub client is forbidden in production."""
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KMBL_ENV", "production")
    monkeypatch.setenv("ALLOW_STUB_TRANSPORT", "false")
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "http")
    monkeypatch.setenv("KILOCLAW_API_KEY", "test-key")
    monkeypatch.setenv("KILOCLAW_BASE_URL", "https://api.example.com/v1")
    get_settings.cache_clear()
    s = Settings()
    stub = KiloClawStubClient(settings=s)
    invoker = DefaultRoleInvoker(client=stub, settings=s)
    gid = uuid4()
    tid = uuid4()
    with pytest.raises(KiloclawRoleInvocationForbiddenError, match="Stub KiloClaw"):
        invoker.invoke(
            graph_run_id=gid,
            thread_id=tid,
            role_type="planner",
            provider_config_key="kmbl-planner",
            input_payload={
                "thread_id": str(tid),
                "event_input": {},
            },
            iteration_index=0,
        )


def test_health_includes_kiloclaw_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    monkeypatch.setenv("KMBL_ENV", "development")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from kmbl_orchestrator.api.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["kmbl_env"] == "development"
    assert "kiloclaw_resolution" in body
    assert body["kiloclaw_resolution"].get("configuration_valid") is True
    assert body["kiloclaw_resolution"].get("kiloclaw_stub_mode") is True
    assert "normalization_rescue_events_total" in body
    assert "orchestrator_graph_run_dispatch_note" in body
    assert body["readiness"].get("kiloclaw_transport_operational") is True


def test_normalization_rescue_counter_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings(monkeypatch)
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
    from kmbl_orchestrator.runtime.run_events import (
        RunEventType,
        append_graph_run_event,
        normalization_rescue_event_total,
    )

    reset_repository_singleton_for_tests()
    repo = InMemoryRepository()
    gid = uuid4()
    before = normalization_rescue_event_total()
    append_graph_run_event(repo, gid, RunEventType.NORMALIZATION_RESCUE, {"n": 1})
    assert normalization_rescue_event_total() == before + 1
