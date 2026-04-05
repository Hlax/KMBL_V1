"""OpenClaw gateway HTTP transport — OpenAI-compatible chat completions."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.providers.kiloclaw_protocol import (
    KiloClawInvocationError,
    RoleType,
    provider_failure,
)
from kmbl_orchestrator.providers.kiloclaw_parsing import (
    _apply_role_contract,
    _extract_http_role_dict,
    _parse_chat_completion_json_content,
    _system_prompt_for_role,
)

_log = logging.getLogger(__name__)


def _openclaw_max_tokens_for_role(settings: Settings, role_type: RoleType) -> int | None:
    """Optional ``max_tokens`` on chat-completions requests (planner default 8192; others unset unless env)."""
    name = {
        "planner": "openclaw_chat_max_tokens_planner",
        "generator": "openclaw_chat_max_tokens_generator",
        "evaluator": "openclaw_chat_max_tokens_evaluator",
    }.get(role_type)
    if not name:
        return None
    mt = getattr(settings, name, None)
    if isinstance(mt, int) and mt > 0:
        return mt
    return None


class OpenClawHttpClient:
    """
    Synchronous HTTP — OpenAI-compatible **chat completions** on the local OpenClaw gateway.

    POST ``{OPENCLAW_BASE_URL}{OPENCLAW_INVOKE_PATH}`` (default ``http://127.0.0.1:18789/v1/chat/completions``)::

        model: ``openclaw:<agent_id>`` (``agent_id`` = ``provider_config_key``, e.g. ``kmbl-planner``)
        messages: system (role prompt) + user (JSON string of ``role_type``, ``config_key``, ``payload``)
        user: ``OPENCLAW_CHAT_COMPLETIONS_USER`` + optional ``:thread_id`` + optional ``:graph_run_id``
        (OpenAI session field — isolates gateway session state per thread and per run)

    Auth: when ``OPENCLAW_API_KEY`` is set, sends ``Authorization: Bearer`` and legacy
    ``x-kiloclaw-proxy-token`` (some gateways expect the latter). Omitted for loopback smoke without a token.

    Response: parse ``choices[0].message.content`` as JSON (markdown fences stripped), then the same
    unwrapping and role validation as other transports.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        base = self._settings.openclaw_base_url.rstrip("/")
        path = self._settings.openclaw_invoke_path.strip()
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = (self._settings.openclaw_api_key or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
            headers["x-kiloclaw-proxy-token"] = key
        else:
            _log.info(
                "openclaw_http_outbound no OPENCLAW_API_KEY; sending unauthenticated request to %s",
                url,
            )
        envelope = {
            "role_type": role_type,
            "config_key": provider_config_key,
            "payload": payload,
        }
        user_content = json.dumps(envelope, ensure_ascii=False)
        model = f"openclaw:{provider_config_key}"
        # OpenAI `user` is forwarded to the gateway. A single shared id (e.g. bare
        # ``kmbl-orchestrator``) can hit OpenClaw/KiloClaw internal errors (HTTP 500
        # ``api_error`` / "internal error") once session state grows; isolating by
        # ``thread_id`` fixes planner/generator/evaluator on the live stack.
        # Append ``graph_run_id`` when present so compaction / session history does not
        # bleed across runs on the same thread (e.g. unrelated tool-agent transcripts).
        chat_user = (self._settings.openclaw_chat_completions_user or "").strip() or "kmbl-orchestrator"
        tid = (payload.get("thread_id") or "").strip()
        if tid:
            chat_user = f"{chat_user}:{tid}"
        gid = (payload.get("graph_run_id") or "").strip()
        if gid:
            chat_user = f"{chat_user}:{gid}"
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _system_prompt_for_role(role_type)},
                {"role": "user", "content": user_content},
            ],
            "user": chat_user,
        }
        mt = _openclaw_max_tokens_for_role(self._settings, role_type)
        if mt is not None:
            body["max_tokens"] = mt
        t0 = time.perf_counter()
        conn_to = float(self._settings.openclaw_http_connect_timeout_sec or 30.0)
        read_to = float(self._settings.openclaw_http_read_timeout_sec or 300.0)
        _log.info(
            "openclaw_http_outbound start url=%s path=%s role_type=%s model=%s "
            "chat_completions_user=%s connect_timeout_sec=%s read_timeout_sec=%s "
            "user_content_len=%s elapsed_ms=0.0",
            url,
            path,
            role_type,
            model,
            chat_user,
            conn_to,
            read_to,
            len(user_content),
        )

        max_retries = 3
        retry_backoff_base = 1.0
        # Extended retry coverage: gateway errors, rate limits, timeouts, cloud edge cases
        retryable_status_codes = {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
        last_error: Exception | None = None
        r: httpx.Response | None = None

        for attempt in range(max_retries):
            try:
                timeout = httpx.Timeout(
                    connect=conn_to,
                    read=read_to,
                    write=read_to,
                    pool=read_to,
                )
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers=headers, json=body)

                if r.status_code in retryable_status_codes and attempt < max_retries - 1:
                    backoff = retry_backoff_base * (2 ** attempt)
                    _log.warning(
                        "openclaw_http_outbound retry attempt=%d/%d status=%d "
                        "backoff_sec=%.1f url=%s role_type=%s",
                        attempt + 1,
                        max_retries,
                        r.status_code,
                        backoff,
                        url,
                        role_type,
                    )
                    time.sleep(backoff)
                    continue
                break

            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff = retry_backoff_base * (2 ** attempt)
                    _log.warning(
                        "openclaw_http_outbound retry attempt=%d/%d exc=%s "
                        "backoff_sec=%.1f url=%s role_type=%s",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                        backoff,
                        url,
                        role_type,
                    )
                    time.sleep(backoff)
                    continue
                _log.exception(
                    "openclaw_http_outbound failed stage=request_error url=%s role_type=%s path=%s",
                    url,
                    role_type,
                    path,
                )
                raise KiloClawInvocationError(
                    str(e),
                    normalized=provider_failure(
                        f"request to OpenClaw gateway failed after {max_retries} attempts: {e!s}",
                        error_type="transport_error",
                        details={"exception_type": type(e).__name__, "attempts": max_retries},
                    ),
                ) from e

            except httpx.RequestError as e:
                # Retry certain request errors (read/write errors, connection resets)
                last_error = e
                if attempt < max_retries - 1:
                    backoff = retry_backoff_base * (2 ** attempt)
                    _log.warning(
                        "openclaw_http_outbound retry attempt=%d/%d exc=%s "
                        "backoff_sec=%.1f url=%s role_type=%s",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                        backoff,
                        url,
                        role_type,
                    )
                    time.sleep(backoff)
                    continue
                _log.exception(
                    "openclaw_http_outbound failed stage=request_error url=%s role_type=%s path=%s",
                    url,
                    role_type,
                    path,
                )
                raise KiloClawInvocationError(
                    str(e),
                    normalized=provider_failure(
                        f"request to OpenClaw gateway failed after {max_retries} attempts: {e!s}",
                        error_type="transport_error",
                        details={"exception_type": type(e).__name__, "attempts": max_retries},
                    ),
                ) from e

        if r is None:
            raise KiloClawInvocationError(
                str(last_error) if last_error else "unknown error after retries",
                normalized=provider_failure(
                    f"request to OpenClaw gateway failed after {max_retries} attempts",
                    error_type="transport_error",
                    details={"attempts": max_retries},
                ),
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log.info(
            "openclaw_http_outbound done url=%s path=%s role_type=%s http_status=%s elapsed_ms=%.1f",
            url,
            path,
            role_type,
            r.status_code,
            elapsed_ms,
        )

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise KiloClawInvocationError(
                "response is not valid JSON",
                normalized=provider_failure(
                    f"invalid JSON from OpenClaw gateway (HTTP {r.status_code})",
                    error_type="invalid_response",
                    details={"http_status": r.status_code, "text_preview": r.text[:500]},
                ),
            ) from e

        if r.status_code >= 400:
            msg = "unknown error"
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    msg = str(err.get("message") or err.get("type") or msg)
                else:
                    msg = str(data.get("message") or data.get("error") or msg)
            raise KiloClawInvocationError(
                f"HTTP {r.status_code}: {msg}",
                normalized=provider_failure(
                    msg,
                    error_type="provider_error",
                    details={"http_status": r.status_code, "body": data if isinstance(data, dict) else None},
                ),
            )

        if not isinstance(data, dict):
            raise KiloClawInvocationError(
                "response body must be a JSON object",
                normalized=provider_failure(
                    "invalid response: expected JSON object",
                    error_type="invalid_response",
                ),
            )
        try:
            parsed = _parse_chat_completion_json_content(data, role_type=role_type)
            out = _extract_http_role_dict(parsed, role_type=role_type)
        except KiloClawInvocationError:
            raise
        return _apply_role_contract(role_type, out)


# Backward-compatible name for imports and tests.
KiloClawHttpClient = OpenClawHttpClient
