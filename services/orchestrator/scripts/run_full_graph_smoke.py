"""
Full graph smoke — thin wrapper around ``smoke_common.run_smoke_flow``.

Equivalent to: ``python scripts/run_graph_smoke.py --preset seeded_local_v1``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from smoke_common import run_smoke_flow

_LOG = Path(__file__).resolve().parents[1] / "scripts" / "_full_run_smoke.log"
_PORT = int(os.environ.get("ORCHESTRATOR_PORT", "8010"))
_KEYWORDS = [
    "request_received",
    "graph_run_persisted",
    "planner_invocation_start",
    "planner_invocation_finished",
    "generator_invocation_start",
    "generator_invocation_finished",
    "evaluator_invocation_start",
    "evaluator_invocation_finished",
    "kiloclaw_http_outbound start",
    "kiloclaw_http_outbound done",
    "staging_snapshot_creation_start",
    "staging_snapshot_creation_done",
    "DECISION_MADE",
    "decision_made",
    "decision",
    "response_returning",
    "run_graph graph_run_id",
    "run_start stage=",
]


def main() -> int:
    venv_py = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
    py = venv_py if venv_py.is_file() else None
    return run_smoke_flow(
        preset="seeded_local_v1",
        port=_PORT,
        log_path=_LOG,
        spawn_server=True,
        keywords_for_log=_KEYWORDS,
        venv_python=py,
    )


if __name__ == "__main__":
    sys.exit(main())
