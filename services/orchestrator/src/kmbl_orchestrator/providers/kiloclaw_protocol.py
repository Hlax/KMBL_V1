"""OpenClaw gateway protocol, error types, and factory (HTTP / CLI / stub).

Shared between all transports. Module path ``kiloclaw_*`` is historical; runtime targets OpenClaw.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from kmbl_orchestrator.config import Settings, get_settings

RoleType = Literal["planner", "generator", "evaluator"]

_log = logging.getLogger(__name__)

_LEGACY_INVALID_BASE_URL = "https://kiloclaw.example.invalid"


class KiloclawTransportConfigError(ValueError):
    """Role gateway transport selection or required credentials are invalid (fail fast)."""


OpenclawTransportConfigError = KiloclawTransportConfigError


@dataclass(frozen=True)
class OpenclawTransportResolution:
    """Resolved transport for logging, health, and per-invocation tracing."""

    configured: str
    resolved: Literal["stub", "http", "openclaw_cli"]
    auto_resolution_note: str | None
    stub_mode: bool
    api_key_present: bool
    openclaw_cli_path: str | None

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "openclaw_transport_configured": self.configured,
            "openclaw_transport_resolved": self.resolved,
            "openclaw_stub_mode": self.stub_mode,
            "openclaw_api_key_present": self.api_key_present,
            "openclaw_auto_resolution_note": self.auto_resolution_note,
            "openclaw_openclaw_cli_path": self.openclaw_cli_path,
        }


KiloclawTransportResolution = OpenclawTransportResolution


def _is_loopback_gateway_url(url: str) -> bool:
    u = url.strip().rstrip("/").lower()
    return u.startswith("http://127.0.0.1:") or u.startswith("http://localhost:")


def _validate_http_settings(settings: Settings, *, context: str) -> None:
    base = (settings.openclaw_base_url or "").strip()
    if not base:
        raise KiloclawTransportConfigError(
            f"{context}: OPENCLAW_BASE_URL is required for HTTP transport."
        )
    if base.rstrip("/") == _LEGACY_INVALID_BASE_URL.rstrip("/"):
        raise KiloclawTransportConfigError(
            f"{context}: OPENCLAW_BASE_URL is still the legacy placeholder {_LEGACY_INVALID_BASE_URL!r}; "
            "set a real gateway URL (e.g. http://127.0.0.1:18789)."
        )
    key = (settings.openclaw_api_key or "").strip()
    loopback = _is_loopback_gateway_url(base)
    if not key and not loopback:
        raise KiloclawTransportConfigError(
            f"{context}: OPENCLAW_API_KEY is required for HTTP transport when the gateway is not loopback "
            "(set a token from gateway.auth.token, or use http://127.0.0.1 / http://localhost for local smoke)."
        )


def _validate_openclaw_cli_settings(settings: Settings, *, context: str) -> str:
    exe_name = (settings.openclaw_openclaw_executable or "openclaw").strip()
    resolved = shutil.which(exe_name) or ""
    if not resolved:
        raise KiloclawTransportConfigError(
            f"{context}: openclaw executable {exe_name!r} not found on PATH "
            "(set OPENCLAW_OPENCLAW_EXECUTABLE or install OpenClaw CLI)."
        )
    return resolved


def _auto_prefers_http(settings: Settings) -> bool:
    """Prefer HTTP when API key is set, or (non-production) when loopback gateway URL is configured."""
    if bool((settings.openclaw_api_key or "").strip()):
        return True
    if settings.kmbl_env == "production":
        return False
    base = (settings.openclaw_base_url or "").strip()
    return bool(base) and _is_loopback_gateway_url(base)


def compute_openclaw_resolution(settings: Settings) -> OpenclawTransportResolution:
    """
    Resolve and validate transport. Raises KiloclawTransportConfigError if the selection
    is inconsistent with credentials or production stub policy (no silent downgrade).
    """
    configured = (settings.openclaw_transport or "auto").strip().lower()
    api_key_present = bool((settings.openclaw_api_key or "").strip())
    allow_stub = settings.effective_allow_stub_transport()

    if configured == "stub":
        if not allow_stub:
            raise KiloclawTransportConfigError(
                "OPENCLAW_TRANSPORT=stub is not allowed: set ALLOW_STUB_TRANSPORT=true "
                "or use a non-production KMBL_ENV."
            )
        return OpenclawTransportResolution(
            configured="stub",
            resolved="stub",
            auto_resolution_note=None,
            stub_mode=True,
            api_key_present=api_key_present,
            openclaw_cli_path=None,
        )

    if configured == "http":
        _validate_http_settings(settings, context="OPENCLAW_TRANSPORT=http")
        return OpenclawTransportResolution(
            configured="http",
            resolved="http",
            auto_resolution_note=None,
            stub_mode=False,
            api_key_present=api_key_present,
            openclaw_cli_path=None,
        )

    if configured == "openclaw_cli":
        path = _validate_openclaw_cli_settings(settings, context="OPENCLAW_TRANSPORT=openclaw_cli")
        return OpenclawTransportResolution(
            configured="openclaw_cli",
            resolved="openclaw_cli",
            auto_resolution_note=None,
            stub_mode=False,
            api_key_present=api_key_present,
            openclaw_cli_path=path,
        )

    if configured in ("auto", ""):
        if _auto_prefers_http(settings):
            note = "api_key_present_selected_http" if api_key_present else "loopback_gateway_auto_http"
            _validate_http_settings(settings, context="OPENCLAW_TRANSPORT=auto→http")
            return OpenclawTransportResolution(
                configured="auto",
                resolved="http",
                auto_resolution_note=note,
                stub_mode=False,
                api_key_present=api_key_present,
                openclaw_cli_path=None,
            )
        if not allow_stub:
            raise KiloclawTransportConfigError(
                "OPENCLAW_TRANSPORT=auto would use stub, but stub transport is "
                "not allowed for this deployment (KMBL_ENV=production without ALLOW_STUB_TRANSPORT). "
                "Set OPENCLAW_API_KEY and OPENCLAW_BASE_URL, set OPENCLAW_TRANSPORT=http, "
                "or set ALLOW_STUB_TRANSPORT=true only if you intentionally accept stubbed agents."
            )
        return OpenclawTransportResolution(
            configured="auto",
            resolved="stub",
            auto_resolution_note="no_http_credentials_auto_stub",
            stub_mode=True,
            api_key_present=False,
            openclaw_cli_path=None,
        )

    raise KiloclawTransportConfigError(
        f"Unknown OPENCLAW_TRANSPORT={settings.openclaw_transport!r} "
        "(expected auto, stub, http, openclaw_cli)."
    )


compute_kiloclaw_resolution = compute_openclaw_resolution


def assert_openclaw_role_invocation_permitted(
    *,
    settings: Settings,
    client: Any,
) -> OpenclawTransportResolution:
    """
    Fail-safe enforcement at the role invocation boundary (not only at client construction).

    Catches injected stub clients in production-like configs and re-validates transport resolution.
    """
    from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError
    from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

    try:
        resolution = compute_openclaw_resolution(settings)
    except KiloclawTransportConfigError as e:
        raise KiloclawRoleInvocationForbiddenError(
            "OpenClaw gateway transport configuration does not allow role invocation.",
            operator_hint=str(e),
        ) from e

    if isinstance(client, KiloClawStubClient) and not settings.effective_allow_stub_transport():
        raise KiloclawRoleInvocationForbiddenError(
            "Stub role-gateway transport is forbidden in this deployment "
            "(KMBL_ENV=production without ALLOW_STUB_TRANSPORT=true).",
            operator_hint=(
                "Configure OPENCLAW_API_KEY and HTTP transport, or set ALLOW_STUB_TRANSPORT=true "
                "only for intentional stubbed demos."
            ),
        )
    return resolution


assert_kiloclaw_role_invocation_permitted = assert_openclaw_role_invocation_permitted


def log_openclaw_transport_banner(settings: Settings | None = None) -> None:
    """Startup visibility: resolved transport and whether stub mode is active."""
    s = settings or get_settings()
    try:
        r = compute_openclaw_resolution(s)
    except KiloclawTransportConfigError as e:
        _log.error(
            "OpenClaw gateway transport configuration INVALID — invocations will fail until fixed: %s",
            e,
        )
        return
    msg = (
        "OpenClaw transport resolved: configured=%s resolved=%s stub_mode=%s "
        "api_key_present=%s allow_stub=%s kmbl_env=%s note=%s openclaw_cli=%s"
    )
    args = (
        r.configured,
        r.resolved,
        r.stub_mode,
        r.api_key_present,
        s.effective_allow_stub_transport(),
        s.kmbl_env,
        r.auto_resolution_note or "",
        r.openclaw_cli_path or "",
    )
    if r.stub_mode:
        _log.warning(msg, *args)
        _log.warning(
            "STUB role-gateway transport is active — planner/generator/evaluator are NOT real "
            "OpenClaw HTTP calls."
        )
    else:
        _log.info(msg, *args)


log_kiloclaw_transport_banner = log_openclaw_transport_banner


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
    """Invokes a hosted role configuration via the OpenClaw-compatible gateway."""

    def invoke_role(
        self,
        role_type: RoleType,
        provider_config_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Returns structured role output (not transport framing)."""
        ...


