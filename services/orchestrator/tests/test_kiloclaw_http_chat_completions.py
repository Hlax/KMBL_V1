"""Tests for KiloClaw HTTP transport via OpenAI-compatible chat completions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.providers.kiloclaw import KiloClawHttpClient, KiloClawInvocationError
from kmbl_orchestrator.providers.kiloclaw_parsing import _parse_chat_completion_json_content


def _settings() -> Settings:
    return Settings.model_construct(
        openclaw_base_url="https://gw.example.test",
        openclaw_invoke_path="/v1/chat/completions",
        openclaw_api_key="test-token",
        openclaw_chat_completions_user="kmbl-orchestrator:e2e-test",
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
def test_http_client_appends_thread_and_graph_run_id_to_chat_user(mock_client_cls: MagicMock) -> None:
    """Isolate OpenClaw session per thread and graph run (avoids cross-run compaction bleed)."""
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
    gid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    c.invoke_role(
        "planner",
        "kmbl-planner",
        {"thread_id": tid, "graph_run_id": gid, "task": "x"},
    )

    body = mock_inst.post.call_args[1]["json"]
    assert body["user"] == f"kmbl-orchestrator:e2e-test:{tid}:{gid}"


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


def test_parse_chat_completion_detects_openclaw_placeholder_generator() -> None:
    data = _chat_response("No response from OpenClaw.")
    with pytest.raises(KiloClawInvocationError) as ei:
        _parse_chat_completion_json_content(data, role_type="generator")
    assert "placeholder" in str(ei.value).lower()
    det = (ei.value.normalized or {}).get("details") or {}
    assert det.get("kind") == "openclaw_placeholder"


def test_parse_chat_completion_detects_no_reply_token() -> None:
    data = _chat_response("NO_REPLY")
    with pytest.raises(KiloClawInvocationError) as ei:
        _parse_chat_completion_json_content(data, role_type="generator")
    assert "placeholder" in str(ei.value).lower()


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_sets_max_tokens_for_generator(mock_client_cls: MagicMock) -> None:
    gen_out = {"updated_state": {"smoke": True}}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(gen_out))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    s = Settings.model_construct(
        openclaw_base_url="https://gw.example.test",
        openclaw_invoke_path="/v1/chat/completions",
        openclaw_api_key="test-token",
        openclaw_chat_completions_user="kmbl-orchestrator",
        openclaw_chat_max_tokens_generator=2048,
    )
    c = KiloClawHttpClient(settings=s)
    c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})
    body = mock_inst.post.call_args[1]["json"]
    assert body["max_tokens"] == 2048


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_sets_max_tokens_for_evaluator(mock_client_cls: MagicMock) -> None:
    ev_out = {"status": "pass", "summary": "ok"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(ev_out))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    s = Settings.model_construct(
        openclaw_base_url="https://gw.example.test",
        openclaw_invoke_path="/v1/chat/completions",
        openclaw_api_key="test-token",
        openclaw_chat_completions_user="kmbl-orchestrator",
        openclaw_chat_max_tokens_evaluator=1024,
    )
    c = KiloClawHttpClient(settings=s)
    c.invoke_role("evaluator", "kmbl-evaluator", {"thread_id": "00000000-0000-0000-0000-000000000001"})
    body = mock_inst.post.call_args[1]["json"]
    assert body["max_tokens"] == 1024


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_default_max_tokens_generator_8192(mock_client_cls: MagicMock) -> None:
    """Schema default sends max_tokens for generator (parity with planner)."""
    gen_out = {"updated_state": {"smoke": True}}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(gen_out))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    s = Settings.model_construct(
        openclaw_base_url="https://gw.example.test",
        openclaw_invoke_path="/v1/chat/completions",
        openclaw_api_key="test-token",
        openclaw_chat_completions_user="kmbl-orchestrator",
    )
    c = KiloClawHttpClient(settings=s)
    c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})
    body = mock_inst.post.call_args[1]["json"]
    assert body["max_tokens"] == 8192


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_http_client_default_max_tokens_evaluator_8192(mock_client_cls: MagicMock) -> None:
    ev_out = {"status": "pass", "summary": "ok"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(ev_out))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    s = Settings.model_construct(
        openclaw_base_url="https://gw.example.test",
        openclaw_invoke_path="/v1/chat/completions",
        openclaw_api_key="test-token",
        openclaw_chat_completions_user="kmbl-orchestrator",
    )
    c = KiloClawHttpClient(settings=s)
    c.invoke_role("evaluator", "kmbl-evaluator", {"thread_id": "00000000-0000-0000-0000-000000000001"})
    body = mock_inst.post.call_args[1]["json"]
    assert body["max_tokens"] == 8192


# ---------------------------------------------------------------------------
# Generator payload recognition — regression suite for the ingest failure
# (thread 8fbf8b5c: "OpenClaw response did not contain a recognizable role payload")
# ---------------------------------------------------------------------------

_GENERATOR_ARTIFACT_PAYLOAD = {
    "selected_urls": [
        "https://harveylacsina.com/",
        "https://harveylacsina.com/about",
    ],
    "artifact_outputs": [
        {
            "role": "interactive_frontend_app_v1",
            "file_path": "component/preview/index.html",
            "language": "html",
            "content": "<!DOCTYPE html><html><body><h1>Harvey Lacsina</h1></body></html>",
        },
        {
            "role": "interactive_frontend_app_v1",
            "file_path": "component/preview/styles.css",
            "language": "css",
            "content": "body { margin: 0; }",
        },
        {
            "role": "interactive_frontend_app_v1",
            "file_path": "component/preview/app.js",
            "language": "javascript",
            "content": "console.log('portfolio');",
        },
    ],
    "updated_state": {
        "selected_urls": ["https://harveylacsina.com/"],
        "chosen_vertical": "interactive_frontend_app_v1",
        "notes": "Portfolio with hero, projects grid, about, contact.",
    },
}


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_artifact_payload_as_json_string(mock_client_cls: MagicMock) -> None:
    """Standard case: message.content is a JSON string with artifact_outputs + updated_state."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(_GENERATOR_ARTIFACT_PAYLOAD))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]
    assert out["selected_urls"] == _GENERATOR_ARTIFACT_PAYLOAD["selected_urls"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_artifact_payload_content_as_dict(mock_client_cls: MagicMock) -> None:
    """Non-standard: message.content is a parsed JSON object (dict), not a string.

    Regression for the gateway returning content as an already-parsed dict.
    """
    # Build chat response manually with content as a raw dict (not serialized).
    chat_resp = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": dict(_GENERATOR_ARTIFACT_PAYLOAD),  # dict, not string
                },
                "finish_reason": "stop",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = chat_resp
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_artifact_payload_wrapped_in_response_key(mock_client_cls: MagicMock) -> None:
    """Gateway wraps the generator output under an unexpected key (e.g. ``response``).

    Regression for: _extract_http_role_dict only checked fixed wrapper keys,
    missing arbitrary keys like ``response`` / ``answer`` / ``generated``.
    """
    wrapped = {"response": dict(_GENERATOR_ARTIFACT_PAYLOAD)}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(wrapped))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_artifact_payload_wrapped_in_generated_key(mock_client_cls: MagicMock) -> None:
    """Another arbitrary wrapper key (``generated``)."""
    wrapped = {"generated": dict(_GENERATOR_ARTIFACT_PAYLOAD)}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(json.dumps(wrapped))
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_artifact_payload_prose_before_json(mock_client_cls: MagicMock) -> None:
    """Model prepends prose before the JSON — recovery must find the role-shaped object."""
    content = "Here is the portfolio implementation:\n\n" + json.dumps(_GENERATOR_ARTIFACT_PAYLOAD)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(content)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_metadata_object_before_payload(mock_client_cls: MagicMock) -> None:
    """Model emits a short metadata JSON object followed by the actual payload.

    Regression: _decode_first_json_object_in_text would pick up the WRONG object.
    The multi-object scanner must find the role-shaped one.
    """
    meta = json.dumps({"meta": {"model": "gpt-4o", "tokens": 3250}})
    payload = json.dumps(_GENERATOR_ARTIFACT_PAYLOAD)
    content = meta + "\n\n" + payload
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(content)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_markdown_fenced_artifact_payload(mock_client_cls: MagicMock) -> None:
    """Generator output inside markdown fence."""
    content = "```json\n" + json.dumps(_GENERATOR_ARTIFACT_PAYLOAD) + "\n```"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _chat_response(content)
    mock_inst = MagicMock()
    mock_inst.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_inst
    mock_client_cls.return_value.__exit__.return_value = None

    c = KiloClawHttpClient(settings=_settings())
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]


