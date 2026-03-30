"""KiloClaw / OpenClaw role execution — stub, HTTP (sync contract), or OpenClaw CLI (docs/09, docs/12 §6)."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from typing import Any, Literal, Protocol

import httpx
from pydantic import ValidationError

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.role_outputs import validate_role_contract

RoleType = Literal["planner", "generator", "evaluator"]

_log = logging.getLogger(__name__)

# docs/12_API_AND_SERVICE_LAYER.md §9 — normalized provider failure envelope
def provider_failure(
    message: str,
    *,
    error_kind: str = "provider_error",
    error_type: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    et = error_type if error_type is not None else error_kind
    out: dict[str, Any] = {
        "status": "failed",
        "error_kind": error_kind,
        "error_type": et,
        "message": message,
    }
    if details:
        out["details"] = details
    return out


class KiloClawInvocationError(Exception):
    """Raised when KiloClaw returns an error or an unusable payload (before invoker marks role_invocation)."""

    def __init__(self, message: str, *, normalized: dict[str, Any]) -> None:
        super().__init__(message)
        self.normalized = normalized


class KiloClawClient(Protocol):
    """Invokes a hosted role configuration in KiloClaw."""

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Returns structured role output (not transport framing)."""
        ...


def _looks_like_role_output(d: dict[str, Any]) -> bool:
    if "build_spec" in d:
        return True
    if d.get("status") in ("pass", "partial", "fail", "blocked"):
        return True
    if any(k in d for k in ("proposed_changes", "updated_state", "artifact_outputs")):
        return True
    return False


def _coerce_planner_wire_keys(d: dict[str, Any]) -> dict[str, Any]:
    """Map common camelCase aliases to planner contract snake_case (models / gateways vary)."""
    out = dict(d)
    if "build_spec" not in out and "buildSpec" in out:
        out["build_spec"] = out.pop("buildSpec")
    if "success_criteria" not in out and "successCriteria" in out:
        out["success_criteria"] = out.pop("successCriteria")
    if "evaluation_targets" not in out and "evaluationTargets" in out:
        out["evaluation_targets"] = out.pop("evaluationTargets")
    return out


def _dict_with_planner_build_spec(d: dict[str, Any]) -> dict[str, Any] | None:
    bs = d.get("build_spec")
    if bs is None and "buildSpec" in d:
        bs = d.get("buildSpec")
    if isinstance(bs, str):
        inner = _as_json_object_maybe(bs)
        if isinstance(inner, dict):
            out = _coerce_planner_wire_keys(dict(d))
            out["build_spec"] = inner
            return out
        return None
    if isinstance(bs, dict):
        return _coerce_planner_wire_keys(d)
    return None


def _as_json_object_maybe(v: Any) -> dict[str, Any] | None:
    """If ``v`` is or parses to a JSON object, return it (else None)."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s.startswith("{"):
            return None
        try:
            loaded = json.loads(s)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            try:
                return _decode_first_json_object_in_text(s)
            except json.JSONDecodeError:
                return None
    return None


def _find_planner_contract_dict(data: Any, depth: int = 0, max_depth: int = 6) -> dict[str, Any] | None:
    """
    Find a nested dict that looks like planner output (``build_spec`` object).

    Varied / long prompts often produce extra wrappers (``response`` → ``plan`` → …).
    """
    if depth > max_depth:
        return None
    if isinstance(data, dict):
        hit = _dict_with_planner_build_spec(data)
        if hit is not None:
            return hit
        for v in data.values():
            inner = _as_json_object_maybe(v)
            if inner is not None:
                found = _find_planner_contract_dict(inner, depth + 1, max_depth)
                if found is not None:
                    return found
            found = _find_planner_contract_dict(v, depth + 1, max_depth)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_planner_contract_dict(item, depth + 1, max_depth)
            if found is not None:
                return found
    return None


_VARIATION_ONLY_KEYS = frozenset(
    {
        "run_nonce",
        "variation_seed",
        "theme_variant",
        "subject_variant",
        "layout_variant",
        "tone_variant",
    }
)


def _looks_like_variation_only_echo(d: dict[str, Any]) -> bool:
    """Planner sometimes returns only ``event_input.variation`` JSON — not a valid contract."""
    if not d:
        return False
    if "build_spec" in d or "buildSpec" in d:
        return False
    ks = set(d.keys())
    return bool(ks) and ks <= _VARIATION_ONLY_KEYS


def _synthetic_planner_from_variation_echo(variation: dict[str, Any]) -> dict[str, Any]:
    """
    Narrow recovery: kmbl-planner sometimes echoes ``variation`` as the entire JSON reply on
    long varied gallery payloads. Map that to a minimal valid planner contract so the graph
    can proceed (variation remains on ``event_input`` for downstream roles).
    """
    return {
        "build_spec": {
            "type": "kmbl_seeded_gallery_strip_varied_v1",
            "title": "Varied gallery strip (local dev)",
            "steps": [
                {
                    "n": 1,
                    "what": "Emit ui_gallery_strip_v1 per event_input and variation",
                },
            ],
        },
        "constraints": {
            "recovered_from": "variation_only_planner_echo",
            "variation": dict(variation),
        },
        "success_criteria": [],
        "evaluation_targets": [],
    }


def _system_prompt_for_role(role_type: RoleType) -> str:
    if role_type == "planner":
        return (
            "You are the KMBL planner agent. Reply with a single JSON object only. "
            "Required top-level keys: build_spec (object), constraints (object), "
            "success_criteria (array), evaluation_targets (array). "
            "Do not respond with only event_input.variation fields (e.g. run_nonce, theme_variant); "
            "those are inputs, not the planner contract output."
        )
    labels = {"planner": "planner", "generator": "generator", "evaluator": "evaluator"}
    return f"You are the KMBL {labels[role_type]} agent. Respond with valid JSON only."


def _message_content_to_str(content: Any) -> str:
    """OpenAI ``message.content`` may be a string or a list of parts (e.g. ``{type:text}``)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                t = p.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return ""


