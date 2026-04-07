"""KiloClaw response parsing and role contract validation helpers.

Shared between HTTP and CLI transports.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from kmbl_orchestrator.contracts.normalized_errors import contract_validation_failure
from kmbl_orchestrator.contracts.role_outputs import validate_role_contract
from kmbl_orchestrator.providers.kiloclaw_protocol import (
    KiloClawInvocationError,
    RoleType,
    provider_failure,
)

_log = logging.getLogger(__name__)


def _looks_like_role_output(d: dict[str, Any]) -> bool:
    if "build_spec" in d:
        return True
    if d.get("status") in ("pass", "partial", "fail", "blocked"):
        return True
    if any(k in d for k in ("proposed_changes", "updated_state", "artifact_outputs")):
        return True
    cf = d.get("contract_failure")
    if isinstance(cf, dict) and isinstance(cf.get("code"), str) and cf["code"].strip():
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
    """OpenAI ``message.content`` may be a string, a list of parts, or (non-standard) a dict.

    Some gateways (including OpenClaw) may return ``content`` as an already-parsed
    JSON object (dict) instead of a JSON string.  Serialize it back so downstream
    ``json.loads`` can handle it uniformly.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # Non-standard: gateway returned parsed object — serialize back to JSON string.
        return json.dumps(content, ensure_ascii=False)
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


_OPENCLAW_PLACEHOLDER_HINT = (
    "OpenClaw returned a placeholder instead of JSON (NO_REPLY or empty gateway response). "
    "Check Ollama logs, context size, bootstrap limits (bootstrapMaxChars), assign a "
    "JSON-capable model for kmbl-generator/kmbl-evaluator, or shorten SOUL/bootstrap text."
)


def _openclaw_placeholder_user_message(raw_after_fence: str) -> str | None:
    """
    Detect short gateway/model sentinel strings before ``json.loads`` so failures are actionable.

    Common when the local model returns ``NO_REPLY`` or the gateway substitutes
    ``No response from OpenClaw.`` — not recoverable as role JSON.
    """
    t = raw_after_fence.strip()
    if not t:
        return None
    first = t.split("\n", 1)[0].strip()
    if len(first) > 280:
        return None
    fl = first.lower()
    if fl in ("no_reply", "no response from openclaw."):
        return _OPENCLAW_PLACEHOLDER_HINT
    return None


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
    drifts from "JSON only".
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
    # Last-resort deep scan: walk all nested dict values (1 level) for role output.
    # Catches gateways that nest the payload under arbitrary keys not tried above.
    for _k, v in data.items():
        if isinstance(v, dict) and _looks_like_role_output(v):
            _log.info(
                "extract_role_payload_from_openclaw_output recovered from nested key=%r",
                _k,
            )
            return v
        # Also check one level deeper (e.g. ``result.output`` where result has no payloads).
        if isinstance(v, dict):
            for _k2, v2 in v.items():
                if isinstance(v2, dict) and _looks_like_role_output(v2):
                    _log.info(
                        "extract_role_payload_from_openclaw_output recovered from nested key=%r.%r",
                        _k,
                        _k2,
                    )
                    return v2
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
    if raw_content.lstrip().startswith("```"):
        _log.info(
            "role_output_normalization step=stripped_markdown_json_fence role_type=%s",
            role_type,
        )
    raw = _strip_markdown_json_fence(raw_content)

    _log.debug(
        "openclaw_http_inbound role_type=%s raw_content_len=%d raw_preview=%s",
        role_type,
        len(raw),
        raw[:500] if raw else "<empty>",
    )

    ph = _openclaw_placeholder_user_message(raw)
    if ph is not None:
        raise KiloClawInvocationError(
            ph,
            normalized=provider_failure(
                ph,
                error_type="provider_error",
                details={
                    "preview": raw[:500],
                    "kind": "openclaw_placeholder",
                    "failure_severity": "fatal",
                    "failure_class": "no_reply_or_empty_gateway",
                },
            ),
        )

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
        elif role_type in ("generator", "evaluator"):
            # Parity with planner: scan ALL objects for the first role-shaped dict
            # instead of blindly taking the first JSON object (which may be metadata).
            objs = _iter_json_objects_in_text(raw)
            for obj in objs:
                if _looks_like_role_output(obj):
                    _log.info(
                        "role_output_normalization step=multi_object_scan_recovery "
                        "role_type=%s matched_keys=%s",
                        role_type,
                        [k for k in obj if k in ("proposed_changes", "updated_state", "artifact_outputs", "status")],
                    )
                    return obj
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
        # Recovery: scan list for first dict that looks like role output
        if role_type == "planner":
            for item in parsed:
                if isinstance(item, dict):
                    hit = _find_planner_contract_dict(item) or _dict_with_planner_build_spec(item)
                    if hit is not None:
                        return hit
        elif role_type in ("generator", "evaluator"):
            # Generator/evaluator: find first dict matching role output keys
            for item in parsed:
                if isinstance(item, dict) and _looks_like_role_output(item):
                    _log.warning(
                        "openclaw %s returned list-root JSON; recovering first matching dict",
                        role_type,
                    )
                    return item
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
                "openclaw_http planner returned variation-only JSON; applying gallery-varied synthetic contract"
            )
            return _synthetic_planner_from_variation_echo(data)
        _log.warning(
            "openclaw_http planner payload not recognized (before OpenClaw envelope scan): top_keys=%s",
            list(data.keys())[:30],
        )
    elif role_type in ("generator", "evaluator"):
        # Parity with planner: scan all top-level values for role-shaped dicts.
        # Gateways may wrap the actual role output under an unexpected key
        # (e.g. ``response``, ``answer``, ``generated``, ``content``).
        for _k, v in data.items():
            if isinstance(v, dict) and _looks_like_role_output(v):
                _log.info(
                    "openclaw_http %s recovered role output from wrapper key=%r",
                    role_type,
                    _k,
                )
                return v
    return extract_role_payload_from_openclaw_output(data)


