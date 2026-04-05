"""
Direct POST to OpenClaw OpenAI-compatible chat completions — proves choices[0].message.content.

Env:
  OPENCLAW_BASE_URL   (default http://127.0.0.1:18789)
  OPENCLAW_INVOKE_PATH (default /v1/chat/completions)
  OPENCLAW_API_KEY    (Bearer + x-kiloclaw-proxy-token; required if gateway rejects unauthenticated)

Exit 0 only when HTTP 200 and JSON has choices[0].message.content (string or list parts).
"""
from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    base = (os.environ.get("OPENCLAW_BASE_URL") or "http://127.0.0.1:18789").rstrip("/")
    path = (os.environ.get("OPENCLAW_INVOKE_PATH") or "/v1/chat/completions").strip()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    key = (os.environ.get("OPENCLAW_API_KEY") or "").strip()
    if not key:
        # Local dev: reuse OpenClaw gateway token (same as orchestrator HTTP transport).
        try:
            import pathlib

            p = pathlib.Path.home() / ".openclaw" / "openclaw.json"
            if p.is_file():
                cfg = json.loads(p.read_text(encoding="utf-8"))
                tok = (cfg.get("gateway") or {}).get("auth") or {}
                if isinstance(tok, dict):
                    t = tok.get("token")
                    if isinstance(t, str) and t.strip() and not t.startswith("__"):
                        key = t.strip()
        except OSError:
            pass

    body = {
        "model": "openclaw:kmbl-planner",
        "messages": [
            {"role": "system", "content": "Reply with a single JSON object only."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "role_type": "planner",
                        "config_key": "kmbl-planner",
                        "payload": {
                            "thread_id": "00000000-0000-0000-0000-000000000001",
                            "identity_context": {},
                            "memory_context": {},
                            "event_input": {"task": "smoke_direct_post"},
                            "current_state_summary": {},
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "max_tokens": 256,
        "user": "kmbl-smoke-direct",
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-kiloclaw-proxy-token"] = key

    print("POST", url)
    print("Authorization:", "set" if key else "none")
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=180.0)
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
    if content is None or (isinstance(content, str) and not content.strip()):
        print("missing_or_empty_content", json.dumps(data, indent=2)[:3000])
        return 1

    preview = content if isinstance(content, str) else str(content)
    print("choices[0].message.content_len", len(preview))
    print("choices[0].message.content_preview", preview[:800])
    print("OK: OpenClaw chat-completions returned usable assistant content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
