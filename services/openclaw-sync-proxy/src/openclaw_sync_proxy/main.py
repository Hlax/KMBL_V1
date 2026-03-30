"""
KMBL v1 synchronous invoke — POST /v1/invoke

Translates to: openclaw agent --agent <config_key> --message <json> --json

Environment:
  OPENCLAW_SYNC_PROXY_TOKEN — required Bearer token (same value as orchestrator KILOCLAW_API_KEY)
  OPENCLAW_EXECUTABLE — default openclaw
  OPENCLAW_TIMEOUT_SEC — default 300
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="OpenClaw sync proxy", version="0.1.0")


class InvokeBody(BaseModel):
    role_type: Literal["planner", "generator", "evaluator"]
    config_key: str = Field(..., min_length=1)
    payload: dict[str, Any]


def _strip_fence(s: str) -> str:
    s = s.strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    if len(lines) < 2:
        return s
    body = "\n".join(lines[1:])
    body = re.sub(r"\n```\s*$", "", body, flags=re.MULTILINE)
    return body.strip()


def _looks_role(d: dict[str, Any]) -> bool:
    if "build_spec" in d:
        return True
    if d.get("status") in ("pass", "partial", "fail", "blocked"):
        return True
    if any(k in d for k in ("proposed_changes", "updated_state", "artifact_outputs")):
        return True
    return False


def extract_role(data: dict[str, Any]) -> dict[str, Any]:
    if _looks_role(data):
        return data
    payloads: Any = None
    if isinstance(data.get("result"), dict):
        payloads = data["result"].get("payloads")
    if payloads is None:
        payloads = data.get("payloads")
    if isinstance(payloads, list) and payloads:
        p0 = payloads[0]
        if isinstance(p0, dict) and isinstance(p0.get("text"), str):
            raw = _strip_fence(p0["text"])
            inner = json.loads(raw)
            if isinstance(inner, dict) and _looks_role(inner):
                return inner
    raise ValueError("unrecognized OpenClaw output shape")


@app.get("/health")
def health() -> dict[str, str]:
    """Reports CLI backend — sync is implemented via local `openclaw` subprocess, not /hooks/agent."""
    exe = (os.environ.get("OPENCLAW_EXECUTABLE") or "openclaw").strip()
    return {
        "status": "ok",
        "service": "openclaw-sync-proxy",
        "backend": "openclaw_cli_subprocess",
        "openclaw_executable": exe,
    }


@app.post("/v1/invoke")
def invoke(
    body: InvokeBody,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    expected = (os.environ.get("OPENCLAW_SYNC_PROXY_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="OPENCLAW_SYNC_PROXY_TOKEN is not set on the proxy",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing Authorization: Bearer")
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid token")

    exe_name = (os.environ.get("OPENCLAW_EXECUTABLE") or "openclaw").strip()
    exe = shutil.which(exe_name) or exe_name
    msg = json.dumps(body.payload, ensure_ascii=False)
    timeout = int(os.environ.get("OPENCLAW_TIMEOUT_SEC") or "300")
    cmd = [exe, "agent", "--agent", body.config_key, "--message", msg, "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail=f"openclaw timed out after {timeout}s") from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"openclaw failed to run: {e!s}") from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[:2000]
        raise HTTPException(
            status_code=502,
            detail=f"openclaw exit {proc.returncode}: {err}",
        )

    raw = (proc.stdout or "").strip()
    if not raw:
        raise HTTPException(status_code=502, detail="openclaw returned empty stdout")
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"invalid JSON from openclaw: {e!s}") from e
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=502, detail="openclaw JSON root must be an object")
    try:
        role = extract_role(envelope)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=502, detail=f"could not extract role payload: {e!s}") from e

    return {"output": role}


def run() -> None:
    import uvicorn

    host = os.environ.get("OPENCLAW_SYNC_PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENCLAW_SYNC_PROXY_PORT", "8090"))
    uvicorn.run("openclaw_sync_proxy.main:app", host=host, port=port)


if __name__ == "__main__":
    run()
