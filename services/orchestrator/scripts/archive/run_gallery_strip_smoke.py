"""
Gallery strip smoke — thin wrapper (``seeded_gallery_strip_v1``).

Equivalent to: ``python scripts/run_graph_smoke.py --preset seeded_gallery_strip_v1``

Set ``ORCHESTRATOR_GALLERY_SMOKE_NO_SERVER=1`` to skip spawning uvicorn (use an already-running API).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from smoke_common import run_smoke_flow

_LOG = Path(__file__).resolve().parents[1] / "scripts" / "_gallery_strip_smoke.log"
_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8010"))
_NO_SERVER = os.environ.get("ORCHESTRATOR_GALLERY_SMOKE_NO_SERVER", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

_KEYWORDS = [
    "request_received",
    "graph_run_persisted",
    "planner_invocation_start",
    "generator_invocation_start",
    "evaluator_invocation_start",
    "staging_snapshot_creation",
    "DECISION_MADE",
    "decision_made",
    "run_graph graph_run_id",
]


def main() -> int:
    venv_py = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
    py = venv_py if venv_py.is_file() else None
    return run_smoke_flow(
        preset="seeded_gallery_strip_v1",
        port=_PORT,
        log_path=None if _NO_SERVER else _LOG,
        spawn_server=not _NO_SERVER,
        keywords_for_log=_KEYWORDS,
        venv_python=py,
    )


if __name__ == "__main__":
    sys.exit(main())
