"""Contract stability and drift detection tests.

These tests prevent:
1. Domain model drift from persistence layer
2. Overfitting to specific scenarios (e.g., Harvey portfolio)
3. Hardcoded values in core logic that should be configurable
"""

from __future__ import annotations

import inspect
import re
from typing import Any
from uuid import uuid4

import pytest

from kmbl_orchestrator.domain import (
    StagingCheckpointRecord,
    WorkingStagingRecord,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.staging.pressure import (
    PressureEvaluation,
    PressureThresholds,
    evaluate_staging_pressure,
)
from kmbl_orchestrator.staging.guardrails import (
    GuardrailEvaluation,
    GuardrailThresholds,
    evaluate_guardrails,
)
from kmbl_orchestrator.staging.facts import (
    WorkingStagingFacts,
    build_working_staging_facts,
)
from kmbl_orchestrator.staging.checkpoint_policy import (
    CheckpointDecision,
    decide_pre_update_checkpoint,
    decide_post_update_checkpoint,
)


class TestDomainPersistenceAlignment:
    """Verify domain models roundtrip correctly through persistence."""

    def test_working_staging_all_fields_persist(self) -> None:
        """All WorkingStagingRecord fields survive save/load cycle."""
        repo = InMemoryRepository()
        thread_id = uuid4()
        
        original = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=thread_id,
            identity_id=uuid4(),
            payload_json={"artifact_refs": [{"path": "test.html", "role": "static_frontend_file_v1"}]},
            last_update_mode="patch",
            last_update_graph_run_id=uuid4(),
            last_update_build_candidate_id=uuid4(),
            current_checkpoint_id=uuid4(),
            revision=5,
            status="draft",
            last_rebuild_revision=2,
            stagnation_count=3,
            last_evaluator_issue_count=4,
            last_revision_summary_json={"mode": "patch", "artifact_delta": {"added": 1}},
        )
        
        repo.save_working_staging(original)
        loaded = repo.get_working_staging_for_thread(thread_id)
        
        assert loaded is not None
        assert loaded.working_staging_id == original.working_staging_id
        assert loaded.thread_id == original.thread_id
        assert loaded.identity_id == original.identity_id
        assert loaded.payload_json == original.payload_json
        assert loaded.last_update_mode == original.last_update_mode
        assert loaded.revision == original.revision
        assert loaded.status == original.status
        assert loaded.last_rebuild_revision == original.last_rebuild_revision
        assert loaded.stagnation_count == original.stagnation_count
        assert loaded.last_evaluator_issue_count == original.last_evaluator_issue_count
        assert loaded.last_revision_summary_json == original.last_revision_summary_json

    def test_staging_checkpoint_all_fields_persist(self) -> None:
        """All StagingCheckpointRecord fields survive save/load cycle."""
        repo = InMemoryRepository()
        thread_id = uuid4()
        working_staging_id = uuid4()
        
        original = StagingCheckpointRecord(
            staging_checkpoint_id=uuid4(),
            working_staging_id=working_staging_id,
            thread_id=thread_id,
            payload_snapshot_json={"artifact_refs": [{"path": "snapshot.html"}]},
            revision_at_checkpoint=10,
            trigger="pre_rebuild",
            source_graph_run_id=uuid4(),
            reason_category="pressure_threshold",
            reason_explanation="Pressure score exceeded threshold (0.65 > 0.5)",
        )
        
        repo.save_staging_checkpoint(original)
        loaded_list = repo.list_staging_checkpoints(working_staging_id)
        
        assert len(loaded_list) == 1
        loaded = loaded_list[0]
        assert loaded.staging_checkpoint_id == original.staging_checkpoint_id
        assert loaded.working_staging_id == original.working_staging_id
        assert loaded.thread_id == original.thread_id
        assert loaded.payload_snapshot_json == original.payload_snapshot_json
        assert loaded.revision_at_checkpoint == original.revision_at_checkpoint
        assert loaded.trigger == original.trigger
        assert loaded.source_graph_run_id == original.source_graph_run_id
        assert loaded.reason_category == original.reason_category
        assert loaded.reason_explanation == original.reason_explanation

    def test_working_staging_optional_fields_default_gracefully(self) -> None:
        """Optional fields have sensible defaults when not provided."""
        repo = InMemoryRepository()
        thread_id = uuid4()
        
        minimal = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=thread_id,
        )
        
        repo.save_working_staging(minimal)
        loaded = repo.get_working_staging_for_thread(thread_id)
        
        assert loaded is not None
        assert loaded.last_rebuild_revision is None
        assert loaded.stagnation_count == 0
        assert loaded.last_evaluator_issue_count == 0
        assert loaded.last_revision_summary_json == {}


