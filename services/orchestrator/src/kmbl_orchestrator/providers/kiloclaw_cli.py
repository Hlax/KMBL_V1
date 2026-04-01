"""KiloClaw CLI transport — runs ``openclaw agent --json``."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from kmbl_orchestrator.config import Settings, get_settings
from kmbl_orchestrator.providers.kiloclaw_protocol import (
    KiloClawInvocationError,
    RoleType,
    provider_failure,
)
from kmbl_orchestrator.providers.kiloclaw_parsing import (
    _apply_role_contract,
    extract_role_payload_from_openclaw_output,
)


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