OpenClawGatewayClient = KiloClawClient


def get_openclaw_client_with_trace(
    settings: Settings | None = None,
) -> tuple[KiloClawClient, dict[str, Any]]:
    """
    Build the gateway client and a trace dict for routing_metadata_json / logging.
    Raises KiloclawTransportConfigError when transport credentials or policy forbid selection.
    """
    from kmbl_orchestrator.providers.kiloclaw_http import OpenClawHttpClient
    from kmbl_orchestrator.providers.kiloclaw_cli import OpenClawCliClient
    from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

    s = settings or get_settings()
    resolution = compute_openclaw_resolution(s)
    trace = resolution.to_trace_dict()

    if resolution.resolved == "stub":
        return KiloClawStubClient(settings=s), trace
    if resolution.resolved == "http":
        return OpenClawHttpClient(settings=s), trace
    if resolution.resolved == "openclaw_cli":
        return OpenClawCliClient(settings=s), trace
    raise AssertionError(f"unexpected resolved transport: {resolution.resolved}")


get_kiloclaw_client_with_trace = get_openclaw_client_with_trace


def get_openclaw_client(settings: Settings | None = None) -> KiloClawClient:
    """
    Select transport (validated — no silent downgrade from http/cli intent to stub).

    - ``auto``: ``http`` when API key or (dev) loopback gateway URL is configured, else ``stub`` if allowed.
    - ``stub``: deterministic loop (disallowed in production unless ALLOW_STUB_TRANSPORT).
    - ``http``: gateway chat completions.
    - ``openclaw_cli``: local ``openclaw agent --json``.
    """
    client, _ = get_openclaw_client_with_trace(settings)
    return client


get_kiloclaw_client = get_openclaw_client

