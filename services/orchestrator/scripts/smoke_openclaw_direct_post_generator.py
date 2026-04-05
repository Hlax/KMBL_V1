#!/usr/bin/env python3
"""
Direct POST to OpenClaw chat completions for **kmbl-generator** — proves the same JSON contract
as the orchestrator (``choices[0].message.content`` parses to a JSON object with generator fields).

Unlike ``smoke_openclaw_direct_post.py`` (planner-only), this catches gateway/model issues that
only appear under the generator role and full bootstrap.

Env:
  OPENCLAW_BASE_URL    (default http://127.0.0.1:18789)
  OPENCLAW_INVOKE_PATH (default /v1/chat/completions)
  OPENCLAW_API_KEY     (optional; falls back to ~/.openclaw/openclaw.json gateway token)

Exit 0 only when HTTP 200, content parses as JSON object, and at least one primary generator
field is non-empty (``proposed_changes``, ``updated_state``, or ``artifact_outputs``).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

_ORCH_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_ORCH_SRC) not in sys.path:
    sys.path.insert(0, str(_ORCH_SRC))

from kmbl_orchestrator.providers.kiloclaw_parsing import _strip_markdown_json_fence  # noqa: E402


def _load_token_from_openclaw_json() -> str:
    key = (os.environ.get("OPENCLAW_API_KEY") or "").strip()
    if key:
        return key
    try:
        p = Path.home() / ".openclaw" / "openclaw.json"
        if p.is_file():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            tok = (cfg.get("gateway") or {}).get("auth") or {}
            if isinstance(tok, dict):
                t = tok.get("token")
                if isinstance(t, str) and t.strip() and not t.startswith("__"):
                    return t.strip()
    except OSError:
        pass
    return ""


def main() -> int:
    base = (os.environ.get("OPENCLAW_BASE_URL") or "http://127.0.0.1:18789").rstrip("/")
    path = (os.environ.get("OPENCLAW_INVOKE_PATH") or "/v1/chat/completions").strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    key = _load_token_from_openclaw_json()

    # Minimal payload shape aligned with orchestrator generator invocations (small; not a full run).
    payload = {
        "thread_id": "00000000-0000-0000-0000-0000000000smoke",
        "build_spec": {
            "type": "generic",
            "title": "Smoke generator",
            "steps": [
                {"title": "Step 1", "description": "One-line smoke step."},
            ],
            "site_archetype": "minimal_single_surface",
            "experience_mode": "flat_standard",
        },
        "current_working_state": {},
        "iteration_feedback": None,
        "iteration_plan": None,
        "event_input": {"task": "direct_post_generator_smoke", "scenario": "smoke"},
    }
    body = {
        "model": "openclaw:kmbl-generator",
        "messages": [
            {
                "role": "system",
                "content": "You are the KMBL generator agent. Respond with valid JSON only.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "role_type": "generator",
                        "config_key": "kmbl-generator",
                        "payload": payload,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "max_tokens": int(os.environ.get("OPENCLAW_SMOKE_GENERATOR_MAX_TOKENS") or "4096"),
        "user": "kmbl-smoke-direct-generator",
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-kiloclaw-proxy-token"] = key

    print("POST", url)
    print("Authorization:", "set" if key else "none")
    print("model", body["model"])
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=300.0)
    except Exception as e:
        print("request_error", type(e).__name__, e)
        return 1

    print("http_status", r.status_code)
    if r.status_code >= 400:
        print(r.text[:2000])
        return 1

    try:
        data = r.json()
    except json.JSONDecodeError:
        print("invalid_json", r.text[:2000])
        return 1

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        print("missing_choices", json.dumps(data, indent=2)[:3000])
        return 1
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        print("missing_message", json.dumps(data, indent=2)[:3000])
        return 1
    content = msg.get("content")
    if content is None:
        print("missing_content", json.dumps(data, indent=2)[:3000])
        return 1

    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(p, str):
                parts.append(p)
        text = "\n".join(parts)
    else:
        text = content if isinstance(content, str) else str(content)

    if not text.strip():
        print("empty_content", json.dumps(data, indent=2)[:3000])
        return 1

    preview = text[:800]
    print("choices[0].message.content_len", len(text))
    print("choices[0].message.content_preview", preview)

    # Placeholders (orchestrator maps these to provider_error before JSON parse).
    low = text.strip().split("\n", 1)[0].strip().lower()
    if low in ("no_reply", "no response from openclaw."):
        print("FAIL: gateway/model placeholder response, not JSON — fix model, context, or bootstrap.")
        return 1

    raw = _strip_markdown_json_fence(text.strip())
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print("FAIL: message.content is not JSON (after fence strip):", e)
        print("raw_preview", text[:1200])
        return 1

    if not isinstance(parsed, dict):
        print("FAIL: JSON root must be an object, got", type(parsed).__name__)
        return 1

    pc = parsed.get("proposed_changes")
    us = parsed.get("updated_state")
    ao = parsed.get("artifact_outputs")
    has_pc = isinstance(pc, dict) and len(pc) > 0
    has_us = isinstance(us, dict) and len(us) > 0
    has_ao = isinstance(ao, list) and len(ao) > 0
    if not (has_pc or has_us or has_ao):
        print(
            "FAIL: generator JSON missing non-empty proposed_changes, updated_state, or artifact_outputs.",
            "keys:",
            list(parsed.keys())[:40],
        )
        return 1

    print("OK: kmbl-generator returned JSON with at least one primary generator field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
