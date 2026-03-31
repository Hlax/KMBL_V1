"""Optional ORCHESTRATOR_API_KEY enforcement on mutating routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kmbl_orchestrator.api.main import app
from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests


@pytest.fixture
def clear_singleton_and_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ORCHESTRATOR_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("KILOCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()
    yield
    get_settings.cache_clear()


def test_no_api_key_allows_post_when_unconfigured(
    clear_singleton_and_settings: None,
) -> None:
    client = TestClient(app)
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 200


def test_api_key_required_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    clear_singleton_and_settings: None,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "secret-test-key")
    get_settings.cache_clear()
    client = TestClient(app)
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 401

    r2 = client.post(
        "/orchestrator/runs/start",
        json={},
        headers={"X-API-Key": "secret-test-key"},
    )
    assert r2.status_code == 200


def test_get_health_unauthenticated_when_key_set(
    monkeypatch: pytest.MonkeyPatch,
    clear_singleton_and_settings: None,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "k")
    get_settings.cache_clear()
    client = TestClient(app)
    assert client.get("/health").status_code == 200
