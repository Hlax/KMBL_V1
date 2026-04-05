"""
Integration-style graph tests: manifest-first static vertical through real graph nodes.

Mocks KiloClawStubClient.invoke_role for deterministic generator (and sometimes evaluator)
outputs while exercising generator_node, evaluator gating, and run_events persistence.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.errors import RoleInvocationFailed
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient
from kmbl_orchestrator.providers.kiloclaw_parsing import _apply_role_contract
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker
from kmbl_orchestrator.runtime.run_events import RunEventType


def _planner_static_vertical() -> dict[str, Any]:
    return {
        "build_spec": {
            "type": "static_frontend_file_v1",
            "title": "mf_graph_e2e",
            "steps": [],
            "site_archetype": "editorial",
            "experience_mode": "flat_editorial_static",
        },
        "constraints": {"scope": "minimal"},
        "success_criteria": ["loop_reaches_evaluator"],
        "evaluation_targets": ["smoke_check"],
    }


def _settings_mf(
    tmp_path: Any,
    *,
    manifest_first: bool,
    public_base: str = "",
) -> Settings:
    root = tmp_path / "wsroot"
    root.mkdir(parents=True, exist_ok=True)
    return Settings.model_construct(
        openclaw_transport="stub",
        kmbl_env="development",
        graph_max_iterations_default=5,
        habitat_image_generation_enabled=False,
        kmbl_manifest_first_static_vertical=manifest_first,
        orchestrator_public_base_url=public_base,
        orchestrator_smoke_contract_evaluator=False,
        kmbl_generator_workspace_root=str(root),
    )


def test_manifest_first_inline_only_fails_graph_generator(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-empty inline artifacts without manifest+sandbox triggers pre-ingest failure."""
    settings = _settings_mf(tmp_path, manifest_first=True)
    monkeypatch.setattr("kmbl_orchestrator.roles.invoke.get_settings", lambda: settings)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    orig = KiloClawStubClient.invoke_role

    def wrapped(
        self: KiloClawStubClient,
        role_type: Any,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if role_type == "planner":
            return _apply_role_contract("planner", _planner_static_vertical())
        if role_type == "generator":
            raw = {
                "artifact_outputs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": "<!DOCTYPE html><html><body>inline only</body></html>",
                        "entry_for_preview": True,
                    }
                ],
                "updated_state": {"revision": 1},
            }
            return _apply_role_contract("generator", raw)
        return orig(self, role_type, provider_config_key, payload)

    tid_s, gid_s = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    gid_u = UUID(gid_s)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        with pytest.raises(RoleInvocationFailed) as exc:
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
    assert exc.value.phase == "generator"
    det = exc.value.detail or {}
    assert det.get("error_kind") == "contract_validation"
    assert (det.get("details") or {}).get("error_kind") == "manifest_first_missing_workspace"

    evs = repo.list_graph_run_events(gid_u, limit=200)
    types = [e.event_type for e in evs]
    assert RunEventType.WORKSPACE_INGEST_NOT_ATTEMPTED in types
    assert RunEventType.MANIFEST_FIRST_VIOLATION in types


