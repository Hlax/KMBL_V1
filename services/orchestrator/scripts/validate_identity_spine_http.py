"""One-off HTTP validation for identity spine (orchestrator must be current code + DB migrated)."""

from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8012"


def main() -> None:
    client = httpx.Client(timeout=120.0)
    evidence: list[tuple[str, int, str]] = []

    def log(title: str, resp: httpx.Response) -> None:
        body = resp.text
        if len(body) > 1200:
            body = body[:1200] + "\n... [truncated]"
        evidence.append((title, resp.status_code, body))

    # 1) Identity CRUD
    iid = str(uuid.uuid4())
    r = client.post(
        f"{BASE}/orchestrator/identity/sources",
        json={
            "identity_id": iid,
            "source_type": "text",
            "raw_text": "spine validation source (redacted)",
        },
    )
    log("POST /orchestrator/identity/sources", r)
    r = client.put(
        f"{BASE}/orchestrator/identity/{iid}/profile",
        json={
            "profile_summary": "Spine validation profile",
            "facets_json": {"validation": "http_check"},
            "open_questions_json": ["q1"],
        },
    )
    log(f"PUT /orchestrator/identity/{iid}/profile", r)
    r = client.get(f"{BASE}/orchestrator/identity/{iid}/profile")
    log(f"GET /orchestrator/identity/{iid}/profile", r)
    r = client.get(f"{BASE}/orchestrator/identity/{iid}/sources")
    log(f"GET /orchestrator/identity/{iid}/sources", r)

    # 2) Non-identity run (regression)
    r = client.post(
        f"{BASE}/orchestrator/runs/start",
        json={
            "trigger_type": "prompt",
            "scenario_preset": "seeded_local_v1",
            "event_input": {},
        },
    )
    log("POST /orchestrator/runs/start (no identity_id)", r)
    r.raise_for_status()
    no_id_gid = r.json()["graph_run_id"]
    _wait_terminal(client, no_id_gid)
    r = client.get(f"{BASE}/orchestrator/runs/{no_id_gid}/detail")
    log(f"GET /orchestrator/runs/{no_id_gid}/detail (non-identity)", r)

    # 3) Identity run
    r = client.post(
        f"{BASE}/orchestrator/runs/start",
        json={
            "identity_id": iid,
            "trigger_type": "prompt",
            "scenario_preset": "seeded_local_v1",
            "event_input": {},
        },
    )
    log("POST /orchestrator/runs/start (with identity_id)", r)
    r.raise_for_status()
    id_gid = r.json()["graph_run_id"]
    _wait_terminal(client, id_gid)
    r = client.get(f"{BASE}/orchestrator/runs/{id_gid}/detail")
    log(f"GET /orchestrator/runs/{id_gid}/detail (identity)", r)
    r = client.get(f"{BASE}/orchestrator/staging", params={"limit": 5})
    log("GET /orchestrator/staging (recent)", r)

    print("=== VALIDATION EVIDENCE (status + redacted body) ===\n")
    for title, code, body in evidence:
        print(f"--- {title} --- HTTP {code}")
        print(body)
        print()


def _wait_terminal(client: httpx.Client, gid: str) -> None:
    for _ in range(90):
        r = client.get(f"{BASE}/orchestrator/runs/{gid}")
        r.raise_for_status()
        st = r.json().get("status")
        if st in ("completed", "failed"):
            return
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for graph_run {gid}")


if __name__ == "__main__":
    main()
