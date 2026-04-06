"""Repository REST preflight before run dispatch and operator cache."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from kmbl_orchestrator.api.main import app
from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.persistence.exceptions import RepositoryDispatchBlockedError
from kmbl_orchestrator.persistence.factory import reset_repository_singleton_for_tests
from kmbl_orchestrator.persistence.repository_health import (
    merge_preflight_into_event_input,
    probe_supabase_rest_readiness,
    probe_write_path_canary,
    require_repository_dispatch_healthy,
    sanitize_repository_preflight_for_operator,
    WRITE_PATH_CANARY_RPC,
)
from kmbl_orchestrator.persistence.supabase_infra import format_supabase_repository_error
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


@pytest.fixture
def clear_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("OPENCLAW_TRANSPORT", "stub")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()


@pytest.fixture
def client(clear_singleton: None) -> TestClient:
    return TestClient(app)


def test_probe_supabase_rest_readiness_healthy() -> None:
    exec_result = MagicMock()
    exec_result.data = []
    lim = MagicMock()
    lim.execute.return_value = exec_result
    sel = MagicMock()
    sel.limit.return_value = lim
    tbl = MagicMock()
    tbl.select.return_value = sel
    client = MagicMock()
    client.table.return_value = tbl
    repo = MagicMock(spec=SupabaseRepository)
    repo._client = client

    snap = probe_supabase_rest_readiness(repo)
    assert snap["state"] == "healthy"
    assert snap["write_path_unproven"] is True


def test_probe_supabase_rest_readiness_html_cloudflare_classified() -> None:
    exc = APIError(
        {
            "code": "400",
            "message": "JSON could not be generated",
            "details": "<html>cloudflare</html>",
            "hint": None,
        }
    )
    repo = MagicMock()
    lim = MagicMock()
    lim.execute.side_effect = exc
    sel = MagicMock()
    sel.limit.return_value = lim
    tbl = MagicMock()
    tbl.select.return_value = sel
    client = MagicMock()
    client.table.return_value = tbl
    repo._client = client

    snap = probe_supabase_rest_readiness(repo)
    assert snap["state"] == "blocked"
    assert snap.get("looks_like_non_json_upstream") is True


def test_require_repository_dispatch_healthy_raises_when_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    repo = MagicMock(spec=SupabaseRepository)
    settings = get_settings()

    def _probe(_r: SupabaseRepository) -> dict:
        return {
            "state": "blocked",
            "backend": "supabase",
            "probe": "thread_select_limit_1",
            "looks_like_non_json_upstream": True,
        }

    monkeypatch.setattr(
        "kmbl_orchestrator.persistence.repository_health.probe_supabase_rest_readiness",
        _probe,
    )
    with pytest.raises(RepositoryDispatchBlockedError):
        require_repository_dispatch_healthy(repo, settings, context="test_ctx")


def test_sanitize_preflight_drops_unknown_keys() -> None:
    out = sanitize_repository_preflight_for_operator(
        {
            "state": "blocked",
            "secret": "nope",
            "message": "x" * 600,
        }
    )
    assert "secret" not in out
    assert len(out.get("message", "")) <= 502


def test_merge_preflight_into_event_input() -> None:
    base = {"a": 1}
    merged = merge_preflight_into_event_input(
        base,
        {
            "state": "healthy",
            "preflight_tier": "healthy_write_proven",
            "probe": "thread_select_limit_1+x",
            "elapsed_ms": 1.2,
            "write_path_proven": True,
            "write_path_unproven": False,
            "write_canary_status": "ok",
            "dispatch_context": "c",
        },
    )
    assert merged["a"] == 1
    assert merged["kmbl_repository_preflight"]["state"] == "healthy"
    assert merged["kmbl_repository_preflight"]["preflight_tier"] == "healthy_write_proven"


def test_start_run_preflight_blocked_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocked(*_a: object, **_k: object) -> None:
        raise RepositoryDispatchBlockedError(
            {
                "state": "blocked",
                "probe": "thread_select_limit_1",
                "looks_like_non_json_upstream": True,
                "message": "bad",
            }
        )

    monkeypatch.setattr(
        "kmbl_orchestrator.api.main.require_repository_dispatch_healthy",
        _blocked,
    )
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error_kind"] == "repository_preflight_failed"
    assert detail["repository_health"]["state"] == "blocked"


def test_start_run_preflight_ok_includes_repository_preflight_and_event_input(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _ok(*_a: object, **_k: object) -> dict:
        return {
            "state": "healthy",
            "backend": "supabase",
            "preflight_tier": "healthy_write_proven",
            "probe": "thread_select_limit_1+x",
            "elapsed_ms": 0.5,
            "write_path_proven": True,
            "write_path_unproven": False,
            "write_canary_status": "ok",
            "dispatch_context": "post_orchestrator_runs_start",
            "note": "n",
        }

    monkeypatch.setattr(
        "kmbl_orchestrator.api.main.require_repository_dispatch_healthy",
        _ok,
    )
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 200
    body = r.json()
    assert body.get("repository_preflight", {}).get("state") == "healthy"
    assert body["effective_event_input"]["kmbl_repository_preflight"]["write_path_proven"] is True


def test_probe_write_path_canary_ok() -> None:
    rpc_chain = MagicMock()
    rpc_chain.execute.return_value = MagicMock(
        data={"ok": True, "channel": "postgrest_rpc", "canary_version": 1}
    )
    client = MagicMock()
    client.rpc.return_value = rpc_chain
    repo = MagicMock(spec=SupabaseRepository)
    repo._client = client

    snap = probe_write_path_canary(repo)
    assert snap["status"] == "ok"
    client.rpc.assert_called_once_with(WRITE_PATH_CANARY_RPC, {})


def test_probe_write_path_canary_unavailable_pgrst202() -> None:
    exc = APIError(
        {
            "code": "PGRST202",
            "message": "Could not find the function",
            "details": None,
            "hint": None,
        }
    )
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = exc
    repo = MagicMock(spec=SupabaseRepository)
    repo._client = client

    snap = probe_write_path_canary(repo)
    assert snap["status"] == "unavailable"


def test_probe_write_path_canary_blocked_non_json() -> None:
    exc = APIError(
        {
            "code": "400",
            "message": "JSON could not be generated",
            "details": "<html>cf</html>",
            "hint": None,
        }
    )
    client = MagicMock()
    client.rpc.return_value.execute.side_effect = exc
    repo = MagicMock(spec=SupabaseRepository)
    repo._client = client

    snap = probe_write_path_canary(repo)
    assert snap["status"] == "blocked"
    assert snap.get("looks_like_non_json_upstream") is True


def test_require_repository_dispatch_healthy_write_blocked_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    repo = MagicMock(spec=SupabaseRepository)
    settings = get_settings()

    monkeypatch.setattr(
        "kmbl_orchestrator.persistence.repository_health.probe_supabase_rest_readiness",
        lambda _r: {
            "state": "healthy",
            "probe": "thread_select_limit_1",
            "elapsed_ms": 1.0,
            "backend": "supabase",
        },
    )
    monkeypatch.setattr(
        "kmbl_orchestrator.persistence.repository_health.probe_write_path_canary",
        lambda _r: {
            "status": "blocked",
            "probe": WRITE_PATH_CANARY_RPC,
            "message": "rpc failed",
            "looks_like_non_json_upstream": True,
        },
    )

    with pytest.raises(RepositoryDispatchBlockedError) as ei:
        require_repository_dispatch_healthy(repo, settings, context="t")
    assert ei.value.snapshot.get("block_phase") == "write_canary"
    assert ei.value.snapshot.get("preflight_tier") == "write_path_blocked"


def test_require_repository_dispatch_healthy_write_unavailable_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    get_settings.cache_clear()
    reset_repository_singleton_for_tests()

    repo = MagicMock(spec=SupabaseRepository)
    settings = get_settings()

    monkeypatch.setattr(
        "kmbl_orchestrator.persistence.repository_health.probe_supabase_rest_readiness",
        lambda _r: {
            "state": "healthy",
            "probe": "thread_select_limit_1",
            "elapsed_ms": 1.0,
            "backend": "supabase",
            "row_sample_count": 0,
        },
    )
    monkeypatch.setattr(
        "kmbl_orchestrator.persistence.repository_health.probe_write_path_canary",
        lambda _r: {"status": "unavailable", "probe": WRITE_PATH_CANARY_RPC, "note": "migration"},
    )

    out = require_repository_dispatch_healthy(repo, settings, context="t")
    assert out is not None
    assert out["preflight_tier"] == "healthy_write_unproven"
    assert out["write_path_proven"] is False
    assert out["write_canary_status"] == "unavailable"


def test_start_run_preflight_write_canary_503_uses_rpc_hint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocked(*_a: object, **_k: object) -> None:
        raise RepositoryDispatchBlockedError(
            {
                "state": "blocked",
                "block_phase": "write_canary",
                "preflight_tier": "write_path_blocked",
                "probe": "thread_select_limit_1+x",
                "message": "bad",
            }
        )

    monkeypatch.setattr(
        "kmbl_orchestrator.api.main.require_repository_dispatch_healthy",
        _blocked,
    )
    monkeypatch.setattr(
        "kmbl_orchestrator.api.main._run_graph_background",
        lambda **kwargs: None,
    )
    r = client.post("/orchestrator/runs/start", json={})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "canary" in detail["message"].lower() or "rpc" in detail["message"].lower()
    assert "migration" in detail["hint"].lower() or "rpc" in detail["hint"].lower()


def test_format_supabase_repository_error_rpc_mutating_context() -> None:
    exc = APIError(
        {
            "code": "PGRST202",
            "message": "function not found",
            "details": None,
            "hint": None,
        }
    )
    msg = format_supabase_repository_error(
        "rpc:atomic_commit",
        "rpc",
        exc,
        rpc="atomic_commit_working_staging_approval",
        persistence_kind="rpc_mutating",
    )
    assert "rpc_mutating" in msg
    assert "atomic_commit" in msg
