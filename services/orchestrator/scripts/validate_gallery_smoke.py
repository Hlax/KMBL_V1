#!/usr/bin/env python3
"""Run deterministic + varied gallery smokes with ``--validate-stability`` (sequential)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PRESETS = (
    "seeded_gallery_strip_v1",
    "seeded_gallery_strip_varied_v1",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "run_graph_smoke.py"
    port = os.environ.get("ORCHESTRATOR_PORT", "8010")
    py = root / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    last = 0
    for preset in _PRESETS:
        r = subprocess.run(
            [
                exe,
                str(script),
                "--preset",
                preset,
                "--port",
                str(port),
                "--validate-stability",
            ],
            cwd=str(root),
        )
        last = r.returncode
        if last != 0:
            return last
    return last


if __name__ == "__main__":
    sys.exit(main())
