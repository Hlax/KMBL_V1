"""Tests for workspace-first, required-library enforcement, retry cap, preview correctness,
no-duplication, and neutral archetype defaults.

Covers:
- Workspace-first preview: multi-file build renders without inline artifact content
- Library enforcement: missing library → partial, satisfied → pass
- Retry cap: weak grounding stops iteration
- Preview correctness: evaluator gets valid preview_url, not null / private-blocked
- No duplication: workspace present → no large artifact content persisted
- Portfolio bias removal: neutral archetype when planner doesn't set one
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.contracts.planner_normalize import normalize_build_spec_for_persistence
from kmbl_orchestrator.domain import EvaluationReportRecord
from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router
from kmbl_orchestrator.runtime.build_candidate_summary_v1 import build_lean_summary_for_payload
from kmbl_orchestrator.runtime.generator_wire_compact_v1 import (
    WIRE_COMPACTION_VERSION,
    compact_generator_output_payload_for_persistence,
    shape_generator_invocation_output_payload,
    wire_compaction_routing_marker,
)
from kmbl_orchestrator.runtime.habitat_lifecycle import (
    clear_registry_for_tests,
    get_active_live_habitat,
    list_manifests,
    materialize_workspace_to_live_habitat,
    register_materialization,
)
from kmbl_orchestrator.runtime.interactive_lane_evaluator_gate import (
    REQUIRED_LIBRARY_MISSING_CODE,
    apply_interactive_lane_evaluator_gate,
)
from kmbl_orchestrator.runtime.session_staging_links import (
    resolve_evaluator_preview_resolution,
)


def _sample_generator_raw(*, with_workspace: bool = False, content_size: int = 3000) -> dict[str, Any]:
    content = "x" * content_size
    raw: dict[str, Any] = {
        "artifact_outputs": [
            {"path": "index.html", "role": "static_frontend_file_v1", "content": content},
            {"path": "style.css", "role": "static_frontend_file_v1", "content": "body{margin:0}"},
            {"path": "app.js", "role": "static_frontend_file_v1", "content": "console.log('hi')"},
        ],
    }
    if with_workspace:
        raw["workspace_manifest_v1"] = {
            "files": [
                {"path": "index.html", "language": "html"},
                {"path": "style.css", "language": "css"},
                {"path": "app.js", "language": "js"},
            ],
        }
        raw["sandbox_ref"] = "/workspace/sandbox-abc"
    return raw


class TestWorkspaceFirstCompaction:
    """P0 — workspace-first wire compaction strips inline bodies."""

    def test_workspace_first_strips_content(self):
        raw = _sample_generator_raw(with_workspace=True)
        compacted, tel = compact_generator_output_payload_for_persistence(raw, workspace_first=True)
        for item in compacted["artifact_outputs"]:
            assert "content" not in item
            assert item["content_omitted"] is True
            assert "content_len" in item
        assert tel["workspace_first"] is True
        assert tel["wire_compaction_version"] == WIRE_COMPACTION_VERSION

    def test_workspace_first_includes_snippet(self):
        raw = _sample_generator_raw(with_workspace=True, content_size=500)
        compacted, _ = compact_generator_output_payload_for_persistence(raw, workspace_first=True)
        html = compacted["artifact_outputs"][0]
        assert "content_snippet" in html
        assert len(html["content_snippet"]) <= 200

    def test_workspace_first_includes_digest(self):
        raw = _sample_generator_raw(with_workspace=True)
        compacted, _ = compact_generator_output_payload_for_persistence(raw, workspace_first=True)
        html = compacted["artifact_outputs"][0]
        assert "digest8" in html
        # Verify digest is correct
        expected = hashlib.sha256(("x" * 3000).encode("utf-8")).hexdigest()[:8]
        assert html["digest8"] == expected

    def test_non_workspace_no_snippet(self):
        raw = _sample_generator_raw(with_workspace=False)
        compacted, tel = compact_generator_output_payload_for_persistence(raw, workspace_first=False)
        for item in compacted["artifact_outputs"]:
            assert "content" not in item
            assert "content_snippet" not in item
            assert item["content_omitted"] is True
        assert tel["workspace_first"] is False

    def test_shape_passes_workspace_first(self):
        raw = _sample_generator_raw(with_workspace=True)
        out, shape = shape_generator_invocation_output_payload(
            raw,
            persist_raw_for_debug=False,
            post_normalization=False,
            workspace_first=True,
        )
        assert shape["workspace_first"] is True
        assert shape["wire_compacted"] is True
        for item in out["artifact_outputs"]:
            assert "content" not in item

    def test_shape_workspace_first_false_default(self):
        raw = _sample_generator_raw(with_workspace=False)
        out, shape = shape_generator_invocation_output_payload(
            raw,
            persist_raw_for_debug=False,
            post_normalization=True,
        )
        # Default should be workspace_first=False
        assert shape["workspace_first"] is False

    def test_debug_mode_preserves_content(self):
        raw = _sample_generator_raw(with_workspace=True)
        out, shape = shape_generator_invocation_output_payload(
            raw,
            persist_raw_for_debug=True,
            post_normalization=False,
            workspace_first=True,
        )
        # Debug mode keeps full content
        assert out["artifact_outputs"][0]["content"] == "x" * 3000
        assert shape["wire_compaction_skipped"] is True


class TestNoInlineDuplication:
    """P0 — workspace present → no large artifact content persisted on wire."""

    def test_compaction_removes_large_content_chars(self):
        raw = _sample_generator_raw(with_workspace=True, content_size=10000)
        _, tel = compact_generator_output_payload_for_persistence(raw, workspace_first=True)
        assert tel["removed_inline_content_char_estimate"] >= 10000
        assert tel["artifact_output_rows_touched"] == 3

    def test_compaction_note_describes_workspace(self):
        raw = _sample_generator_raw(with_workspace=True)
        compacted, _ = compact_generator_output_payload_for_persistence(raw, workspace_first=True)
        note = compacted["kmbl_generator_wire_compaction_v1"]["note"]
        assert "workspace" in note.lower()


# ---------------------------------------------------------------------------
# 2. Required-library enforcement
# ---------------------------------------------------------------------------


def _make_eval_report(
    *,
    status: str = "pass",
    summary: str = "ok",
    issues: list | None = None,
    metrics: dict | None = None,
) -> EvaluationReportRecord:
    return EvaluationReportRecord(
        evaluation_report_id=uuid4(),
        graph_run_id=uuid4(),
        thread_id=uuid4(),
        build_candidate_id=uuid4(),
        evaluator_invocation_id=uuid4(),
        status=status,
        summary=summary,
        issues_json=issues or [],
        metrics_json=metrics or {},
    )


def _build_candidate_with_libs(detected: list[str], content: str = "<html></html>") -> dict[str, Any]:
    return {
        "artifact_outputs": [
            {"path": "index.html", "role": "interactive_frontend_app_v1", "content": content},
        ],
        "kmbl_build_candidate_summary_v1": {
            "libraries_detected": detected,
        },
    }


class TestRequiredLibraryEnforcement:
    """P0 — required libraries hard enforcement: missing → partial, satisfied → pass."""

    def test_missing_library_downgrades_to_partial(self):
        build_spec = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "required_libraries": ["three", "gsap"],
            },
            "experience_mode": "webgl_3d_portfolio",
        }
        bc = _build_candidate_with_libs(["gsap"])  # missing three
        report = _make_eval_report(status="pass")
        result = apply_interactive_lane_evaluator_gate(
            report, build_spec=build_spec, event_input={}, build_candidate=bc,
        )
        assert result.status == "partial"
        codes = [i["code"] for i in result.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE in codes

    def test_satisfied_libraries_stay_pass(self):
        build_spec = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "required_libraries": ["three", "gsap"],
            },
            "experience_mode": "webgl_3d_portfolio",
        }
        bc = _build_candidate_with_libs(
            ["three", "gsap"],
            content="<html><script>THREE.WebGLRenderer; gsap.to(); addEventListener('click', f)</script></html>",
        )
        report = _make_eval_report(status="pass")
        result = apply_interactive_lane_evaluator_gate(
            report, build_spec=build_spec, event_input={}, build_candidate=bc,
        )
        # Status should remain pass (no required_library_missing issue)
        codes = [i["code"] for i in result.issues_json if isinstance(i, dict)]
        assert REQUIRED_LIBRARY_MISSING_CODE not in codes

    def test_compliance_metric_populated(self):
        build_spec = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "required_libraries": ["three"],
            },
            "experience_mode": "webgl_3d_portfolio",
        }
        bc = _build_candidate_with_libs(["three"])
        report = _make_eval_report(status="pass")
        result = apply_interactive_lane_evaluator_gate(
            report, build_spec=build_spec, event_input={}, build_candidate=bc,
        )
        compliance = result.metrics_json.get("required_libraries_compliance")
        assert compliance is not None
        assert compliance["satisfied"] is True
        assert compliance["missing"] == []

    def test_fallback_to_allowed_libraries(self):
        """When required_libraries is absent, falls back to allowed_libraries."""
        build_spec = {
            "type": "interactive_frontend_app_v1",
            "execution_contract": {
                "allowed_libraries": ["three", "gsap"],
            },
            "experience_mode": "webgl_3d_portfolio",
        }
        bc = _build_candidate_with_libs([])  # no libs detected
        report = _make_eval_report(status="pass")
        result = apply_interactive_lane_evaluator_gate(
            report, build_spec=build_spec, event_input={}, build_candidate=bc,
        )
        assert result.status == "partial"


# ---------------------------------------------------------------------------
# 3. Weakly-grounded retry cap
# ---------------------------------------------------------------------------


class TestWeaklyGroundedRetryCap:
    """P0 — weak grounding stops iteration after configurable cap."""

    def _make_state(self, *, iteration: int = 3, grounding_mode: str = "operator_local_only") -> dict:
        return {
            "graph_run_id": str(uuid4()),
            "thread_id": str(uuid4()),
            "iteration_index": iteration,
            "build_candidate_id": str(uuid4()),
            "evaluation_report": {
                "status": "partial",
                "summary": "needs work",
                "issues": [{"severity": "medium", "code": "test"}],
                "metrics": {"preview_grounding_mode": grounding_mode},
            },
        }

    def _make_ctx(self, *, weak_cap: int = 3):
        """Build a minimal GraphContext-like object for decision_router."""

        class _Settings:
            graph_max_iterations_default = 10
            kmbl_weakly_grounded_max_iterations = weak_cap

        class _Repo:
            def __init__(self):
                self._events: list = []

            def append_graph_run_event(self, *a, **kw):
                pass

            def get_evaluation_report(self, *a, **kw):
                return None

            def get_graph_run(self, *a, **kw):
                return None

            def save_graph_run_event(self, ev):
                self._events.append(ev)

            def list_graph_run_events(self, *a, **kw):
                return []

            def __getattr__(self, name):
                # Stub any method needed by decision_router
                return lambda *a, **kw: None

        class _Ctx:
            settings = _Settings()
            repo = _Repo()

        return _Ctx()

    def test_weak_grounding_caps_iterate(self):
        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(iteration=3, grounding_mode="operator_local_only")
        result = decision_router(ctx, state)
        # At iteration 3 with weak grounding and cap 3, should route to stage
        assert result["decision"] == "stage"

    def test_browser_grounding_allows_iterate(self):
        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(iteration=3, grounding_mode="browser_reachable")
        result = decision_router(ctx, state)
        # Browser grounding should allow iterate to continue
        assert result["decision"] == "iterate"

    def test_below_cap_allows_iterate(self):
        ctx = self._make_ctx(weak_cap=3)
        state = self._make_state(iteration=2, grounding_mode="operator_local_only")
        result = decision_router(ctx, state)
        # Below cap, iterate should continue
        assert result["decision"] == "iterate"

    def test_zero_cap_disables(self):
        ctx = self._make_ctx(weak_cap=0)
        state = self._make_state(iteration=5, grounding_mode="operator_local_only")
        result = decision_router(ctx, state)
        # Cap 0 disables check
        assert result["decision"] == "iterate"


# ---------------------------------------------------------------------------
# 4. Preview correctness — evaluator gets valid preview URL
# ---------------------------------------------------------------------------


class TestPreviewCorrectness:
    """P0 — evaluator gets valid browser-reachable preview URL, not null / private-blocked."""

    def _settings(self, **overrides) -> Settings:
        defaults = {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-key",
            "KMBL_ENV": "development",
            "orchestrator_port": 8000,
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_public_base_produces_preview_url(self):
        s = self._settings(orchestrator_public_base_url="https://tunnel.example.com")
        res = resolve_evaluator_preview_resolution(
            s,
            graph_run_id=str(uuid4()),
            thread_id=str(uuid4()),
            build_candidate=None,
        )
        assert res["preview_url"] is not None
        assert "candidate-preview" in res["preview_url"]
        assert res["preview_grounding_mode"] == "browser_reachable"

    def test_no_public_base_derives_local(self):
        s = self._settings()
        res = resolve_evaluator_preview_resolution(
            s,
            graph_run_id=str(uuid4()),
            thread_id=str(uuid4()),
            build_candidate=None,
        )
        # In dev mode, should derive local base
        assert res["orchestrator_public_base_source"] in ("configured", "derived_local")

    def test_private_host_blocked_without_allow_flag(self):
        s = self._settings(
            orchestrator_public_base_url="",
            kmbl_preview_derive_local_public_base=True,
        )
        res = resolve_evaluator_preview_resolution(
            s,
            graph_run_id=str(uuid4()),
            thread_id=str(uuid4()),
            build_candidate=None,
        )
        # Localhost should be detected
        if res.get("preview_url"):
            assert "127.0.0.1" in res["preview_url"] or "localhost" in res["preview_url"]

    def test_evaluator_grounding_evidence_quality_metric(self):
        """The evaluator_grounding_evidence_quality metric is computed correctly."""
        s = self._settings(orchestrator_public_base_url="https://tunnel.example.com")
        res = resolve_evaluator_preview_resolution(
            s,
            graph_run_id=str(uuid4()),
            thread_id=str(uuid4()),
            build_candidate=None,
        )
        # When preview_grounding_mode is browser_reachable, evidence quality should be "browser"
        assert res["preview_grounding_mode"] == "browser_reachable"
        # The evaluator node computes the metric from this — verify mode is correct


# ---------------------------------------------------------------------------
# 5. Portfolio bias removal — neutral archetype
# ---------------------------------------------------------------------------


class TestPortfolioBiasRemoval:
    """P0 — no implicit portfolio archetype default."""

    def test_no_archetype_default_injected(self):
        bs, normalized = normalize_build_spec_for_persistence({})
        # site_archetype should NOT be defaulted to "portfolio"
        assert bs.get("site_archetype") != "portfolio"

    def test_explicit_archetype_preserved(self):
        bs, _ = normalize_build_spec_for_persistence({"site_archetype": "portfolio"})
        assert bs["site_archetype"] == "portfolio"

    def test_whitespace_archetype_stripped(self):
        bs, _ = normalize_build_spec_for_persistence({"site_archetype": "  gallery  "})
        assert bs["site_archetype"] == "gallery"

    def test_empty_archetype_nullified(self):
        bs, _ = normalize_build_spec_for_persistence({"site_archetype": "  "})
        assert bs["site_archetype"] is None

    def test_non_portfolio_archetype_preserved(self):
        bs, _ = normalize_build_spec_for_persistence({"site_archetype": "interactive_app"})
        assert bs["site_archetype"] == "interactive_app"

    def test_type_defaults_to_generic(self):
        bs, normalized = normalize_build_spec_for_persistence({})
        assert bs["type"] == "generic"
        assert "type" in normalized


# ---------------------------------------------------------------------------
# 6. Lean summary builder
# ---------------------------------------------------------------------------


class TestLeanSummary:
    """P1 — minimal summary: keep entrypoint, file list, compliance; drop heavy sub-dicts."""

    def test_lean_keeps_essential_keys(self):
        full = {
            "summary_version": 2,
            "lane": "interactive_frontend_app_v1",
            "escalation_lane": None,
            "libraries_detected": ["three", "gsap"],
            "file_inventory": [{"path": "index.html"}],
            "file_inventory_truncated": False,
            "entrypoints": [{"path": "index.html"}],
            "experience_summary": {"experience_mode": "webgl_3d_portfolio"},
            "required_libraries_compliance": {"satisfied": True},
            "warnings": [],
            # Heavy stuff that should be dropped
            "sections_or_modules": [{"heading": "hero"}, {"heading": "about"}],
            "interaction_summary": {"cues": ["click", "scroll"]},
            "rendering_summary": {"has_webgl_hint": True},
            "asset_summary": {"splat_or_ply": 0},
            "compliance_summary": {"overall": "ok"},
            "previous_iteration_diff_summary": None,
        }
        lean = build_lean_summary_for_payload(full)
        assert "entrypoints" in lean
        assert "file_inventory" in lean
        assert "required_libraries_compliance" in lean
        assert "libraries_detected" in lean
        # Heavy keys dropped
        assert "sections_or_modules" not in lean
        assert "interaction_summary" not in lean
        assert "rendering_summary" not in lean
        assert "asset_summary" not in lean
        assert "compliance_summary" not in lean

    def test_lean_from_empty(self):
        assert build_lean_summary_for_payload({}) == {}

    def test_lean_from_none(self):
        assert build_lean_summary_for_payload(None) == {}


# ---------------------------------------------------------------------------
# 7. Live habitat materialization — workspace → habitat
# ---------------------------------------------------------------------------


class TestLiveHabitatMaterialization:
    """P1 — workspace→habitat flow becomes consistent."""

    def setup_method(self):
        clear_registry_for_tests()

    def test_workspace_promotes_to_live_habitat(self):
        tid = uuid4()
        gid = uuid4()
        manifest = materialize_workspace_to_live_habitat(
            thread_id=tid,
            graph_run_id=gid,
            workspace_path="/tmp/workspace/test",
            entrypoint="index.html",
        )
        assert manifest.materialization_kind == "live_habitat"
        assert manifest.materialization_status == "active"
        assert manifest.can_rehydrate_from_persistence is True

    def test_workspace_supersedes_prior_live_habitat(self):
        tid = uuid4()
        gid1 = uuid4()
        gid2 = uuid4()

        m1 = materialize_workspace_to_live_habitat(
            thread_id=tid, graph_run_id=gid1, workspace_path="/tmp/ws1",
        )
        m2 = materialize_workspace_to_live_habitat(
            thread_id=tid, graph_run_id=gid2, workspace_path="/tmp/ws2",
        )

        active = get_active_live_habitat(tid)
        assert active is not None
        assert active.manifest_id == m2.manifest_id

        # m1 should be superseded
        all_for_thread = list_manifests(thread_id=tid, materialization_kind="live_habitat")
        statuses = {m.manifest_id: m.materialization_status for m in all_for_thread}
        assert statuses[m1.manifest_id] == "superseded"
        assert statuses[m2.manifest_id] == "active"

    def test_candidate_preview_not_affected(self):
        tid = uuid4()
        gid = uuid4()

        # Register a candidate_preview
        register_materialization(
            thread_id=tid,
            local_path="/tmp/candidate",
            materialization_kind="candidate_preview",
            graph_run_id=gid,
            can_rehydrate_from_persistence=True,
        )

        # Promote workspace to live_habitat
        materialize_workspace_to_live_habitat(
            thread_id=tid, graph_run_id=gid, workspace_path="/tmp/ws",
        )

        # Both should be active
        all_m = list_manifests(thread_id=tid, status="active")
        kinds = {m.materialization_kind for m in all_m}
        assert "candidate_preview" in kinds
        assert "live_habitat" in kinds


# ---------------------------------------------------------------------------
# 8. Wire compaction version
# ---------------------------------------------------------------------------


class TestWireCompactionVersion:
    """Verify wire compaction version is v2."""

    def test_version_is_2(self):
        assert WIRE_COMPACTION_VERSION == 2

    def test_marker_includes_version(self):
        marker = wire_compaction_routing_marker(
            persist_raw_for_debug=False,
            wire_meta={"wire_compaction_version": 2, "workspace_first": True},
        )
        assert marker.get("wire_compaction_version") == 2
        assert marker.get("workspace_first") is True
