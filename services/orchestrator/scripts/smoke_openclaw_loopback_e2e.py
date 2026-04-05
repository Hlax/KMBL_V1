#!/usr/bin/env python3
"""
Minimal planner → generator → evaluator → staging smoke against local OpenClaw gateway.

Prereqs:
  - Orchestrator running (e.g. uvicorn on ORCHESTRATOR_BASE)
  - OpenClaw **HTTP API** reachable at OPENCLAW_BASE_URL + OPENCLAW_INVOKE_PATH
    (must return 200/4xx from POST /v1/chat/completions — if you only get HTML or 404,
    the control UI may be on this port while the OpenAI-compatible API listens elsewhere.)
  - Env: OPENCLAW_TRANSPORT=auto|http, no Supabase required (in-memory repo)

Recommended env for this smoke (no browser tooling nudge, no habitat images):
  KMBL_SMOKE_CONTRACT_EVALUATOR=true
  HABITAT_IMAGE_GENERATION_ENABLED=false
  SUPABASE_URL=  SUPABASE_SERVICE_ROLE_KEY=

Usage (from repo root or services/orchestrator)::

  set PYTHONPATH=services\\orchestrator\\src
  set ORCHESTRATOR_BASE=http://127.0.0.1:8000
  python services/orchestrator/scripts/smoke_openclaw_loopback_e2e.py
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
    base = (os.environ.get("ORCHESTRATOR_BASE") or "http://127.0.0.1:8000").rstrip("/")
    poll_sec = float(os.environ.get("SMOKE_POLL_SEC") or "2.0")
    # Local Ollama + full bootstrap can exceed 10m per role; override with SMOKE_DEADLINE_SEC if needed.
    deadline_sec = float(os.environ.get("SMOKE_DEADLINE_SEC") or "1800.0")

    print("=== KMBL OpenClaw loopback smoke ===")
    print("ORCHESTRATOR_BASE:", base)

    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        h = client.get(f"{base}/health")
        print("\nGET /health", h.status_code)
        if h.status_code != 200:
            print(h.text[:2000])
            return 1
        hb = h.json()
        eff = hb.get("openclaw_transport_effective") or hb.get("kiloclaw_transport_effective")
        bu = hb.get("openclaw_base_url") or hb.get("kiloclaw_base_url")
        ip = hb.get("openclaw_invoke_path") or hb.get("kiloclaw_invoke_path")
        print("effective_transport:", eff)
        print("openclaw_base_url:", bu)
        print("invoke_path:", ip)
        if bu and ip:
            print("full_invoke_target:", f"{str(bu).rstrip('/')}{ip if str(ip).startswith('/') else '/' + str(ip)}")
        oc_res = hb.get("openclaw_resolution") or hb.get("kiloclaw_resolution") or {}
        print("configuration_valid:", oc_res.get("configuration_valid"))
        print("stub_mode:", oc_res.get("openclaw_stub_mode", oc_res.get("kiloclaw_stub_mode")))

        if eff == "stub":
            print(
                "\nWARNING: stub transport — OpenClaw HTTP is NOT used; this is not a real gateway smoke.",
            )

        body = {
            "scenario_preset": "seeded_local_v1",
            "max_iterations": 1,
            "trigger_type": "system",
        }
        print("\nPOST /orchestrator/runs/start", json.dumps(body))
        r = client.post(f"{base}/orchestrator/runs/start", json=body)
        print("status", r.status_code)
        try:
            start = r.json()
        except json.JSONDecodeError:
            print(r.text[:3000])
            return 1
        print(json.dumps(start, indent=2)[:6000])
        if r.status_code != 200:
            return 1
        gid = start.get("graph_run_id")
        if not gid:
            print("missing graph_run_id")
            return 1

        t0 = time.time()
        last: dict = {}
        while time.time() - t0 < deadline_sec:
            s = client.get(f"{base}/orchestrator/runs/{gid}")
            try:
                last = s.json()
            except json.JSONDecodeError:
                print(s.text[:2000])
                return 1
            st = last.get("status")
            print(
                f"  poll status={st!r} http={s.status_code} "
                f"failure_phase={last.get('failure_phase')!r} elapsed={time.time() - t0:.1f}s"
            )
            if st in ("completed", "failed"):
                break
            time.sleep(poll_sec)
        else:
            print("TIMEOUT waiting for completed/failed")
            return 1

        print("\n--- final GET /orchestrator/runs/{id} ---")
        print(json.dumps(last, indent=2)[:8000])

        detail = client.get(f"{base}/orchestrator/runs/{gid}/detail")
        if detail.status_code == 200:
            dj = detail.json()
            invs = dj.get("role_invocations") or []
            print("\n--- role invocations (detail) ---")
            for inv in invs:
                print(
                    f"  {inv.get('role_type')}: status={inv.get('status')} "
                    f"key={inv.get('provider_config_key')}"
                )
            summ = dj.get("summary") or {}
            if summ.get("openclaw_transport_trace"):
                print("openclaw_transport_trace:", summ.get("openclaw_transport_trace"))

        ok = last.get("status") == "completed"
        if ok:
            print("\nRESULT: completed (orchestrator reported status=completed)")
        else:
            print("\nRESULT: failed or incomplete — see failure_phase and messages above")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
