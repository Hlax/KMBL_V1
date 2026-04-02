"""KiloClaw protocol, error types, and factory.

Shared between all transports (HTTP, CLI, stub).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from kmbl_orchestrator.config import Settings, get_settings

RoleType = Literal["planner", "generator", "evaluator"]

_log = logging.getLogger(__name__)

_DEFAULT_INVALID_KILOCLAW_BASE_URL = "https://kiloclaw.example.invalid"


class KiloclawTransportConfigError(ValueError):
    """KiloClaw transport selection or required credentials are invalid (fail fast)."""


@dataclass(frozen=True)
class KiloclawTransportResolution:
    """Resolved transport for logging, health, and per-invocation tracing."""

    configured: str
    resolved: Literal["stub", "http", "openclaw_cli"]
    auto_resolution_note: str | None
    stub_mode: bool
    api_key_present: bool
    openclaw_cli_path: str | None

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "kiloclaw_transport_configured": self.configured,
            "kiloclaw_transport_resolved": self.resolved,
            "kiloclaw_stub_mode": self.stub_mode,
            "kiloclaw_api_key_present": self.api_key_present,
            "kiloclaw_auto_resolution_note": self.auto_resolution_note,
            "kiloclaw_openclaw_cli_path": self.openclaw_cli_path,
        }


def _validate_http_settings(settings: Settings, *, context: str) -> None:
    key = (settings.kiloclaw_api_key or "").strip()
    if not key:
        raise KiloclawTransportConfigError(
            f"{context}: KILOCLAW_API_KEY is required for HTTP transport (no silent fallback to stub)."
        )
    base = (settings.kiloclaw_base_url or "").strip()
    if not base:
        raise KiloclawTransportConfigError(
            f"{context}: KILOCLAW_BASE_URL is required for HTTP transport."
        )
    if base.rstrip("/") == _DEFAULT_INVALID_KILOCLAW_BASE_URL.rstrip("/"):
        raise KiloclawTransportConfigError(
            f"{context}: KILOCLAW_BASE_URL is still the placeholder {_DEFAULT_INVALID_KILOCLAW_BASE_URL!r}; "
            "set a real gateway URL."
        )


def _validate_openclaw_cli_settings(settings: Settings, *, context: str) -> str:
    exe_name = (settings.kiloclaw_openclaw_executable or "openclaw").strip()
    resolved = shutil.which(exe_name) or ""
    if not resolved:
        raise KiloclawTransportConfigError(
            f"{context}: openclaw executable {exe_name!r} not found on PATH "
            "(set KILOCLAW_OPENCLAW_EXECUTABLE or install OpenClaw CLI)."
        )
    return resolved


def compute_kiloclaw_resolution(settings: Settings) -> KiloclawTransportResolution:
    """
    Resolve and validate transport. Raises KiloclawTransportConfigError if the selection
    is inconsistent with credentials or production stub policy (no silent downgrade).
    """
    configured = (settings.kiloclaw_transport or "auto").strip().lower()
    api_key_present = bool((settings.kiloclaw_api_key or "").strip())
    allow_stub = settings.effective_allow_stub_transport()

    if configured == "stub":
        if not allow_stub:
            raise KiloclawTransportConfigError(
                "KILOCLAW_TRANSPORT=stub is not allowed: set ALLOW_STUB_TRANSPORT=true "
                "or use a non-production KMBL_ENV."
            )
        return KiloclawTransportResolution(
            configured="stub",
            resolved="stub",
            auto_resolution_note=None,
            stub_mode=True,
            api_key_present=api_key_present,
            openclaw_cli_path=None,
        )

    if configured == "http":
        _validate_http_settings(settings, context="KILOCLAW_TRANSPORT=http")
        return KiloclawTransportResolution(
            configured="http",
            resolved="http",
            auto_resolution_note=None,
            stub_mode=False,
            api_key_present=True,
            openclaw_cli_path=None,
        )

    if configured == "openclaw_cli":
        path = _validate_openclaw_cli_settings(settings, context="KILOCLAW_TRANSPORT=openclaw_cli")
        return KiloclawTransportResolution(
            configured="openclaw_cli",
            resolved="openclaw_cli",
            auto_resolution_note=None,
            stub_mode=False,
            api_key_present=api_key_present,
            openclaw_cli_path=path,
        )

    if configured in ("auto", ""):
        if api_key_present:
            _validate_http_settings(settings, context="KILOCLAW_TRANSPORT=auto→http")
            return KiloclawTransportResolution(
                configured="auto",
                resolved="http",
                auto_resolution_note="api_key_present_selected_http",
                stub_mode=False,
                api_key_present=True,
                openclaw_cli_path=None,
            )
        if not allow_stub:
            raise KiloclawTransportConfigError(
                "KILOCLAW_TRANSPORT=auto would use stub (no KILOCLAW_API_KEY), but stub transport is "
                "not allowed for this deployment (KMBL_ENV=production without ALLOW_STUB_TRANSPORT). "
                "Set KILOCLAW_API_KEY and a valid KILOCLAW_BASE_URL, set KILOCLAW_TRANSPORT=http, "
                "or set ALLOW_STUB_TRANSPORT=true only if you intentionally accept stubbed agents."
            )
        return KiloclawTransportResolution(
            configured="auto",
            resolved="stub",
            auto_resolution_note="no_api_key_auto_stub",
            stub_mode=True,
            api_key_present=False,
            openclaw_cli_path=None,
        )

    raise KiloclawTransportConfigError(
        f"Unknown KILOCLAW_TRANSPORT={settings.kiloclaw_transport!r} "
        "(expected auto, stub, http, openclaw_cli)."
    )


def assert_kiloclaw_role_invocation_permitted(
    *,
    settings: Settings,
    client: Any,
) -> KiloclawTransportResolution:
    """
    Fail-safe enforcement at the role invocation boundary (not only at client construction).

    Catches injected stub clients in production-like configs and re-validates transport resolution.
    """
    from kmbl_orchestrator.errors import KiloclawRoleInvocationForbiddenError
    from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

    try:
        resolution = compute_kiloclaw_resolution(settings)
    except KiloclawTransportConfigError as e:
        raise KiloclawRoleInvocationForbiddenError(
            "KiloClaw transport configuration does not allow role invocation.",
            operator_hint=str(e),
        ) from e

    if isinstance(client, KiloClawStubClient) and not settings.effective_allow_stub_transport():
        raise KiloclawRoleInvocationForbiddenError(
            "Stub KiloClaw transport is forbidden in this deployment "
            "(KMBL_ENV=production without ALLOW_STUB_TRANSPORT=true).",
            operator_hint=(
                "Configure KILOCLAW_API_KEY and HTTP transport, or set ALLOW_STUB_TRANSPORT=true "
                "only for intentional stubbed demos."
            ),
        )
    return resolution


def log_kiloclaw_transport_banner(settings: Settings | None = None) -> None:
    """Startup visibility: resolved transport and whether stub mode is active."""
    s = settings or get_settings()
    try:
        r = compute_kiloclaw_resolution(s)
    except KiloclawTransportConfigError as e:
        _log.error(
            "KiloClaw transport configuration INVALID — invocations will fail until fixed: %s",
            e,
        )
        return
    msg = (
        "KiloClaw transport resolved: configured=%s resolved=%s stub_mode=%s "
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
            "KiloClaw STUB transport is active — planner/generator/evaluator are NOT real "
            "OpenClaw/KiloClaw HTTP calls."
        )
    else:
        _log.info(msg, *args)


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


def get_kiloclaw_client_with_trace(
    settings: Settings | None = None,
) -> tuple[KiloClawClient, dict[str, Any]]:
    """
    Build the KiloClaw client and a trace dict for routing_metadata_json / logging.
    Raises KiloclawTransportConfigError when transport credentials or policy forbid selection.
    """
    from kmbl_orchestrator.providers.kiloclaw_http import KiloClawHttpClient
    from kmbl_orchestrator.providers.kiloclaw_cli import OpenClawCliClient
    from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient

    s = settings or get_settings()
    resolution = compute_kiloclaw_resolution(s)
    trace = resolution.to_trace_dict()

    if resolution.resolved == "stub":
        return KiloClawStubClient(settings=s), trace
    if resolution.resolved == "http":
        return KiloClawHttpClient(settings=s), trace
    if resolution.resolved == "openclaw_cli":
        return OpenClawCliClient(settings=s), trace
    raise AssertionError(f"unexpected resolved transport: {resolution.resolved}")


def get_kiloclaw_client(settings: Settings | None = None) -> KiloClawClient:
    """
    Select transport (validated — no silent downgrade from http/cli intent to stub).

    - ``auto``: ``http`` if ``KILOCLAW_API_KEY`` is set and base URL valid, else ``stub`` if allowed.
    - ``stub``: deterministic loop (disallowed in production unless ALLOW_STUB_TRANSPORT).
    - ``http``: gateway chat completions.
    - ``openclaw_cli``: local ``openclaw agent --json``.
    """
    client, _ = get_kiloclaw_client_with_trace(settings)
    return client

