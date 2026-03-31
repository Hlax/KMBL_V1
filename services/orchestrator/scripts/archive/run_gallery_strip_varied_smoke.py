#!/usr/bin/env python3
"""
Gallery strip **varied** smoke — thin wrapper (``seeded_gallery_strip_varied_v1``).

Equivalent to: ``python scripts/run_graph_smoke.py --preset seeded_gallery_strip_varied_v1``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from smoke_common import run_smoke_flow

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
    import argparse

    p = argparse.ArgumentParser(description="Gallery strip varied smoke")
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ORCHESTRATOR_PORT", "8010")),
    )
    p.add_argument(
        "--no-server",
        action="store_true",
        help="Do not spawn uvicorn (use existing server on --port).",
    )
    ns, _ = p.parse_known_args()
    log = Path(__file__).resolve().parents[1] / "scripts" / "_smoke_gallery_varied_v1.log"
    venv_py = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
    py = venv_py if venv_py.is_file() else None
    return run_smoke_flow(
        preset="seeded_gallery_strip_varied_v1",
        port=ns.port,
        log_path=None if ns.no_server else log,
        spawn_server=not ns.no_server,
        keywords_for_log=_KEYWORDS,
        venv_python=py,
    )


if __name__ == "__main__":
    sys.exit(main())
