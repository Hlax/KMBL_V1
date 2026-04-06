"""Compact payload telemetry (no raw prompts)."""

from __future__ import annotations

import json
from uuid import uuid4

from kmbl_orchestrator.domain import GraphRunRecord, RoleInvocationRecord, ThreadRecord
from kmbl_orchestrator.runtime.graph_run_detail_read_model import build_graph_run_detail_read_model
from kmbl_orchestrator.runtime.payload_telemetry_v1 import TELEMETRY_VERSION, build_payload_telemetry_v1


def test_planner_telemetry_bounded_keys() -> None:
    p = {"thread_id": "t", "graph_run_id": "g", "event_input": {"a": "b"}}
    t = build_payload_telemetry_v1("planner", p)
    assert t["telemetry_version"] == TELEMETRY_VERSION
    assert t["role"] == "planner"
    assert t["payload_char_count"] > 20
    assert t["payload_byte_count"] >= t["payload_char_count"]
    assert "full_prompt" not in json.dumps(t, default=str).lower()


def test_evaluator_telemetry_estimated_saved_slim_vs_full() -> None:
    full_refs = [
        {"path": "a.html", "content": "x" * 5000},
        {"path": "b.js", "content": "y" * 3000},
    ]
    slim_bc = {
        "artifact_outputs": [
            {"path": "a.html", "content_omitted": True, "content_len": 5000},
            {"path": "b.js", "content_omitted": True, "content_len": 3000},
        ],
        "kmbl_build_candidate_summary_v1": {"summary_version": 1},
        "kmbl_evaluator_artifact_snippets_v1": {
            "entry_html": {"path": "a.html", "text": "<!doctype html>"},
            "scripts": [],
            "shaders": [],
        },
    }
    payload = {
        "thread_id": "t",
        "graph_run_id": "g",
        "build_candidate": slim_bc,
        "success_criteria": [],
        "evaluation_targets": [],
        "iteration_hint": 0,
        "kmbl_implementation_reference_cards": [{"id": "r1"}],
    }
    t = build_payload_telemetry_v1(
        "evaluator",
        payload,
        full_artifact_refs_for_compare=full_refs,
    )
    assert t["has_build_candidate_summary"] is True
    assert t["summary_replaced_full_artifacts"] is True
    assert t["full_artifact_content_char_count"] == 8000
    assert t["artifact_outputs_inline_content_char_count"] == 0
    assert t["estimated_content_chars_saved_vs_full_inline"] == 8000
    assert t["reference_card_count"] == 1
    assert t["snippet_non_empty_count"] >= 1


def test_generator_telemetry_reference_cards() -> None:
    p = {
        "thread_id": "t",
        "build_spec": {"type": "interactive_frontend_app_v1"},
        "kmbl_implementation_reference_cards": [{"id": "a"}, {"id": "b"}],
        "kmbl_inspiration_reference_cards": [{"id": "c"}],
    }
    t = build_payload_telemetry_v1("generator", p)
    assert t["reference_card_count"] == 3
    assert t["artifact_output_count"] == 0


def test_read_model_merges_payload_telemetry() -> None:
    tid = uuid4()
    gid = uuid4()
    rid = uuid4()
    inv = RoleInvocationRecord(
        role_invocation_id=rid,
        graph_run_id=gid,
        thread_id=tid,
        role_type="evaluator",
        provider_config_key="k",
        input_payload_json={"thread_id": str(tid)},
        status="completed",
        iteration_index=0,
        started_at="2026-04-01T12:00:00+00:00",
        ended_at="2026-04-01T12:01:00+00:00",
        routing_metadata_json={
            "kmbl_payload_telemetry_v1": {
                "telemetry_version": 1,
                "role": "evaluator",
                "payload_char_count": 1234,
                "payload_byte_count": 1250,
                "payload_governor_v1": {
                    "was_trimmed": True,
                    "chars_saved_by_governor_trim": 99,
                },
            }
        },
    )
    raw = build_graph_run_detail_read_model(
        thread=ThreadRecord(thread_id=tid, thread_kind="build", status="active"),
        gr=GraphRunRecord(
            graph_run_id=gid,
            thread_id=tid,
            trigger_type="prompt",
            status="completed",
            started_at="2026-04-01T12:00:00+00:00",
            ended_at="2026-04-01T12:05:00+00:00",
        ),
        invocations=[inv],
        staging_rows=[],
        publications=[],
        events=[],
        latest_checkpoint=None,
        has_interrupt_signal=False,
        bs=None,
        bc=None,
        ev=None,
    )
    obs = raw["summary"]["run_observability"]
    assert isinstance(obs, dict)
    rows = obs.get("role_payload_telemetry_v1")
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["payload_char_count"] == 1234
    riv = raw["role_invocations"][0]
    assert riv["payload_telemetry"]["payload_char_count"] == 1234
    assert riv["payload_telemetry"]["payload_governor_v1"]["was_trimmed"] is True
