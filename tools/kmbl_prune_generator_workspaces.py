#!/usr/bin/env python3
"""Operator entrypoint: prune stale per-run generator workspace dirs (opt-in via env).

Run from repo root, e.g.:
  python tools/kmbl_prune_generator_workspaces.py --dry-run

Requires the same KMBL_* env as the orchestrator (especially KMBL_GENERATOR_WORKSPACE_ROOT
and retention flags). Does nothing unless KMBL_GENERATOR_WORKSPACE_RETENTION_ENABLED=true.

Alternative: HTTP POST ``/orchestrator/maintenance/prune-generator-workspaces`` with
``KMBL_MAINTENANCE_PRUNE_HTTP_ENABLED=true`` and JSON body ``{"dry_run": true}`` (see orchestrator API).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ORCH_SRC = _REPO_ROOT / "services" / "orchestrator" / "src"
if _ORCH_SRC.is_dir() and str(_ORCH_SRC) not in sys.path:
    sys.path.insert(0, str(_ORCH_SRC))

from kmbl_orchestrator.config import get_settings  # noqa: E402
from kmbl_orchestrator.runtime.workspace_retention import (  # noqa: E402
    prune_stale_generator_workspaces,
    prune_stale_generator_workspaces_summary,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Prune old kmbl generator per-run workspace directories")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidates only; do not delete",
    )
    args = p.parse_args()
    settings = get_settings()
    r = prune_stale_generator_workspaces(settings, dry_run=args.dry_run)
    print(json.dumps(prune_stale_generator_workspaces_summary(r), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