class TestScenarioAgnosticPressure:
    """Pressure evaluation must work with any scenario, not just known ones."""

    @pytest.mark.parametrize("patches,expected_above_threshold", [
        (0, False),
        (3, False),
        (5, False),
        (10, True),
        (15, True),
    ])
    def test_patch_count_pressure_is_linear(self, patches: int, expected_above_threshold: bool) -> None:
        """Patch count contributes linearly to pressure regardless of scenario."""
        thresholds = PressureThresholds()
        
        pressure = evaluate_staging_pressure(
            revision=patches + 1,
            patches_since_last_rebuild=patches,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
            thresholds=thresholds,
        )
        
        patch_signal = next((s for s in pressure.signals if s.signal_name == "patches_since_rebuild"), None)
        assert patch_signal is not None
        
        if expected_above_threshold:
            assert patch_signal.value > patch_signal.threshold
        else:
            assert patch_signal.value <= patch_signal.threshold

    @pytest.mark.parametrize("status,forces_rebuild", [
        ("pass", False),
        ("partial", False),
        ("fail", True),
        ("blocked", True),
    ])
    def test_evaluator_status_rebuild_forcing(self, status: str, forces_rebuild: bool) -> None:
        """Evaluator status forcing is consistent across all scenarios."""
        pressure = evaluate_staging_pressure(
            revision=5,
            patches_since_last_rebuild=4,
            evaluator_status=status,
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
        )
        
        assert pressure.should_rebuild == forces_rebuild

    @pytest.mark.parametrize("stagnation,artifacts,html,expected_signal_exceeded", [
        (0, 5, True, False),
        (5, 5, True, True),
        (0, 100, True, True),
        (0, 5, False, True),
    ])
    def test_pressure_signals_are_orthogonal(
        self, stagnation: int, artifacts: int, html: bool, expected_signal_exceeded: bool
    ) -> None:
        """Each pressure signal contributes independently to overall pressure."""
        pressure = evaluate_staging_pressure(
            revision=3,
            patches_since_last_rebuild=2,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=stagnation,
            total_artifact_count=artifacts,
            has_previewable_html=html,
        )
        
        any_exceeded = any(s.exceeded for s in pressure.signals)
        assert any_exceeded == expected_signal_exceeded


class TestScenarioAgnosticGuardrails:
    """Guardrails must apply uniformly across scenarios."""

    @pytest.mark.parametrize("patches,violation_expected", [
        (5, False),
        (10, False),
        (15, True),
        (20, True),
    ])
    def test_max_patches_guardrail(self, patches: int, violation_expected: bool) -> None:
        """Max patches guardrail triggers at threshold regardless of scenario."""
        thresholds = GuardrailThresholds(max_patches_before_forced_rebuild=12)
        
        evaluation = evaluate_guardrails(
            revision=patches + 1,
            patches_since_rebuild=patches,
            stagnation_count=0,
            artifact_count=10,
            checkpoint_count=2,
            has_previewable_html=True,
            thresholds=thresholds,
        )
        
        has_patch_violation = any(v.guardrail == "max_patches" for v in evaluation.violations)
        assert has_patch_violation == violation_expected

    @pytest.mark.parametrize("stagnation,violation_expected", [
        (0, False),
        (3, False),
        (5, True),
        (10, True),
    ])
    def test_stagnation_guardrail(self, stagnation: int, violation_expected: bool) -> None:
        """Stagnation guardrail triggers at threshold regardless of scenario."""
        thresholds = GuardrailThresholds(max_stagnation_iterations=4)
        
        evaluation = evaluate_guardrails(
            revision=10,
            patches_since_rebuild=5,
            stagnation_count=stagnation,
            artifact_count=10,
            checkpoint_count=2,
            has_previewable_html=True,
            thresholds=thresholds,
        )
        
        has_stagnation_violation = any(v.guardrail == "max_stagnation" for v in evaluation.violations)
        assert has_stagnation_violation == violation_expected


