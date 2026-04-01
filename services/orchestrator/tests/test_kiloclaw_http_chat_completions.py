"""Tests for KiloClaw HTTP transport via OpenAI-compatible chat completions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.providers.kiloclaw import (
    KiloClawHttpClient,
    KiloClawInvocationError,
    _parse_chat_completion_json_content,
)


def _settings() -> Settings:
    return Settings.model_construct(
        kiloclaw_base_url="https://gw.example.test",
        kiloclaw_invoke_path="/v1/chat/completions",
        kiloclaw_api_key="test-token",
        kiloclaw_chat_completions_user="kmbl-orchestrator:e2e-test",
    )


def _chat_response(
    content: str | dict | list,
    *,
    tool_calls: list[dict] | None = None,
) -> dict:
    if isinstance(content, list):
        msg_content: str | list | None = content
    else:
        text = content if isinstance(content, str) else json.dumps(content)
        msg_content = text
    msg: dict = {"role": "assistant", "content": msg_content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
        msg["content"] = None
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "stop",
            }
        ],
    }


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_posts_chat_completions_and_parses_planner(mock_client_cls: MagicMock) -> None:
    planner_out = {
        "build_spec": {"type": "http_test", "title": "t", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(planner_out)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {"task": "x"})

    assert out["build_spec"] == planner_out["build_spec"]
    call_kw = mock_inst.post.call_args
    assert call_kw[0][0] == "https://gw.example.test/v1/chat/completions"
    hdrs = call_kw[1]["headers"]
    assert hdrs["Authorization"] == "Bearer test-token"
    assert hdrs["x-kiloclaw-proxy-token"] == "test-token"
    body = call_kw[1]["json"]
    assert body["model"] == "openclaw:kmbl-planner"
    assert body["user"] == "kmbl-orchestrator:e2e-test"
    assert body["messages"][0]["role"] == "system"
    user_obj = json.loads(body["messages"][1]["content"])
    assert user_obj["role_type"] == "planner"
    assert user_obj["config_key"] == "kmbl-planner"
    assert user_obj["payload"] == {"task": "x"}


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_appends_thread_id_to_chat_user(mock_client_cls: MagicMock) -> None:
    """Isolate OpenClaw session per thread — bare kmbl-orchestrator can 500 on the gateway."""
    planner_out = {
        "build_spec": {"type": "http_test", "title": "t", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(planner_out)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    tid = "11111111-2222-3333-4444-555555555555"
    c.invoke_role("planner", "kmbl-planner", {"thread_id": tid, "task": "x"})

    body = mock_inst.post.call_args[1]["json"]
    assert body["user"] == f"kmbl-orchestrator:e2e-test:{tid}"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_planner_recovers_variation_only_echo(mock_client_cls: MagicMock) -> None:
    """Live varied gallery sometimes returns only ``variation`` keys — narrow synthetic contract."""
    variation_only = {
        "run_nonce": "n1",
        "variation_seed": 42,
        "theme_variant": "pastel",
        "subject_variant": "architecture",
        "layout_variant": "strip_4",
        "tone_variant": "bold_caption",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(variation_only))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["type"] == "kmbl_seeded_gallery_strip_varied_v1"
    assert out["constraints"].get("recovered_from") == "variation_only_planner_echo"
    assert out["constraints"]["variation"]["run_nonce"] == "n1"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_planner_reads_json_from_tool_calls_arguments(mock_client_cls: MagicMock) -> None:
    planner_out = {
        "build_spec": {"type": "http_test", "title": "from_tool_call", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "emit_plan", "arguments": json.dumps(planner_out)},
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response("", tool_calls=tool_calls)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "from_tool_call"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_planner_concatenated_json_objects(mock_client_cls: MagicMock) -> None:
    """Some models emit a short meta object then the plan — ``json.loads`` fails; first ``raw_decode`` would miss ``build_spec``."""
    planner_out = {
        "build_spec": {"type": "http_test", "title": "second_object", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    two = '{"meta":{"stub":true}}\n' + json.dumps(planner_out)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(two)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "second_object"


def test_parse_chat_completion_accepts_message_content_array() -> None:
    """Some gateways return ``message.content`` as a list of text parts."""
    planner_out = {
        "build_spec": {"type": "http_test", "title": "array_content", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    data = _chat_response(
        [{"type": "text", "text": json.dumps(planner_out)}]
    )
    parsed = _parse_chat_completion_json_content(data)
    assert parsed["build_spec"]["title"] == "array_content"


def test_parse_chat_completion_accepts_prose_before_json_object() -> None:
    """Varied gallery runs send longer planner prompts; models may prepend prose before JSON."""
    planner_out = {
        "build_spec": {"type": "http_test", "title": "t", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    prose = "Here is the plan per your request:\n\n"
    wrapped = prose + json.dumps(planner_out)
    data = _chat_response(wrapped)
    parsed = _parse_chat_completion_json_content(data)
    assert parsed["build_spec"]["title"] == "t"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_strips_markdown_fence(mock_client_cls: MagicMock) -> None:
    planner_out = {
        "build_spec": {"type": "http_test", "title": "t", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    fenced = "```json\n" + json.dumps(planner_out) + "\n```"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(fenced)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "t"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_parses_prose_before_json_planner_output(mock_client_cls: MagicMock) -> None:
    planner_out = {
        "build_spec": {"type": "http_test", "title": "from_prose", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    content = "Summary:\n\n" + json.dumps(planner_out)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(content)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "from_prose"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_unwraps_planner_output_nested_under_plan(mock_client_cls: MagicMock) -> None:
    """Models often nest the contract under ``plan``; varied prompts increase this pattern."""
    planner_inner = {
        "build_spec": {"type": "http_test", "title": "under_plan", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    wrapped = {"plan": planner_inner}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(wrapped))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "under_plan"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_unwraps_planner_double_nested(mock_client_cls: MagicMock) -> None:
    """Varied prompts may yield ``wrapper.plan`` or similar — more than one level deep."""
    planner_inner = {
        "build_spec": {"type": "http_test", "title": "double_nested", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    wrapped = {"response": {"plan": planner_inner}}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(wrapped))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "double_nested"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_unwraps_planner_nested_under_arbitrary_key(mock_client_cls: MagicMock) -> None:
    """Planner-only: contract may sit under ``response``, ``answer``, etc. (not only ``plan``)."""
    planner_inner = {
        "build_spec": {"type": "http_test", "title": "under_response", "steps": []},
        "constraints": {},
        "success_criteria": [],
        "evaluation_targets": [],
    }
    wrapped = {"response": planner_inner}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(wrapped))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("planner", "kmbl-planner", {})
    assert out["build_spec"]["title"] == "under_response"


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_validates_planner_missing_build_spec(mock_client_cls: MagicMock) -> None:
    # Object-shaped JSON that `_extract_http_role_dict` accepts as role output but fails planner rules.
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response({"proposed_changes": {}})
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    with pytest.raises(KiloClawInvocationError, match="build_spec"):
        c.invoke_role("planner", "kmbl-planner", {})