def _assistant_message_body_for_json(msg: dict[str, Any]) -> str:
    """
    Primary JSON for the assistant turn: ``message.content``, or tool/function call ``arguments``
    when the gateway puts structured output there instead of ``content`` (common on long prompts).
    """
    raw = _message_content_to_str(msg.get("content"))
    if raw.strip():
        return raw
    tc = msg.get("tool_calls")
    if isinstance(tc, list):
        for call in tc:
            if not isinstance(call, dict):
                continue
            fn = call.get("function")
            if isinstance(fn, dict):
                args = fn.get("arguments")
                if isinstance(args, str) and args.strip():
                    return args
    fc = msg.get("function_call")
    if isinstance(fc, dict):
        args = fc.get("arguments")
        if isinstance(args, str) and args.strip():
            return args
    return ""


def _strip_markdown_json_fence(s: str) -> str:
    s = s.strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    if len(lines) < 2:
        return s
    body = "\n".join(lines[1:])
    body = re.sub(r"\n```\s*$", "", body, flags=re.MULTILINE)
    return body.strip()


def _iter_json_objects_in_text(text: str) -> list[dict[str, Any]]:
    """Every top-level JSON object in ``text`` (models sometimes emit multiple concatenated objects)."""
    decoder = json.JSONDecoder()
    out: list[dict[str, Any]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        try:
            val, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(val, dict):
            out.append(val)
        i = end
    return out


def _decode_first_json_object_in_text(text: str) -> dict[str, Any]:
    """
    Decode the first top-level JSON object embedded in ``text``.

    Models sometimes prepend prose (or wrap output in ways ``json.loads`` on the whole
    string cannot parse). ``JSONDecoder.raw_decode`` finds a valid object starting at a
    ``{`` even after leading text — matching kmbl-planner USER.md intent when the model
    drifts from “JSON only”.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            val, _end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict):
            return val
    raise json.JSONDecodeError("no JSON object found in assistant content", text, 0)


def extract_role_payload_from_openclaw_output(data: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce OpenClaw `openclaw agent --json` stdout (or equivalent) to one dict that matches
    planner / generator / evaluator role output fields.
    """
    if _looks_like_role_output(data):
        return data
    payloads: Any = None
    res = data.get("result")
    if isinstance(res, dict):
        payloads = res.get("payloads")
    if payloads is None:
        payloads = data.get("payloads")
    if isinstance(payloads, list) and payloads:
        p0 = payloads[0]
        if isinstance(p0, dict):
            text = p0.get("text")
            if isinstance(text, str) and text.strip():
                raw = _strip_markdown_json_fence(text)
                inner: dict[str, Any] | None = None
                try:
                    loaded = json.loads(raw)
                    inner = loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError:
                    try:
                        inner = _decode_first_json_object_in_text(raw)
                    except json.JSONDecodeError:
                        inner = None
                if inner is not None and _looks_like_role_output(inner):
                    return inner
    raise KiloClawInvocationError(
        "could not extract role payload from OpenClaw JSON",
        normalized=provider_failure(
            "OpenClaw response did not contain a recognizable role payload",
            error_kind="provider_error",
            error_type="invalid_response",
            details={"keys": list(data.keys())[:40]},
        ),
    )


def _parse_chat_completion_json_content(
    data: dict[str, Any], *, role_type: RoleType | None = None
) -> dict[str, Any]:
    """OpenAI chat.completion shape: parse JSON from ``choices[0].message.content``."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise KiloClawInvocationError(
            "chat completion missing choices",
            normalized=provider_failure(
                "invalid chat completion: missing choices",
                error_type="invalid_response",
                details={"keys": list(data.keys())[:40]},
            ),
        )
    c0 = choices[0]
    if not isinstance(c0, dict):
        raise KiloClawInvocationError(
            "chat completion choice is not an object",
            normalized=provider_failure(
                "invalid chat completion: choice[0] not an object",
                error_type="invalid_response",
            ),
        )
    msg = c0.get("message")
    if not isinstance(msg, dict):
        raise KiloClawInvocationError(
            "chat completion missing message",
            normalized=provider_failure(
                "invalid chat completion: missing message",
                error_type="invalid_response",
            ),
        )
    raw_content = _assistant_message_body_for_json(msg)
    if not raw_content.strip():
        raise KiloClawInvocationError(
            "chat completion missing message.content",
            normalized=provider_failure(
                "invalid chat completion: empty or missing message.content",
                error_type="invalid_response",
            ),
        )
    raw = _strip_markdown_json_fence(raw_content)
    e_first: json.JSONDecodeError | None = None
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        e_first = e
        parsed = None
        if role_type == "planner":
            objs = _iter_json_objects_in_text(raw)
            for obj in objs:
                hit = _find_planner_contract_dict(obj) or _dict_with_planner_build_spec(obj)
                if hit is not None:
                    return hit
        try:
            parsed = _decode_first_json_object_in_text(raw)
        except json.JSONDecodeError:
            assert e_first is not None
            raise KiloClawInvocationError(
                f"assistant content is not valid JSON: {e_first!s}",
                normalized=provider_failure(
                    "invalid JSON in assistant message.content",
                    error_type="invalid_response",
                    details={"preview": raw[:500]},
                ),
            ) from e_first

    if isinstance(parsed, list):
        if role_type == "planner":
            for item in parsed:
                if isinstance(item, dict):
                    hit = _find_planner_contract_dict(item) or _dict_with_planner_build_spec(item)
                    if hit is not None:
                        return hit
        raise KiloClawInvocationError(
            "assistant JSON root must be an object",
            normalized=provider_failure(
                "invalid response: assistant JSON must be a JSON object",
                error_type="invalid_response",
            ),
        )

    if not isinstance(parsed, dict):
        raise KiloClawInvocationError(
            "assistant JSON root must be an object",
            normalized=provider_failure(
                "invalid response: assistant JSON must be a JSON object",
                error_type="invalid_response",
            ),
        )

    if role_type == "planner":
        hit = _find_planner_contract_dict(parsed) or _dict_with_planner_build_spec(parsed)
        if hit is not None:
            return hit
    return parsed


def _extract_http_role_dict(
    data: dict[str, Any], *, role_type: RoleType | None = None
) -> dict[str, Any]:
    """Resolve HTTP JSON to a single role-shaped dict (KMBL wrapper or OpenClaw envelope)."""
    if data.get("status") == "failed" or data.get("error_type") == "provider_error":
        msg = str(data.get("message") or "provider reported failure")
        raise KiloClawInvocationError(
            msg,
            normalized=provider_failure(
                msg,
                details={k: v for k, v in data.items() if k != "message"},
            ),
        )
    # Include ``plan`` / ``planner_output`` — models often nest the contract under "plan"
    # when the task text says "plan" or "build_spec" (e.g. varied gallery longer prompt).
    for key in ("output", "result", "data", "payload", "plan", "planner_output"):
        inner = data.get(key)
        if isinstance(inner, dict) and _looks_like_role_output(inner):
            return inner
    if _looks_like_role_output(data):
        return data
    # Planner: wrappers may nest the contract more than one level (e.g. ``response.plan``).
    if role_type == "planner":
        found = _find_planner_contract_dict(data)
        if found is not None:
            return found
        for _k, v in data.items():
            if isinstance(v, dict) and _looks_like_role_output(v):
                return v
        if _looks_like_variation_only_echo(data):
            _log.warning(
                "kiloclaw_http planner returned variation-only JSON; applying gallery-varied synthetic contract"
            )
            return _synthetic_planner_from_variation_echo(data)
        _log.warning(
            "kiloclaw_http planner payload not recognized (before OpenClaw envelope scan): top_keys=%s",
            list(data.keys())[:30],
        )
    return extract_role_payload_from_openclaw_output(data)


def _apply_role_contract(role_type: RoleType, body: dict[str, Any]) -> dict[str, Any]:
    """Pydantic wire contract (see ``contracts.role_outputs``); maps errors to KiloClawInvocationError."""
    try:
        return validate_role_contract(role_type, body)
    except ValidationError as e:
        raise KiloClawInvocationError(
            f"role output contract validation failed: {e!s}",
            normalized=contract_validation_failure(
                phase=role_type,
                message="role output does not match KMBL wire contract",
                pydantic_errors=e.errors(),
            ),
        ) from e


class KiloClawHttpClient:
    """
    Synchronous HTTP — OpenAI-compatible **chat completions** on the KiloClaw gateway.

    POST ``{KILOCLAW_BASE_URL}{KILOCLAW_INVOKE_PATH}`` (default ``/v1/chat/completions``) with JSON::

        model: ``openclaw:<agent_id>`` (``agent_id`` = ``provider_config_key``, e.g. ``kmbl-planner``)
        messages: system (role prompt) + user (JSON string of ``role_type``, ``config_key``, ``payload``)
        user: ``KILOCLAW_CHAT_COMPLETIONS_USER`` (OpenAI session field)

    Auth: ``Authorization: Bearer <KILOCLAW_API_KEY>``. KiloClaw controllers on some deployments
    also accept the same token as ``x-kiloclaw-proxy-token``; we send both (same value) for compatibility.

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
        base = self._settings.kiloclaw_base_url.rstrip("/")
        path = self._settings.kiloclaw_invoke_path.strip()
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = (self._settings.kiloclaw_api_key or "").strip()
        if not key:
            raise KiloClawInvocationError(
                "KILOCLAW_API_KEY is required for HTTP transport",
                normalized=provider_failure(
                    "missing KILOCLAW_API_KEY",
                    error_type="configuration_error",
                ),
            )
        headers["Authorization"] = f"Bearer {key}"
        headers["x-kiloclaw-proxy-token"] = key
        envelope = {
            "role_type": role_type,
            "config_key": provider_config_key,
            "payload": payload,
        }
        user_content = json.dumps(envelope, ensure_ascii=False)
        model = f"openclaw:{provider_config_key}"
        chat_user = (self._settings.kiloclaw_chat_completions_user or "").strip() or "kmbl-orchestrator"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": _system_prompt_for_role(role_type)},
                {"role": "user", "content": user_content},
            ],
            "user": chat_user,
        }
        t0 = time.perf_counter()
        conn_to = float(self._settings.kiloclaw_http_connect_timeout_sec or 30.0)
        read_to = float(self._settings.kiloclaw_http_read_timeout_sec or 300.0)
        _log.info(
            "kiloclaw_http_outbound start url=%s path=%s role_type=%s model=%s "
            "connect_timeout_sec=%s read_timeout_sec=%s user_content_len=%s elapsed_ms=0.0",
            url,
            path,
            role_type,
            model,
            conn_to,
            read_to,
            len(user_content),
        )
        try:
            timeout = httpx.Timeout(
                connect=conn_to,
                read=read_to,
                write=read_to,
                pool=read_to,
            )
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=headers, json=body)
        except httpx.RequestError as e:
            _log.exception(
                "kiloclaw_http_outbound failed stage=request_error url=%s role_type=%s path=%s",
                url,
                role_type,
                path,
            )
            raise KiloClawInvocationError(
                str(e),
                normalized=provider_failure(
                    f"request to KiloClaw failed: {e!s}",
                    error_type="transport_error",
                    details={"exception_type": type(e).__name__},
                ),
            ) from e

        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log.info(
            "kiloclaw_http_outbound done url=%s path=%s role_type=%s http_status=%s elapsed_ms=%.1f",
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
                    f"invalid JSON from KiloClaw (HTTP {r.status_code})",
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


class OpenClawCliClient:
    """
    Synchronous OpenClaw CLI — runs ``openclaw agent --agent <config_key> --message <json> --json``.

    ``config_key`` must be the agent id (e.g. kmbl-planner). Message is JSON serialization of ``payload``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _ = role_type
        exe_name = (self._settings.kiloclaw_openclaw_executable or "openclaw").strip()
        exe = shutil.which(exe_name) or exe_name
        msg = json.dumps(payload, ensure_ascii=False)
        timeout = max(1, int(self._settings.kiloclaw_openclaw_timeout_sec))
        cmd: list[str] = [
            exe,
            "agent",
            "--agent",
            provider_config_key,
            "--message",
            msg,
            "--json",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise KiloClawInvocationError(
                "openclaw CLI timed out",
                normalized=provider_failure(
                    f"openclaw CLI exceeded {timeout}s",
                    error_type="transport_error",
                    details={"timeout_sec": timeout},
                ),
            ) from e
        except OSError as e:
            raise KiloClawInvocationError(
                str(e),
                normalized=provider_failure(
                    f"failed to run openclaw: {e!s}",
                    error_type="configuration_error",
                    details={"executable": exe},
                ),
            ) from e

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:2000]
            raise KiloClawInvocationError(
                f"openclaw exited {proc.returncode}",
                normalized=provider_failure(
                    "openclaw CLI failed",
                    error_type="provider_error",
                    details={"returncode": proc.returncode, "stderr_preview": err},
                ),
            )

        raw_out = (proc.stdout or "").strip()
        if not raw_out:
            raise KiloClawInvocationError(
                "openclaw returned empty stdout",
                normalized=provider_failure(
                    "openclaw CLI produced no output",
                    error_type="invalid_response",
                ),
            )
        try:
            envelope = json.loads(raw_out)
        except json.JSONDecodeError as e:
            raise KiloClawInvocationError(
                "openclaw stdout is not valid JSON",
                normalized=provider_failure(
                    f"invalid JSON from openclaw CLI: {e!s}",
                    error_type="invalid_response",
                    details={"text_preview": raw_out[:500]},
                ),
            ) from e
        if not isinstance(envelope, dict):
            raise KiloClawInvocationError(
                "openclaw JSON root must be an object",
                normalized=provider_failure(
                    "openclaw CLI returned non-object JSON",
                    error_type="invalid_response",
                ),
            )
        try:
            role_dict = extract_role_payload_from_openclaw_output(envelope)
        except KiloClawInvocationError:
            raise
        return _apply_role_contract(role_type, role_dict)


class KiloClawStubClient:
    """
    Deterministic placeholder responses for planner → generator → evaluator loop.

    Used when transport is ``stub`` (local development without OpenClaw).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _ = self._settings
        _ = provider_config_key
        if role_type == "planner":
            raw = {
                "build_spec": {
                    "type": "stub",
                    "title": "stub_spec",
                    "steps": [],
                },
                "constraints": {"scope": "minimal"},
                "success_criteria": ["loop_reaches_evaluator"],
                "evaluation_targets": ["smoke_check"],
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "generator":
            raw = {
                "proposed_changes": {"files": []},
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "https://preview.example.invalid",
            }
            return _apply_role_contract(role_type, raw)
        if role_type == "evaluator":
            iteration = payload.get("iteration_hint", 0)
            status: Literal["pass", "partial", "fail", "blocked"] = (
                "pass" if iteration >= 0 else "partial"
            )
            raw = {
                "status": status,
                "summary": "stub evaluation",
                "issues": [],
                "artifacts": [],
                "metrics": {"stub": True},
            }
            return _apply_role_contract(role_type, raw)
        raise ValueError(f"unknown role_type: {role_type}")


def get_kiloclaw_client(settings: Settings | None = None) -> KiloClawClient:
    """
    Select transport:

    - ``auto`` (default): ``http`` if ``KILOCLAW_API_KEY`` is set, else ``stub``.
    - ``stub``: deterministic loop.
    - ``http``: gateway chat completions (default path ``/v1/chat/completions``).
    - ``openclaw_cli``: local ``openclaw agent --json`` (co-located with the orchestrator).
    """
    s = settings or get_settings()
    t = (s.kiloclaw_transport or "auto").strip().lower()
    if t == "stub":
        return KiloClawStubClient(settings=s)
    if t == "openclaw_cli":
        return OpenClawCliClient(settings=s)
    if t == "http":
        return KiloClawHttpClient(settings=s)
    if t in ("auto", ""):
        if (s.kiloclaw_api_key or "").strip():
            return KiloClawHttpClient(settings=s)
        return KiloClawStubClient(settings=s)
    raise ValueError(f"unknown KILOCLAW_TRANSPORT: {s.kiloclaw_transport}")
