#!/usr/bin/env python3
"""
Single local happy path: health → POST /orchestrator/runs/start → GET run status.

Requires:
  - Orchestrator listening (e.g. http://127.0.0.1:8010)
  - Repo-root `.env.local` with real Supabase + KiloClaw so rows persist (not in-memory)

Usage (from services/orchestrator)::

  set PYTHONPATH=src
  set ORCHESTRATOR_BASE=http://127.0.0.1:8010
  python scripts/local_persisted_run_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_SRC = _ORCH / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import httpx  # noqa: E402


def main() -> int:
    base = (os.environ.get("ORCHESTRATOR_BASE") or "http://127.0.0.1:8010").rstrip("/")
    print("base:", base)
    with httpx.Client(timeout=300.0) as client:
        h = client.get(f"{base}/health")
        print("GET /health", h.status_code)
        print(json.dumps(h.json(), indent=2)[:2500])
        if h.status_code != 200:
            return 1

        r = client.post(f"{base}/orchestrator/runs/start", json={})
        print("POST /orchestrator/runs/start", r.status_code)
        try:
            body = r.json()
        except json.JSONDecodeError:
            print(r.text[:2000])
            return 1
        print(json.dumps(body, indent=2)[:4000])
        gid = body.get("graph_run_id")
        if not gid:
            print("missing graph_run_id in response")
            return 1
        if body.get("status") != "running":
            print("expected start response status=running, got:", body.get("status"))
            return 1

        deadline = time.time() + 300.0
        last: dict = {}
        while time.time() < deadline:
            s = client.get(f"{base}/orchestrator/runs/{gid}")
            print("GET /orchestrator/runs/{id}", s.status_code)
            try:
                last = s.json()
            except json.JSONDecodeError:
                print(s.text[:2000])
                return 1
            print(json.dumps(last, indent=2)[:4000])
            st = last.get("status")
            if st in ("completed", "failed"):
                if st == "failed":
                    print(
                        "\n--- RUN STATUS: failed ---\n"
                        "  KiloClaw/contract: see failure_phase + failure (error_type) on GET.\n"
                        "  Supabase/graph:    see error_kind=persist_or_graph + error_message on GET.\n"
                    )
                break
            time.sleep(1.5)
        else:
            print("poll timeout waiting for completed/failed")
            return 1

        run_ok = r.status_code == 200 and s.status_code == 200 and last.get("status") == "completed"
        return 0 if run_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
