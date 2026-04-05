"""Per-run generator workspace retention (opt-in)."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID, uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.workspace_retention import prune_stale_generator_workspaces


def test_retention_disabled_noops(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    tid = uuid4()
    rid = uuid4()
    run_dir = root / str(tid) / str(rid)
    run_dir.mkdir(parents=True)
    s = Settings.model_construct(
        kmbl_generator_workspace_root=str(root),
        kmbl_generator_workspace_retention_enabled=False,
        kmbl_generator_workspace_retention_min_age_days=0.001,
    )
    r = prune_stale_generator_workspaces(s, dry_run=False)
    assert r.deleted_paths == []
    assert run_dir.is_dir()


def test_retention_deletes_old_run_dir(tmp_path: Path) -> None:
    root = tmp_path / "w"
    tid = uuid4()
    rid = uuid4()
    run_dir = root / str(tid) / str(rid)
    run_dir.mkdir(parents=True)
    old = time.time() - 40 * 86400
    import os

    os.utime(run_dir, (old, old))

    s = Settings.model_construct(
        kmbl_generator_workspace_root=str(root),
        kmbl_generator_workspace_retention_enabled=True,
        kmbl_generator_workspace_retention_min_age_days=7.0,
    )
    r = prune_stale_generator_workspaces(s, dry_run=False, now=time.time())
    assert str(run_dir) in r.deleted_paths
    assert not run_dir.exists()


def test_retention_protects_graph_run(tmp_path: Path) -> None:
    root = tmp_path / "w"
    tid = uuid4()
    rid = uuid4()
    run_dir = root / str(tid) / str(rid)
    run_dir.mkdir(parents=True)
    old = time.time() - 40 * 86400
    import os

    os.utime(run_dir, (old, old))

    s = Settings.model_construct(
        kmbl_generator_workspace_root=str(root),
        kmbl_generator_workspace_retention_enabled=True,
        kmbl_generator_workspace_retention_min_age_days=7.0,
    )
    r = prune_stale_generator_workspaces(
        s,
        dry_run=False,
        protect_graph_run_ids=frozenset({UUID(str(rid))}),
        now=time.time(),
    )
    assert r.deleted_paths == []
    assert run_dir.is_dir()
