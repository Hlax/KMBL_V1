"""Artifact-first wire compaction, evaluator snippet policy, and staging snapshot rules."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.runtime.staging_snapshot_policy_v1 import (
    should_create_staging_snapshot,
    staging_snapshot_skip_reason,
)
from kmbl_orchestrator.runtime.build_candidate_summary_v1 import (
    merge_slim_with_full_artifacts_for_gates,
)
from kmbl_orchestrator.runtime.evaluator_snippet_policy_v1 import (
    should_omit_evaluator_snippets_from_llm_payload,
    should_prebuild_snippets_for_graph_state,
)
from kmbl_orchestrator.runtime.generator_wire_compact_v1 import (
    compact_generator_output_payload_for_persistence,
    shape_generator_invocation_output_payload,
)
from kmbl_orchestrator.runtime.literal_success_gate import apply_literal_success_checks


def test_shape_invocation_payload_debug_preserves_content_reference() -> None:
    raw = {"artifact_outputs": [{"path": "a.html", "content": "FULL"}]}
    compact, tm = shape_generator_invocation_output_payload(
        raw,
        persist_raw_for_debug=False,
        post_normalization=False,
    )
    assert "content" not in compact["artifact_outputs"][0]
    assert tm["wire_compacted"] is True
    assert tm["first_durable_save_pre_normalize"] is True
    full, tm2 = shape_generator_invocation_output_payload(
        raw,
        persist_raw_for_debug=True,
        post_normalization=False,
    )
    assert full["artifact_outputs"][0].get("content") == "FULL"
    assert tm2["debug_raw_generator_output"] is True
    assert tm2["wire_compacted"] is False


def test_compact_generator_wire_strips_artifact_output_content() -> None:
    raw: dict[str, Any] = {
        "artifact_outputs": [
            {"path": "index.html", "role": "entry", "content": "x" * 9000},
        ],
        "preview_url": "https://p.example",
    }
    compact, tel = compact_generator_output_payload_for_persistence(raw)
    ao = compact.get("artifact_outputs")
    assert isinstance(ao, list) and ao
    row = ao[0]
    assert "content" not in row
    assert row.get("content_omitted") is True
    assert tel["removed_inline_content_char_estimate"] == 9000


def test_omit_snippets_when_v2_preview_absolute() -> None:
    s = Settings.model_construct(
        orchestrator_smoke_contract_evaluator=False,
        kmbl_evaluator_force_snippets=False,
    )
    bc = {
        "kmbl_build_candidate_summary_v2": {
            "entrypoints": ["index.html"],
            "preview_readiness": {"has_resolved_entrypoints": True},
        },
    }
    omit, reason = should_omit_evaluator_snippets_from_llm_payload(
        bc_slim=bc,
        skip_llm=False,
        preview_url="https://live.example/preview",
        preview_resolution={"preview_url_is_absolute": True},
        settings=s,
    )
    assert omit is True
    assert reason == "summary_v2_preview_grounding_sufficient"


def test_include_snippets_without_summary_v2() -> None:
    s = Settings.model_construct(
        orchestrator_smoke_contract_evaluator=False,
        kmbl_evaluator_force_snippets=False,
    )
    omit, reason = should_omit_evaluator_snippets_from_llm_payload(
        bc_slim={},
        skip_llm=False,
        preview_url="https://x",
        preview_resolution={"preview_url_is_absolute": True},
        settings=s,
    )
    assert omit is False
    assert reason == "no_summary_v2_include_snippets"


def test_prebuild_snippets_false_when_http_preview_and_v2_ok() -> None:
    s2 = {
        "entrypoints": ["a.html"],
        "preview_readiness": {"has_resolved_entrypoints": True},
    }
    assert should_prebuild_snippets_for_graph_state(
        summary_v2=s2,
        preview_url_hint="https://p",
    ) is False


def test_merge_slim_with_full_refs_for_literal_gate() -> None:
    full_refs = [
        {"path": "index.html", "content": "needle_ok", "role": "static_frontend_file_v1"},
    ]
    slim = {
        "artifact_outputs": [
            {"path": "index.html", "content_omitted": True, "content_len": 9},
        ],
    }
    merged = merge_slim_with_full_artifacts_for_gates(slim, full_refs)
    r = apply_literal_success_checks(
        EvaluationReportRecord(
            evaluation_report_id=uuid4(),
            thread_id=uuid4(),
            graph_run_id=uuid4(),
            evaluator_invocation_id=uuid4(),
            build_candidate_id=uuid4(),
            status="pass",
        ),
        build_spec={"literal_success_checks": ["needle_ok"]},
        build_candidate=merged,
    )
    assert r.status == "pass"


def test_staging_policy_helpers_partial_always() -> None:
    assert should_create_staging_snapshot(
        "always",
        True,
        evaluation_status="partial",
        allow_partial_under_always=False,
    ) is False
    assert staging_snapshot_skip_reason(
        "always",
        True,
        evaluation_status="partial",
        allow_partial_under_always=False,
    ) == "always_partial_excluded_default"
    assert should_create_staging_snapshot(
        "always",
        False,
        evaluation_status="pass",
        allow_partial_under_always=False,
    ) is True