def test_manifest_first_workspace_ingest_completes_graph(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid manifest + sandbox + on-disk files: ingest completes; generator enforcement passes."""
    settings = _settings_mf(
        tmp_path,
        manifest_first=True,
        public_base="http://127.0.0.1:8010",
    )
    monkeypatch.setattr("kmbl_orchestrator.roles.invoke.get_settings", lambda: settings)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    orig = KiloClawStubClient.invoke_role

    tid_s, gid_s = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    tid_u = UUID(tid_s)
    gid_u = UUID(gid_s)
    sandbox = tmp_path / "wsroot" / str(tid_u) / str(gid_u) / "sandbox"
    (sandbox / "component/preview").mkdir(parents=True)
    (sandbox / "component/preview/index.html").write_text(
        "<!DOCTYPE html><html><body>disk</body></html>",
        encoding="utf-8",
    )
    wm: dict[str, Any] = {
        "version": 1,
        "files": [{"path": "component/preview/index.html"}],
        "entry_html": "component/preview/index.html",
    }

    def wrapped(
        self: KiloClawStubClient,
        role_type: Any,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if role_type == "planner":
            return _apply_role_contract("planner", _planner_static_vertical())
        if role_type == "generator":
            raw = {
                "workspace_manifest_v1": wm,
                "sandbox_ref": str(sandbox),
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
                "preview_url": "http://127.0.0.1:8010/preview",
            }
            return _apply_role_contract("generator", raw)
        if role_type == "evaluator":
            return _apply_role_contract(
                "evaluator",
                {
                    "status": "pass",
                    "summary": "mf e2e",
                    "issues": [],
                    "artifacts": [],
                    "metrics": {},
                },
            )
        return orig(self, role_type, provider_config_key, payload)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
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

    evs = repo.list_graph_run_events(gid_u, limit=200)
    types = [e.event_type for e in evs]
    assert RunEventType.WORKSPACE_INGEST_STARTED in types
    assert RunEventType.WORKSPACE_INGEST_COMPLETED in types
    completed = next(e for e in evs if e.event_type == RunEventType.WORKSPACE_INGEST_COMPLETED)
    assert (completed.payload_json or {}).get("file_count") == 1


def test_manifest_first_inline_html_skips_ingest_fails(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest + sandbox present but inline HTML blocks ingest → manifest-first violation."""
    settings = _settings_mf(tmp_path, manifest_first=True)
    monkeypatch.setattr("kmbl_orchestrator.roles.invoke.get_settings", lambda: settings)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    orig = KiloClawStubClient.invoke_role

    tid_s, gid_s = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    gid_u = UUID(gid_s)
    tid_u = UUID(tid_s)
    sandbox = tmp_path / "wsroot" / str(tid_u) / str(gid_s) / "sandbox"
    (sandbox / "component/preview").mkdir(parents=True)
    (sandbox / "component/preview/index.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    wm: dict[str, Any] = {
        "version": 1,
        "files": [{"path": "component/preview/index.html"}],
        "entry_html": "component/preview/index.html",
    }

    def wrapped(
        self: KiloClawStubClient,
        role_type: Any,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if role_type == "planner":
            return _apply_role_contract("planner", _planner_static_vertical())
        if role_type == "generator":
            raw = {
                "workspace_manifest_v1": wm,
                "sandbox_ref": str(sandbox),
                "artifact_outputs": [
                    {
                        "role": "static_frontend_file_v1",
                        "path": "component/preview/index.html",
                        "language": "html",
                        "content": "<!DOCTYPE html><html><body>blocks ingest</body></html>",
                    }
                ],
                "updated_state": {"revision": 1},
            }
            return _apply_role_contract("generator", raw)
        return orig(self, role_type, provider_config_key, payload)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        with pytest.raises(RoleInvocationFailed) as exc:
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
    det = exc.value.detail or {}
    assert det.get("error_kind") == "contract_validation"
    assert (det.get("details") or {}).get("error_kind") == "manifest_first_ingest_skipped_or_empty"

    evs = repo.list_graph_run_events(gid_u, limit=200)
    types = [e.event_type for e in evs]
    assert RunEventType.WORKSPACE_INGEST_SKIPPED_INLINE_HTML in types
    assert RunEventType.MANIFEST_FIRST_VIOLATION in types


def test_manifest_first_evaluator_grounding_unavailable_graph(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No absolute preview URL with manifest-first static vertical → evaluator fails before LLM."""
    settings = _settings_mf(tmp_path, manifest_first=True, public_base="")
    monkeypatch.setattr("kmbl_orchestrator.roles.invoke.get_settings", lambda: settings)

    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)
    orig = KiloClawStubClient.invoke_role

    tid_s, gid_s = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    gid_u = UUID(gid_s)
    tid_u = UUID(tid_s)
    sandbox = tmp_path / "wsroot" / str(tid_u) / str(gid_s) / "sandbox"
    (sandbox / "component/preview").mkdir(parents=True)
    (sandbox / "component/preview/index.html").write_text(
        "<!DOCTYPE html><html><body>g</body></html>",
        encoding="utf-8",
    )
    wm: dict[str, Any] = {
        "version": 1,
        "files": [{"path": "component/preview/index.html"}],
        "entry_html": "component/preview/index.html",
    }

    def wrapped(
        self: KiloClawStubClient,
        role_type: Any,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if role_type == "planner":
            return _apply_role_contract("planner", _planner_static_vertical())
        if role_type == "generator":
            raw = {
                "workspace_manifest_v1": wm,
                "sandbox_ref": str(sandbox),
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
            }
            return _apply_role_contract("generator", raw)
        return orig(self, role_type, provider_config_key, payload)

    with patch.object(KiloClawStubClient, "invoke_role", wrapped):
        with pytest.raises(RoleInvocationFailed) as exc:
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
    assert exc.value.phase == "evaluator"
    assert exc.value.detail.get("error_kind") == "evaluator_grounding_unavailable"

    evs = repo.list_graph_run_events(gid_u, limit=200)
    assert RunEventType.EVALUATOR_GROUNDING_UNAVAILABLE in [e.event_type for e in evs]
