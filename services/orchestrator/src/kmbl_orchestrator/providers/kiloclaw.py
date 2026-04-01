"""KiloClaw / OpenClaw role execution — backward-compatible re-export shim.

The implementation is now split across:
- kiloclaw_protocol.py  — protocol, errors, factory
- kiloclaw_parsing.py   — response parsing & contract validation helpers
- kiloclaw_http.py      — HTTP transport (KiloClawHttpClient)
- kiloclaw_cli.py       — CLI transport (OpenClawCliClient)
- kiloclaw_stub.py      — stub transport (KiloClawStubClient)
"""

# Re-export everything that external code imports from this module
from kmbl_orchestrator.providers.kiloclaw_protocol import (  # noqa: F401
    KiloClawClient,
    KiloClawInvocationError,
    RoleType,
    get_kiloclaw_client,
    provider_failure,
)
from kmbl_orchestrator.providers.kiloclaw_parsing import (  # noqa: F401
    _apply_role_contract,
    _as_json_object_maybe,
    _assistant_message_body_for_json,
    _coerce_planner_wire_keys,
    _decode_first_json_object_in_text,
    _dict_with_planner_build_spec,
    _extract_http_role_dict,
    _find_planner_contract_dict,
    _iter_json_objects_in_text,
    _looks_like_role_output,
    _looks_like_variation_only_echo,
    _message_content_to_str,
    _parse_chat_completion_json_content,
    _strip_markdown_json_fence,
    _synthetic_planner_from_variation_echo,
    _system_prompt_for_role,
    extract_role_payload_from_openclaw_output,
)
from kmbl_orchestrator.providers.kiloclaw_http import KiloClawHttpClient  # noqa: F401
from kmbl_orchestrator.providers.kiloclaw_cli import OpenClawCliClient  # noqa: F401
from kmbl_orchestrator.providers.kiloclaw_stub import KiloClawStubClient  # noqa: F401

# Backward compatibility: tests patch ``kiloclaw.httpx.Client``
import httpx  # noqa: F401

__all__ = [
    "KiloClawClient",
    "KiloClawHttpClient",
    "KiloClawInvocationError",
    "KiloClawStubClient",
    "OpenClawCliClient",
    "RoleType",
    "extract_role_payload_from_openclaw_output",
    "get_kiloclaw_client",
    "provider_failure",
    "_parse_chat_completion_json_content",
]
