"""Runtime guards for session_3-style planner/generator/evaluator failures."""

from __future__ import annotations

import pytest

from kmbl_orchestrator.identity.sanitize import sanitize_display_name, sanitize_identity_brief_payload
from kmbl_orchestrator.runtime.evaluator_preflight import (
    should_skip_evaluator_llm,
    synthetic_skipped_evaluator_raw,
)
from kmbl_orchestrator.runtime.static_vertical_invariants import (
    clamp_experience_mode_for_static_vertical,
    is_static_frontend_vertical,
)
from kmbl_orchestrator.staging.integrity import validate_static_frontend_bundle_requirement


def test_static_vertical_rejects_checklist_only_output() -> None:
    build_spec = {"type": "static_frontend_file_v1", "title": "x"}
    event_input = {"constraints": {"canonical_vertical": "static_frontend_file_v1"}}
    out = {
        "proposed_changes": {"checklist_steps": [{"title": "a"}]},
        "artifact_outputs": None,
        "updated_state": {},
    }
    with pytest.raises(ValueError, match="artifact_outputs"):
        validate_static_frontend_bundle_requirement(build_spec, event_input, out)


def test_static_bundle_accepts_contract_failure_instead_of_html() -> None:
    build_spec = {"type": "static_frontend_file_v1"}
    event_input = {"constraints": {"canonical_vertical": "static_frontend_file_v1"}}
    out = {
        "contract_failure": {"code": "no_budget", "message": "cannot build"},
        "artifact_outputs": None,
    }
    validate_static_frontend_bundle_requirement(build_spec, event_input, out)


def test_evaluator_skip_when_no_html_bundle() -> None:
    bc = {"artifact_outputs": None, "preview_url": None}
    bs = {"type": "static_frontend_file_v1"}
    ei = {"constraints": {"kmbl_static_frontend_vertical": True}}
    skip, reason = should_skip_evaluator_llm(bc, bs, ei)
    assert skip is True
    assert "no_artifact" in reason


def test_evaluator_skip_false_when_html_present() -> None:
    bc = {
        "artifact_outputs": [
            {
                "role": "static_frontend_file_v1",
                "file_path": "component/preview/index.html",
                "content": "<!DOCTYPE html><html><body>x</body></html>",
            }
        ]
    }
    bs = {"type": "static_frontend_file_v1"}
    ei = {}
    assert should_skip_evaluator_llm(bc, bs, ei) == (False, "")


def test_synthetic_skip_raw_shape() -> None:
    r = synthetic_skipped_evaluator_raw("unit_test")
    assert r["status"] == "partial"
    assert r["metrics"]["evaluator_skipped"] is True


def test_clamp_webgl_on_static_vertical() -> None:
    """WebGL/immersive modes are no longer clamped for static vertical.

    Static HTML/JS/CSS bundles can contain Three.js/WebGL scenes.
    The evaluator's 3D content guardrail provides the quality gate instead.
    """
    bs = {"type": "static_frontend_file_v1", "experience_mode": "webgl_3d_portfolio"}
    ei = {"constraints": {"canonical_vertical": "static_frontend_file_v1"}}
    fixes = clamp_experience_mode_for_static_vertical(bs, ei)
    # No clamping — WebGL is allowed in static bundles
    assert fixes == []
    assert bs["experience_mode"] == "webgl_3d_portfolio"


def test_is_static_frontend_vertical() -> None:
    assert is_static_frontend_vertical(
        {"type": "static_frontend_file_v1"},
        {},
    )


def test_sanitize_display_name_strips_headings_line() -> None:
    assert sanitize_display_name("harvey lacsina\n\nHeadings: CJR | SAP") == "harvey lacsina"


def test_sanitize_identity_brief_payload() -> None:
    d = sanitize_identity_brief_payload(
        {
            "identity_id": "x",
            "source_url": "https://x.com",
            "display_name": "Name\n\nHeadings: A | B",
            "must_mention": ["Name\n\nHeadings: A | B", "Work"],
            "palette_hex": ["#038", "#8211"],
        }
    )
    assert "Headings" not in (d.get("display_name") or "")
    assert d.get("display_name") == "Name"
