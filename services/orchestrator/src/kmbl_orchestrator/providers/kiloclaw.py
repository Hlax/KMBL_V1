"""KiloClaw role execution client — HTTP provider + deterministic stub (docs/09, docs/12 §6)."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

import httpx

from kmbl_orchestrator.config import Settings, get_settings

RoleType = Literal["planner", "generator", "evaluator"]

# docs/12_API_AND_SERVICE_LAYER.md §9 — normalized provider failure envelope
def provider_failure(
    message: str,
    *,
    error_type: str = "provider_error",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": "failed",
        "error_type": error_type,
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


def _unwrap_response_body(data: Any) -> dict[str, Any]:
    """Extract role output dict from common KiloClaw / gateway envelopes."""
    if not isinstance(data, dict):
        raise KiloClawInvocationError(
            "response body must be a JSON object",
            normalized=provider_failure(
                "invalid response: expected JSON object",
                error_type="invalid_response",
            ),
        )
    candidate: dict[str, Any] = data
    for key in ("output", "result", "data", "payload"):
        inner = data.get(key)
        if isinstance(inner, dict):
            candidate = inner
            break
    if candidate.get("status") == "failed" or candidate.get("error_type") == "provider_error":
        msg = str(candidate.get("message") or "provider reported failure")
        raise KiloClawInvocationError(
            msg,
            normalized=provider_failure(
                msg,
                details={k: v for k, v in candidate.items() if k not in ("message",)},
            ),
        )
    return candidate


def _validate_planner_output(body: dict[str, Any]) -> None:
    if "build_spec" not in body:
        raise KiloClawInvocationError(
            "planner output missing build_spec",
            normalized=provider_failure(
                "planner response missing required field: build_spec",
                error_type="invalid_response",
            ),
        )


def _validate_generator_output(body: dict[str, Any]) -> None:
    if not any(k in body for k in ("proposed_changes", "updated_state", "artifact_outputs")):
        raise KiloClawInvocationError(
            "generator output missing proposed_changes / updated_state / artifact_outputs",
            normalized=provider_failure(
                "generator response must include at least one of: "
                "proposed_changes, updated_state, artifact_outputs",
                error_type="invalid_response",
            ),
        )


def _validate_evaluator_output(body: dict[str, Any]) -> None:
    st = body.get("status")
    if st not in ("pass", "partial", "fail", "blocked"):
        raise KiloClawInvocationError(
            "evaluator output has invalid or missing status",
            normalized=provider_failure(
                "evaluator response must include status: pass | partial | fail | blocked",
                error_type="invalid_response",
            ),
        )


def _validate_role_output(role_type: RoleType, body: dict[str, Any]) -> None:
    if role_type == "planner":
        _validate_planner_output(body)
    elif role_type == "generator":
        _validate_generator_output(body)
    elif role_type == "evaluator":
        _validate_evaluator_output(body)


class KiloClawHttpClient:
    """
    Synchronous HTTP invoke to KiloClaw.

    Request: POST ``{KILOCLAW_BASE_URL}{KILOCLAW_INVOKE_PATH}`` (defaults to ``/invoke``) with JSON body::

        {"role_type": "...", "config_key": "<provider_config_key>", "payload": {...}}

    Auth: ``Authorization: Bearer <KILOCLAW_API_KEY>`` when API key is set.

    Response: JSON object; role output may be the root object or nested under
    ``output`` / ``result`` / ``data`` / ``payload``.
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
                "KILOCLAW_API_KEY is required for HTTP client",
                normalized=provider_failure(
                    "missing KILOCLAW_API_KEY",
                    error_type="configuration_error",
                ),
            )
        headers["Authorization"] = f"Bearer {key}"
        body = {
            "role_type": role_type,
            "config_key": provider_config_key,
            "payload": payload,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
                r = client.post(url, headers=headers, json=body)
        except httpx.RequestError as e:
            raise KiloClawInvocationError(
                str(e),
                normalized=provider_failure(
                    f"request to KiloClaw failed: {e!s}",
                    error_type="transport_error",
                    details={"exception_type": type(e).__name__},
                ),
            ) from e

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
                msg = str(data.get("message") or data.get("error") or msg)
            raise KiloClawInvocationError(
                f"HTTP {r.status_code}: {msg}",
                normalized=provider_failure(
                    msg,
                    error_type="provider_error",
                    details={"http_status": r.status_code, "body": data if isinstance(data, dict) else None},
                ),
            )

        try:
            out = _unwrap_response_body(data)
        except KiloClawInvocationError:
            raise

        try:
            _validate_role_output(role_type, out)
        except KiloClawInvocationError:
            raise

        return out


class KiloClawStubClient:
    """
    Deterministic placeholder responses for planner → generator → evaluator loop.

    Used when ``KILOCLAW_API_KEY`` is unset (local development without a live KiloClaw).
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
            return {
                "build_spec": {"title": "stub_spec", "steps": []},
                "constraints": {"scope": "minimal"},
                "success_criteria": ["loop_reaches_evaluator"],
                "evaluation_targets": ["smoke_check"],
            }
        if role_type == "generator":
            return {
                "proposed_changes": {"files": []},
                "artifact_outputs": [],
                "updated_state": {"revision": 1},
                "sandbox_ref": "stub-sandbox",
                "preview_url": "https://preview.example.invalid",
            }
        if role_type == "evaluator":
            iteration = payload.get("iteration_hint", 0)
            status: Literal["pass", "partial", "fail", "blocked"] = (
                "pass" if iteration >= 0 else "partial"
            )
            return {
                "status": status,
                "summary": "stub evaluation",
                "issues": [],
                "artifacts": [],
                "metrics": {"stub": True},
            }
        raise ValueError(f"unknown role_type: {role_type}")


def get_kiloclaw_client(settings: Settings | None = None) -> KiloClawClient:
    """HTTP client when ``KILOCLAW_API_KEY`` is set; otherwise stub."""
    s = settings or get_settings()
    if (s.kiloclaw_api_key or "").strip():
        return KiloClawHttpClient(settings=s)
    return KiloClawStubClient(settings=s)
