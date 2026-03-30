#!/usr/bin/env python3
"""Unified graph smoke: ``--preset seeded_*`` (local, gallery strip, gallery varied)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from smoke_common import parse_cli_preset, run_smoke_flow

_KEYWORDS_FULL = [
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

_KEYWORDS_GALLERY = [
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
    preset, port, no_server, validate_stability = parse_cli_preset()
    log = Path(__file__).resolve().parents[1] / "scripts" / f"_smoke_{preset}.log"
    kw = _KEYWORDS_GALLERY if "gallery" in preset else _KEYWORDS_FULL
    venv_py = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
    py = venv_py if venv_py.is_file() else None
    return run_smoke_flow(
        preset=preset,
        port=port,
        log_path=None if no_server else log,
        spawn_server=not no_server,
        keywords_for_log=kw,
        venv_python=py,
        validate_stability=validate_stability,
    )


if __name__ == "__main__":
    sys.exit(main())
