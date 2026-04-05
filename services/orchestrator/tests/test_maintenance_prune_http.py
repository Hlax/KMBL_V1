"""HTTP entrypoint for workspace retention (gated). Imports FastAPI only when available."""

from __future__ import annotations

import pytest

from kmbl_orchestrator.config import Settings


def test_prune_endpoint_403_when_http_disabled() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    from kmbl_orchestrator.api.routes_maintenance import router
    from kmbl_orchestrator.config import get_settings

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        kmbl_maintenance_prune_http_enabled=False,
    )
    c = TestClient(app)
    r = c.post(
        "/orchestrator/maintenance/prune-generator-workspaces",
        json={"dry_run": True},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error_kind"] == "maintenance_endpoint_disabled"


def test_prune_endpoint_200_dry_run_when_enabled() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    from kmbl_orchestrator.api.routes_maintenance import router
    from kmbl_orchestrator.config import get_settings

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        kmbl_maintenance_prune_http_enabled=True,
        kmbl_generator_workspace_retention_enabled=False,
    )
    c = TestClient(app)
    r = c.post(
        "/orchestrator/maintenance/prune-generator-workspaces",
        json={"dry_run": True, "protect_graph_run_ids": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["retention_enabled"] is False
    assert body["deleted_count"] == 0