@patch("kmbl_orchestrator.providers.kiloclaw_http.httpx.Client")
def test_generator_tool_calls_with_artifact_payload(mock_client_cls: MagicMock) -> None:
    """Generator output delivered via tool_calls.function.arguments (content is null)."""
    tool_calls = [
        {
            "id": "call_gen_1",
            "type": "function",
            "function": {
                "name": "emit_artifacts",
                "arguments": json.dumps(_GENERATOR_ARTIFACT_PAYLOAD),
            },
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
    out = c.invoke_role("generator", "kmbl-generator", {"thread_id": "00000000-0000-0000-0000-000000000001"})

    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


def test_parse_generator_payload_from_openclaw_envelope() -> None:
    """OpenClaw CLI/agent envelope wrapping the generator output in result.payloads."""
    from kmbl_orchestrator.providers.kiloclaw_parsing import extract_role_payload_from_openclaw_output

    envelope = {
        "result": {
            "payloads": [{"text": json.dumps(_GENERATOR_ARTIFACT_PAYLOAD)}],
        }
    }
    out = extract_role_payload_from_openclaw_output(envelope)
    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]
    assert out["updated_state"] == _GENERATOR_ARTIFACT_PAYLOAD["updated_state"]


def test_parse_generator_payload_nested_under_arbitrary_result_key() -> None:
    """extract_role_payload_from_openclaw_output deep scan for nested role output."""
    from kmbl_orchestrator.providers.kiloclaw_parsing import extract_role_payload_from_openclaw_output

    nested = {
        "status": "ok",
        "result": {
            "generator_output": dict(_GENERATOR_ARTIFACT_PAYLOAD),
        },
    }
    out = extract_role_payload_from_openclaw_output(nested)
    assert out["artifact_outputs"] == _GENERATOR_ARTIFACT_PAYLOAD["artifact_outputs"]


def test_parse_evaluator_payload_wrapped_in_response_key() -> None:
    """Evaluator output under an unexpected wrapper key."""
    evaluator_out = {"status": "pass", "summary": "All checks pass", "issues": []}
    wrapped = {"response": evaluator_out}
    data = _chat_response(json.dumps(wrapped))
    parsed = _parse_chat_completion_json_content(data, role_type="evaluator")
    from kmbl_orchestrator.providers.kiloclaw_parsing import _extract_http_role_dict

    out = _extract_http_role_dict(parsed, role_type="evaluator")
    assert out["status"] == "pass"
