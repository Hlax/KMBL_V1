"""Start temporary uvicorn with ORCHESTRATOR_SMOKE_PLANNER_ONLY, POST /runs/start, print log excerpts."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

_ORCH = Path(__file__).resolve().parents[1]
_LOG = _ORCH / "scripts" / "_planner_smoke_server.log"
_PORT = int(os.environ.get("PLANNER_SMOKE_PORT", "8016"))


def main() -> int:
    _LOG.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ORCH / "src")
    env["ORCHESTRATOR_SMOKE_PLANNER_ONLY"] = "true"
    env["ORCHESTRATOR_VERBOSE_LOGS"] = "1"
    logf = open(_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            str(_ORCH / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "uvicorn",
            "kmbl_orchestrator.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(_PORT),
        ],
        cwd=str(_ORCH),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    try:
        base = f"http://127.0.0.1:{_PORT}"
        for _ in range(30):
            time.sleep(0.5)
            try:
                httpx.get(f"{base}/health", timeout=2.0)
                break
            except Exception:
                continue
        else:
            print("SERVER_START_FAILED", file=sys.stderr)
            return 1

        r = httpx.post(f"{base}/orchestrator/runs/start", json={}, timeout=120.0)
        print("POST_STATUS", r.status_code)
        print("POST_BODY", r.text)
        if r.status_code == 200:
            data = r.json()
            gid = data.get("graph_run_id")
            for _ in range(60):
                time.sleep(1.0)
                s = httpx.get(f"{base}/orchestrator/runs/{gid}", timeout=30.0)
                if s.status_code != 200:
                    continue
                st = s.json().get("status")
                if st in ("completed", "failed"):
                    print("RUN_FINAL_STATUS", st)
                    print("RUN_SNIPPET", json.dumps(s.json())[:4000])
                    break
        time.sleep(1.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        logf.close()

    text = _LOG.read_text(encoding="utf-8", errors="replace")
    keys = [
        "request_received",
        "graph_run_persisted",
        "kiloclaw_http_outbound start",
        "kiloclaw_http_outbound done",
        "planner_invocation_finished",
        "smoke_planner_only",
        "response_returning",
    ]
    print("--- LOG_EXCERPTS ---")
    for line in text.splitlines():
        if any(k in line for k in keys):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
