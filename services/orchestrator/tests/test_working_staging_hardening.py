"""Tests for the working staging hardening pass.

Covers: pressure evaluation, revision journaling, checkpoint policy,
mutation intent, guardrails, and structured facts handoff.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from kmbl_orchestrator.domain import WorkingStagingRecord
from kmbl_orchestrator.staging.checkpoint_policy import (
    CheckpointReason,
    checkpoint_reason_to_trigger,
    decide_post_update_checkpoint,
    decide_pre_update_checkpoint,
)
from kmbl_orchestrator.staging.facts import (
    build_working_staging_facts,
    working_staging_facts_to_payload,
)
from kmbl_orchestrator.staging.guardrails import (
    compute_stagnation_count,
    evaluate_guardrails,
    GuardrailThresholds,
)
from kmbl_orchestrator.staging.mutation_intent import (
    MutationIntent,
    apply_mutation_plan_to_refs,
    extract_mutation_intent,
    resolve_mutation_plan,
)
from kmbl_orchestrator.staging.pressure import (
    PressureThresholds,
    count_patches_since_rebuild,
    evaluate_staging_pressure,
)
from kmbl_orchestrator.staging.revision_journal import (
    build_revision_summary,
    compute_artifact_delta,
    extract_issue_categories,
)


def _make_working_staging(
    *,
    revision: int = 0,
    status: str = "draft",
    payload: dict[str, Any] | None = None,
    last_rebuild_revision: int | None = None,
    stagnation_count: int = 0,
) -> WorkingStagingRecord:
    return WorkingStagingRecord(
        working_staging_id=uuid4(),
        thread_id=uuid4(),
        payload_json=payload or {},
        revision=revision,
        status=status,  # type: ignore[arg-type]
        last_rebuild_revision=last_rebuild_revision,
        stagnation_count=stagnation_count,
    )


class TestPressureEvaluation:
    def test_initial_build_forces_rebuild(self):
        pressure = evaluate_staging_pressure(
            revision=0,
            patches_since_last_rebuild=0,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=0,
            has_previewable_html=False,
        )
        assert pressure.should_rebuild
        assert pressure.rebuild_reason == "initial_build"
        assert pressure.recommendation == "rebuild"

    def test_fail_status_forces_rebuild(self):
        pressure = evaluate_staging_pressure(
            revision=5,
            patches_since_last_rebuild=2,
            evaluator_status="fail",
            unresolved_issue_count=3,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
        )
        assert pressure.should_rebuild
        assert "evaluator_status" in [s.signal_name for s in pressure.signals if s.exceeded]

    def test_pass_status_allows_patch(self):
        pressure = evaluate_staging_pressure(
            revision=3,
            patches_since_last_rebuild=2,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
        )
        assert not pressure.should_rebuild
        assert pressure.recommendation == "patch"

    def test_too_many_patches_triggers_rebuild(self):
        pressure = evaluate_staging_pressure(
            revision=15,
            patches_since_last_rebuild=15,
            evaluator_status="partial",
            unresolved_issue_count=8,
            stagnation_iterations=4,
            total_artifact_count=60,
            has_previewable_html=False,
            thresholds=PressureThresholds(
                max_patches_before_rebuild_consideration=8,
                max_stagnation_iterations=3,
                max_unresolved_issues_for_patch=5,
                max_artifact_refs_for_healthy_surface=50,
            ),
        )
        assert pressure.should_rebuild
        assert pressure.pressure_score >= 0.5
        assert len([s for s in pressure.signals if s.exceeded]) >= 3

    def test_stagnation_increases_pressure(self):
        pressure = evaluate_staging_pressure(
            revision=5,
            patches_since_last_rebuild=3,
            evaluator_status="partial",
            unresolved_issue_count=5,
            stagnation_iterations=4,
            total_artifact_count=10,
            has_previewable_html=True,
            thresholds=PressureThresholds(max_stagnation_iterations=3),
        )
        stag_signal = next(s for s in pressure.signals if s.signal_name == "stagnation_iterations")
        assert stag_signal.exceeded

    def test_count_patches_since_rebuild(self):
        assert count_patches_since_rebuild(5, 2) == 3
        assert count_patches_since_rebuild(5, None) == 5
        assert count_patches_since_rebuild(0, None) == 0


class TestRevisionJournal:
    def test_build_revision_summary(self):
        summary = build_revision_summary(
            revision=3,
            previous_revision=2,
            update_mode="patch",
            mode_reason_category="incremental_improvement",
            evaluator_status="pass",
            evaluator_issue_count=0,
            artifacts_added=1,
            total_artifact_count=5,
            has_previewable_html=True,
        )
        assert summary.revision == 3
        assert summary.previous_revision == 2
        assert summary.update_mode == "patch"
        assert summary.mode_reason.category == "incremental_improvement"
        assert summary.evaluator_influence is not None
        assert summary.evaluator_influence.status == "pass"

    def test_compute_artifact_delta(self):
        before = [
            {"path": "index.html", "role": "static_frontend_file_v1", "language": "html"},
            {"path": "old.css", "role": "static_frontend_file_v1", "language": "css"},
        ]
        after = [
            {"path": "index.html", "role": "static_frontend_file_v1", "language": "html"},
            {"path": "new.css", "role": "static_frontend_file_v1", "language": "css"},
        ]
        delta = compute_artifact_delta(before, after)
        assert delta.artifacts_added == 1
        assert delta.artifacts_replaced == 1
        assert delta.artifacts_removed == 1
        assert delta.has_previewable_html

    def test_extract_issue_categories(self):
        issues = [
            {"category": "layout", "message": "test"},
            {"type": "content", "message": "test"},
            {"severity": "warning", "message": "test"},
        ]
        categories = extract_issue_categories(issues)
        assert "layout" in categories
        assert "content" in categories
        assert "warning" in categories


class TestCheckpointPolicy:
    def test_pre_rebuild_checkpoint_decision(self):
        ws = _make_working_staging(revision=3)
        decision = decide_pre_update_checkpoint(
            working_staging=ws,
            update_mode="rebuild",
            pressure_score=0.0,
        )
        assert decision.should_checkpoint
        assert decision.reason is not None
        assert decision.reason.category == "pre_rebuild_safety"

    def test_no_checkpoint_for_patch(self):
        ws = _make_working_staging(revision=3)
        decision = decide_pre_update_checkpoint(
            working_staging=ws,
            update_mode="patch",
            pressure_score=0.0,
        )
        assert not decision.should_checkpoint

    def test_high_pressure_triggers_checkpoint(self):
        ws = _make_working_staging(revision=5)
        decision = decide_pre_update_checkpoint(
            working_staging=ws,
            update_mode="patch",
            pressure_score=0.6,
        )
        assert decision.should_checkpoint
        assert decision.reason is not None
        assert decision.reason.category == "pressure_threshold"

    def test_first_previewable_checkpoint(self):
        before = _make_working_staging(revision=1, payload={})
        after = _make_working_staging(
            revision=2,
            payload={
                "metadata": {"frontend_static": {"has_previewable_html": True}},
            },
        )
        decision = decide_post_update_checkpoint(
            before=before,
            after=after,
            update_mode="rebuild",
            is_first_previewable=True,
        )
        assert decision.should_checkpoint
        assert decision.reason is not None
        assert decision.reason.category == "first_previewable_state"

    def test_checkpoint_reason_to_trigger(self):
        reason = CheckpointReason(category="pre_rebuild_safety", explanation="test")
        assert checkpoint_reason_to_trigger(reason) == "pre_rebuild"

        reason = CheckpointReason(category="first_previewable_state", explanation="test")
        assert checkpoint_reason_to_trigger(reason) == "first_previewable_html"


class TestMutationIntent:
    def test_extract_mutation_intent_absent(self):
        raw = {"artifact_outputs": [], "updated_state": {}}
        intents = extract_mutation_intent(raw)
        assert intents is None

    def test_extract_mutation_intent_present(self):
        raw = {
            "_kmbl_mutation_intent": {
                "mode": "append",
                "target_paths": ["new.html"],
            }
        }
        intents = extract_mutation_intent(raw)
        assert intents is not None
        assert len(intents) == 1
        assert intents[0].mode == "append"

    def test_resolve_mutation_plan_fallback_patch(self):
        existing = [{"path": "a.html"}, {"path": "b.css"}]
        new = [{"path": "a.html"}, {"path": "c.js"}]
        plan = resolve_mutation_plan(
            update_mode="patch",
            intents=None,
            new_artifact_refs=new,
            existing_artifact_refs=existing,
        )
        assert plan.fallback_used
        assert plan.effective_mode == "patch"
        assert "c.js" in plan.paths_to_add
        assert "a.html" in plan.paths_to_replace

    def test_resolve_mutation_plan_fallback_rebuild(self):
        existing = [{"path": "a.html"}, {"path": "b.css"}]
        new = [{"path": "new.html"}]
        plan = resolve_mutation_plan(
            update_mode="rebuild",
            intents=None,
            new_artifact_refs=new,
            existing_artifact_refs=existing,
        )
        assert plan.fallback_used
        assert plan.effective_mode == "rebuild"
        assert "b.css" in plan.paths_to_remove

    def test_apply_mutation_plan_patch(self):
        existing = [{"path": "a.html", "content": "old"}]
        new = [{"path": "a.html", "content": "new"}, {"path": "b.css", "content": "new"}]
        plan = resolve_mutation_plan(
            update_mode="patch",
            intents=None,
            new_artifact_refs=new,
            existing_artifact_refs=existing,
        )
        result = apply_mutation_plan_to_refs(plan, existing, new)
        assert len(result) == 2
        paths = [r["path"] for r in result]
        assert "a.html" in paths
        assert "b.css" in paths

    def test_intent_with_preserve_paths(self):
        existing = [{"path": "keep.html"}, {"path": "old.css"}]
        new = [{"path": "new.js"}]
        intents = [
            MutationIntent(
                mode="append",
                preserve_paths=["keep.html"],
            )
        ]
        plan = resolve_mutation_plan(
            update_mode="patch",
            intents=intents,
            new_artifact_refs=new,
            existing_artifact_refs=existing,
        )
        assert "keep.html" in plan.paths_to_preserve


class TestGuardrails:
    def test_healthy_state(self):
        result = evaluate_guardrails(
            revision=3,
            patches_since_rebuild=2,
            stagnation_count=0,
            artifact_count=5,
            checkpoint_count=3,
            has_previewable_html=True,
        )
        assert result.is_healthy
        assert not result.forced_rebuild_required
        assert len(result.violations) == 0

    def test_max_patches_violation(self):
        result = evaluate_guardrails(
            revision=15,
            patches_since_rebuild=15,
            stagnation_count=0,
            artifact_count=10,
            checkpoint_count=5,
            has_previewable_html=True,
            thresholds=GuardrailThresholds(max_patches_before_forced_rebuild=12),
        )
        assert not result.is_healthy
        assert result.forced_rebuild_required
        assert result.forced_rebuild_reason == "max_patches_exceeded"

    def test_stagnation_violation(self):
        result = evaluate_guardrails(
            revision=10,
            patches_since_rebuild=5,
            stagnation_count=5,
            artifact_count=10,
            checkpoint_count=5,
            has_previewable_html=True,
            thresholds=GuardrailThresholds(max_stagnation_iterations=4),
        )
        assert not result.is_healthy
        assert result.forced_rebuild_required
        assert result.forced_rebuild_reason == "stagnation_detected"

    def test_compute_stagnation_count_improves(self):
        new_count = compute_stagnation_count(
            current_issue_count=2,
            previous_issue_count=5,
            current_status="partial",
            previous_status="fail",
            existing_stagnation_count=3,
        )
        assert new_count == 0

    def test_compute_stagnation_count_stagnates(self):
        new_count = compute_stagnation_count(
            current_issue_count=5,
            previous_issue_count=5,
            current_status="partial",
            previous_status="partial",
            existing_stagnation_count=2,
        )
        assert new_count == 3


class TestWorkingStagingFacts:
    def test_build_facts_empty_staging(self):
        facts = build_working_staging_facts(None)
        assert facts.is_empty
        assert facts.needs_rebuild
        assert not facts.can_patch

    def test_build_facts_with_content(self):
        ws = _make_working_staging(
            revision=3,
            status="review_ready",
            payload={
                "artifacts": {
                    "artifact_refs": [
                        {"path": "index.html", "role": "static_frontend_file_v1", "language": "html"},
                        {"path": "style.css", "role": "static_frontend_file_v1", "language": "css"},
                    ]
                }
            },
        )
        facts = build_working_staging_facts(
            ws,
            checkpoint_count=2,
            evaluator_status="pass",
            patches_since_rebuild=2,
        )
        assert not facts.is_empty
        assert facts.can_patch
        assert facts.artifact_inventory.total_count == 2
        assert facts.artifact_inventory.has_static_frontend
        assert facts.revision_history.current_revision == 3
        assert facts.checkpoint_availability.has_checkpoints

    def test_facts_to_payload(self):
        ws = _make_working_staging(revision=2)
        facts = build_working_staging_facts(ws)
        payload = working_staging_facts_to_payload(facts)
        assert "working_staging_id" in payload
        assert "revision_history" in payload
        assert "artifact_inventory" in payload


class TestIntegration:
    """Integration tests that verify the full flow."""

    def test_pressure_based_rebuild_selection(self):
        from kmbl_orchestrator.staging.working_staging_ops import choose_update_mode_with_pressure

        ws = _make_working_staging(
            revision=10,
            last_rebuild_revision=0,
            stagnation_count=4,
            payload={
                "artifacts": {"artifact_refs": [{"path": f"file{i}.html"} for i in range(60)]}
            },
        )

        mode, pressure, reason = choose_update_mode_with_pressure(
            ws, "partial", evaluation_issue_count=8
        )

        assert pressure is not None
        assert pressure.pressure_score > 0.3

    def test_backward_compatibility_choose_update_mode(self):
        from kmbl_orchestrator.staging.working_staging_ops import choose_update_mode

        ws = _make_working_staging(revision=5)
        mode = choose_update_mode(ws, "pass")
        assert mode == "patch"

        mode = choose_update_mode(ws, "fail")
        assert mode == "rebuild"

        mode = choose_update_mode(None, "pass")
        assert mode == "rebuild"