def _soft_fill_missing_contract_fields(
    role_type: RoleType, body: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """
    Best-effort defaults for early-stage agent output (logged, not silent).

    Does not invent required semantic fields (e.g. planner ``build_spec``, evaluator ``status``).
    """
    steps: list[str] = []
    out = dict(body)
    if role_type == "planner":
        if "constraints" not in out:
            out["constraints"] = {}
            steps.append("defaulted_planner_constraints_empty_object")
        if "success_criteria" not in out:
            out["success_criteria"] = []
            steps.append("defaulted_planner_success_criteria_empty_array")
        if "evaluation_targets" not in out:
            out["evaluation_targets"] = []
            steps.append("defaulted_planner_evaluation_targets_empty_array")
    elif role_type == "evaluator":
        if "issues" not in out:
            out["issues"] = []
            steps.append("defaulted_evaluator_issues_empty_array")
        if "metrics" not in out:
            out["metrics"] = {}
            steps.append("defaulted_evaluator_metrics_empty_object")
        if "artifacts" not in out:
            out["artifacts"] = []
            steps.append("defaulted_evaluator_artifacts_empty_array")
    if steps:
        _log.info(
            "role_output_normalization role_type=%s steps=%s",
            role_type,
            steps,
        )
    return out, steps


def _apply_role_contract(role_type: RoleType, body: dict[str, Any]) -> dict[str, Any]:
    """Pydantic wire contract (see ``contracts.role_outputs``); maps errors to KiloClawInvocationError."""
    filled, _steps = _soft_fill_missing_contract_fields(role_type, body)
    try:
        return validate_role_contract(role_type, filled)
    except ValidationError as e:
        raise KiloClawInvocationError(
            f"role output contract validation failed: {e!s}",
            normalized=contract_validation_failure(
                phase=role_type,
                message="role output does not match KMBL wire contract",
                pydantic_errors=e.errors(),
            ),
        ) from e