class TestDriftDetection:
    """Detect hardcoded scenario-specific values in core logic."""

    SCENARIO_SPECIFIC_PATTERNS = [
        r"harvey",
        r"lacsina",
        r"portfolio",
        r"kmbl_identity_url_static_v1",
        r"kmbl_static_frontend_pass",
        r"kiloclaw_image_only",
    ]

    def test_no_scenario_strings_in_pressure_module(self) -> None:
        """Pressure module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.pressure as module
        self._check_module_for_patterns(module)

    def test_no_scenario_strings_in_guardrails_module(self) -> None:
        """Guardrails module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.guardrails as module
        self._check_module_for_patterns(module)

    def test_no_scenario_strings_in_facts_module(self) -> None:
        """Facts module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.facts as module
        self._check_module_for_patterns(module)

    def test_no_scenario_strings_in_mutation_intent_module(self) -> None:
        """Mutation intent module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.mutation_intent as module
        self._check_module_for_patterns(module)

    def test_no_scenario_strings_in_checkpoint_policy_module(self) -> None:
        """Checkpoint policy module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.checkpoint_policy as module
        self._check_module_for_patterns(module)

    def test_no_scenario_strings_in_revision_journal_module(self) -> None:
        """Revision journal module should not contain scenario-specific strings."""
        import kmbl_orchestrator.staging.revision_journal as module
        self._check_module_for_patterns(module)

    def _check_module_for_patterns(self, module: Any) -> None:
        """Check module source for scenario-specific patterns."""
        try:
            source = inspect.getsource(module)
        except OSError:
            pytest.skip(f"Could not get source for {module}")
            return

        for pattern in self.SCENARIO_SPECIFIC_PATTERNS:
            matches = re.findall(pattern, source, re.IGNORECASE)
            assert not matches, (
                f"Found scenario-specific pattern '{pattern}' in {module.__name__}. "
                f"Core staging logic should be scenario-agnostic. Matches: {matches}"
            )

    def test_thresholds_are_configurable(self) -> None:
        """Threshold values should come from config objects, not hardcoded."""
        default_pressure = PressureThresholds()
        custom_pressure = PressureThresholds(
            max_patches_before_rebuild_consideration=20,
            max_stagnation_iterations=10,
            max_artifact_refs_for_healthy_surface=100,
        )
        
        assert default_pressure.max_patches_before_rebuild_consideration != custom_pressure.max_patches_before_rebuild_consideration
        
        p1 = evaluate_staging_pressure(
            revision=15,
            patches_since_last_rebuild=14,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
            thresholds=default_pressure,
        )
        
        p2 = evaluate_staging_pressure(
            revision=15,
            patches_since_last_rebuild=14,
            evaluator_status="pass",
            unresolved_issue_count=0,
            stagnation_iterations=0,
            total_artifact_count=5,
            has_previewable_html=True,
            thresholds=custom_pressure,
        )
        
        assert p1.pressure_score != p2.pressure_score, "Thresholds should affect pressure calculation"


class TestFactsBuilderGenerality:
    """Facts builder must work with any staging state, not just known shapes."""

    def test_empty_staging_produces_valid_facts(self) -> None:
        """Empty staging should produce valid facts, not crash."""
        staging = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
        )
        
        facts = build_working_staging_facts(
            staging,
            checkpoint_count=0,
        )
        
        assert isinstance(facts, WorkingStagingFacts)
        assert facts.revision_history.current_revision == 0
        assert facts.artifact_inventory.total_count == 0

    def test_none_staging_produces_valid_facts(self) -> None:
        """None staging should produce valid empty facts."""
        facts = build_working_staging_facts(None)
        
        assert isinstance(facts, WorkingStagingFacts)
        assert facts.is_empty
        assert facts.needs_rebuild

    def test_arbitrary_artifact_types_counted(self) -> None:
        """Facts builder should count any artifact type, not just known ones."""
        staging = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
            payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {"path": "a.html", "role": "static_frontend_file_v1", "language": "html"},
                        {"path": "b.css", "role": "static_frontend_file_v1"},
                        {"path": "img1.png", "role": "ui_image_v1"},
                        {"path": "custom.xyz", "role": "custom_artifact_type_v99"},
                    ]
                }
            },
            revision=5,
        )
        
        facts = build_working_staging_facts(staging)
        
        assert facts.artifact_inventory.total_count == 4
        assert "custom_artifact_type_v99" in facts.artifact_inventory.by_role

    def test_facts_with_maximal_state(self) -> None:
        """Facts builder handles fully populated staging without error."""
        staging = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
            identity_id=uuid4(),
            payload_json={
                "artifacts": {
                    "artifact_refs": [
                        {"path": f"file{i}.html", "role": "static_frontend_file_v1", "language": "html"}
                        for i in range(50)
                    ]
                },
                "static_frontend_preview_v1": {"entry_path": "file0.html"},
            },
            last_update_mode="patch",
            last_update_graph_run_id=uuid4(),
            revision=100,
            status="draft",
            last_rebuild_revision=50,
            stagnation_count=5,
            last_evaluator_issue_count=10,
            last_revision_summary_json={"mode": "patch", "artifact_delta": {"added": 5, "removed": 2}},
        )
        
        facts = build_working_staging_facts(
            staging,
            checkpoint_count=5,
            latest_checkpoint_revision=90,
            latest_checkpoint_trigger="post_patch",
            evaluator_status="partial",
            evaluator_issues=[{"severity": "error", "message": f"Issue {i}"} for i in range(10)],
            pressure_score=0.4,
            pressure_recommendation="neutral",
            pressure_concerns=["patches_since_rebuild"],
            patches_since_rebuild=50,
            stagnation_count=5,
        )
        
        assert facts.revision_history.current_revision == 100
        assert facts.artifact_inventory.total_count == 50
        assert facts.checkpoint_availability.checkpoint_count == 5
        assert facts.recent_evaluator is not None
        assert facts.recent_evaluator.issue_count == 10


class TestCheckpointPolicyGenerality:
    """Checkpoint policy should be scenario-independent."""

    @pytest.mark.parametrize("mode,revision,expect_checkpoint", [
        ("rebuild", 5, True),
        ("rebuild", 0, False),
        ("patch", 5, False),
        ("patch", 0, False),
    ])
    def test_pre_update_checkpoint_logic(
        self, mode: str, revision: int, expect_checkpoint: bool
    ) -> None:
        """Pre-update checkpoint logic is mode-based, not scenario-based."""
        staging = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
            revision=revision,
        )
        
        decision = decide_pre_update_checkpoint(
            working_staging=staging,
            update_mode=mode,  # type: ignore
            pressure_score=0.3,
        )
        
        assert decision.should_checkpoint == expect_checkpoint

    @pytest.mark.parametrize("mode,is_first_previewable,revision_after,expect_checkpoint", [
        ("patch", True, 5, True),
        ("patch", False, 5, False),
        ("patch", False, 3, True),
        ("rebuild", True, 5, True),
    ])
    def test_post_update_checkpoint_scenarios(
        self, mode: str, is_first_previewable: bool, revision_after: int, expect_checkpoint: bool
    ) -> None:
        """Post-update checkpoint logic handles various scenarios."""
        before = WorkingStagingRecord(
            working_staging_id=uuid4(),
            thread_id=uuid4(),
            revision=revision_after - 1,
        )
        after = WorkingStagingRecord(
            working_staging_id=before.working_staging_id,
            thread_id=before.thread_id,
            revision=revision_after,
        )
        
        decision = decide_post_update_checkpoint(
            before=before,
            after=after,
            update_mode=mode,  # type: ignore
            is_first_previewable=is_first_previewable,
        )
        
        assert decision.should_checkpoint == expect_checkpoint
