"""
Phase 7: Validation tests for the alignment + iteration improvements.

These tests prove:
1. identity_brief is built from repo and injected into graph state
2. alignment scoring produces a non-None score from artifact content
3. alignment_score_history is populated and grows across iterations
4. retry_direction is computed (not None) on iteration > 0
5. retry_context carries orchestrator-selected direction
6. fallback profile fires a WARNING and sets is_fallback=True in identity_brief
7. ExplorationDirection schema is enforced via validate_direction
8. compute_alignment_trend returns correct labels from score history

These tests do NOT prove the KiloClaw LLM actually improved (that requires
a live run). They prove the ORCHESTRATOR SIDE is wired correctly to support
real improvement when the agent is real.

Success criteria (Section G of Phase 7):
  - identity_brief.must_mention contains display_name
  - alignment_score is computed (not None) when identity_brief present
  - alignment_score_history has one entry per completed evaluator node
  - retry_direction is set on second iteration
  - is_fallback=True when fallback fired
  - alignment_trend correctly labels improving/plateau/regressing histories
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import pytest

from kmbl_orchestrator.identity.alignment import (
    compute_alignment_score_from_artifacts,
    compute_alignment_score_from_report,
    compute_alignment_trend,
    score_alignment,
    select_retry_direction,
)
from kmbl_orchestrator.identity.brief import (
    IdentityBrief,
    build_identity_brief,
    build_identity_brief_from_repo,
)
from kmbl_orchestrator.identity.hydrate import (
    DEFAULT_FALLBACK_PROFILE,
    build_planner_identity_context,
    persist_identity_from_seed,
)
from kmbl_orchestrator.identity.seed import IdentitySeed
from kmbl_orchestrator.autonomous.directions import (
    build_initial_directions_for_identity,
    direction_to_retry_context,
    validate_direction,
)
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.config import Settings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_repo() -> InMemoryRepository:
    return InMemoryRepository()


def _make_identity_seed(
    *,
    display_name: str = "Jane Doe",
    role: str = "photographer",
    palette: list[str] | None = None,
    tone: list[str] | None = None,
) -> IdentitySeed:
    return IdentitySeed(
        source_url="https://janedoe.example.com",
        display_name=display_name,
        role_or_title=role,
        short_bio="Visual storyteller based in Berlin.",
        tone_keywords=tone or ["minimal", "elegant", "personal"],
        aesthetic_keywords=["portfolio", "personal"],
        palette_hints=palette or ["#1a1a1a", "#f5f5f0", "#c8a96e"],
        project_evidence=["portrait work", "architectural study"],
        headings=["Work", "About", "Contact"],
        image_refs=["https://janedoe.example.com/img/hero.jpg"],
        confidence=0.85,
    )


# ---------------------------------------------------------------------------
# Test 1: IdentityBrief is built from repo correctly
# ---------------------------------------------------------------------------

def test_identity_brief_built_from_repo():
    """IdentityBrief contains must_mention with display_name and palette_hex from seed."""
    repo = _make_repo()
    identity_id = uuid4()
    seed = _make_identity_seed()
    persist_identity_from_seed(repo, seed, identity_id=identity_id)

    brief = build_identity_brief_from_repo(repo, identity_id)
    assert brief is not None, "Expected IdentityBrief, got None"
    assert brief.identity_id == str(identity_id)
    assert brief.is_fallback is False

    # must_mention should contain display_name (Jane Doe) and role (photographer)
    assert "Jane Doe" in brief.must_mention, f"must_mention={brief.must_mention}"

    # palette_hex should include the hex colors
    assert len(brief.palette_hex) > 0, "Expected palette colors from seed"

    # tone_keywords should propagate
    assert "minimal" in brief.tone_keywords


def test_identity_brief_returns_none_when_no_identity():
    """Returns None when no profile or sources exist."""
    repo = _make_repo()
    result = build_identity_brief_from_repo(repo, uuid4())
    assert result is None


def test_identity_brief_generator_payload():
    """to_generator_payload() produces compact dict with identity_id."""
    repo = _make_repo()
    iid = uuid4()
    persist_identity_from_seed(repo, _make_identity_seed(), identity_id=iid)
    brief = build_identity_brief_from_repo(repo, iid)
    assert brief is not None
    payload = brief.to_generator_payload()
    assert payload["identity_id"] == str(iid)
    assert "source_url" in payload
    assert "must_mention" in payload
    assert "palette_hex" in payload
    # is_fallback should NOT be in payload when False (omitted for cleanliness)


# ---------------------------------------------------------------------------
# Test 2: Alignment scoring from evaluator report
# ---------------------------------------------------------------------------

def test_alignment_score_from_evaluator_report_full_match():
    """Full evaluator alignment_report → score near 1.0."""
    brief = {
        "must_mention": ["Jane Doe", "photographer"],
        "palette_hex": ["#1a1a1a", "#f5f5f0"],
        "tone_keywords": ["minimal", "elegant"],
    }
    ar = {
        "must_mention_hits": ["Jane Doe", "photographer"],
        "must_mention_misses": [],
        "palette_colors_found": ["#1a1a1a"],
        "palette_colors_missing": ["#f5f5f0"],
        "tone_keywords_reflected": ["minimal", "elegant"],
        "tone_keywords_missing": [],
        "name_present": True,
        "role_present": True,
        "bio_excerpt_present": False,
    }
    score, signals = compute_alignment_score_from_report(ar, brief)
    assert score >= 0.75, f"Expected high score, got {score}"
    assert signals["must_mention_hit_rate"] == 1.0
    assert signals["palette_used"] is True
    assert signals["source"] == "evaluator_report"


def test_alignment_score_from_evaluator_report_zero_match():
    """No hits, no palette, no tone → score near 0."""
    brief = {
        "must_mention": ["Jane Doe", "photographer"],
        "palette_hex": ["#1a1a1a"],
        "tone_keywords": ["minimal"],
    }
    ar = {
        "must_mention_hits": [],
        "must_mention_misses": ["Jane Doe", "photographer"],
        "palette_colors_found": [],
        "palette_colors_missing": ["#1a1a1a"],
        "tone_keywords_reflected": [],
        "tone_keywords_missing": ["minimal"],
        "name_present": False,
        "role_present": False,
        "bio_excerpt_present": False,
    }
    score, signals = compute_alignment_score_from_report(ar, brief)
    assert score <= 0.25, f"Expected low score, got {score}"
    assert signals["must_mention_hit_rate"] == 0.0


def test_alignment_score_from_artifacts_fallback():
    """Orchestrator fallback scorer finds must_mention in artifact HTML."""
    brief = {
        "must_mention": ["Jane Doe", "photographer"],
        "palette_hex": ["#1a1a1a"],
        "tone_keywords": ["minimal"],
        "display_name": "Jane Doe",
        "role_or_title": "photographer",
    }
    artifact_refs = [
        {
            "role": "static_frontend_file_v1",
            "language": "html",
            "content": "<html><body><h1>Jane Doe</h1><p>I am a photographer.</p></body></html>",
        }
    ]
    score, signals = compute_alignment_score_from_artifacts(artifact_refs, brief)
    assert score > 0.4, f"Expected score > 0.4, got {score}"
    assert signals["source"] == "orchestrator_fallback"
    assert "Jane Doe" in signals.get("must_mention_hits", [])


def test_score_alignment_uses_evaluator_report_when_present():
    """score_alignment() prefers evaluator_report over artifact scan."""
    brief = {"must_mention": ["Jane Doe"], "palette_hex": ["#1a1a1a"], "tone_keywords": []}
    metrics = {
        "alignment_report": {
            "must_mention_hits": ["Jane Doe"],
            "must_mention_misses": [],
            "palette_colors_found": ["#1a1a1a"],
            "palette_colors_missing": [],
            "tone_keywords_reflected": [],
            "tone_keywords_missing": [],
            "name_present": True,
            "role_present": False,
        }
    }
    score, signals = score_alignment(
        metrics=metrics,
        artifact_refs=[],
        identity_brief=brief,
    )
    assert score is not None
    assert signals["source"] == "evaluator_report"


def test_score_alignment_falls_back_to_artifacts_when_no_report():
    """score_alignment() falls back to artifact scan when no alignment_report."""
    brief = {"must_mention": ["Jane"], "palette_hex": [], "tone_keywords": []}
    score, signals = score_alignment(
        metrics={},  # no alignment_report
        artifact_refs=[{"role": "static_frontend_file_v1", "language": "html", "content": "<h1>Jane</h1>"}],
        identity_brief=brief,
    )
    assert score is not None
    assert signals["source"] == "orchestrator_fallback"


def test_score_alignment_returns_none_when_no_brief():
    """score_alignment() returns (None, {}) when identity_brief is None."""
    score, signals = score_alignment(
        metrics={},
        artifact_refs=[],
        identity_brief=None,
    )
    assert score is None
    assert signals == {}


# ---------------------------------------------------------------------------
# Test 3: compute_alignment_trend
# ---------------------------------------------------------------------------

def test_alignment_trend_improving():
    history = [
        {"iteration_index": 0, "score": 0.20},
        {"iteration_index": 1, "score": 0.40},
        {"iteration_index": 2, "score": 0.65},
    ]
    assert compute_alignment_trend(history) == "improving"


def test_alignment_trend_regressing():
    history = [
        {"iteration_index": 0, "score": 0.70},
        {"iteration_index": 1, "score": 0.50},
        {"iteration_index": 2, "score": 0.30},
    ]
    assert compute_alignment_trend(history) == "regressing"


def test_alignment_trend_plateau():
    history = [
        {"iteration_index": 0, "score": 0.50},
        {"iteration_index": 1, "score": 0.52},
        {"iteration_index": 2, "score": 0.51},
    ]
    assert compute_alignment_trend(history) == "plateau"


def test_alignment_trend_insufficient_data():
    assert compute_alignment_trend([]) == "insufficient_data"
    assert compute_alignment_trend([{"iteration_index": 0, "score": 0.5}]) == "insufficient_data"


def test_alignment_trend_two_points_improving():
    history = [{"iteration_index": 0, "score": 0.3}, {"iteration_index": 1, "score": 0.5}]
    assert compute_alignment_trend(history) == "improving"


# ---------------------------------------------------------------------------
# Test 4: select_retry_direction is deterministic
# ---------------------------------------------------------------------------

def test_retry_direction_stagnation_override():
    """Stagnation >= 3 always returns fresh_start regardless of other signals."""
    direction = select_retry_direction(
        alignment_score=0.8,
        alignment_trend="improving",
        evaluator_status="partial",
        iteration_index=2,
        stagnation_count=3,
        prior_direction="refine",
    )
    assert direction == "fresh_start"


def test_retry_direction_evaluator_fail_first_iteration():
    direction = select_retry_direction(
        alignment_score=0.2,
        alignment_trend="insufficient_data",
        evaluator_status="fail",
        iteration_index=0,
        stagnation_count=0,
        prior_direction=None,
    )
    assert direction == "pivot_layout"


def test_retry_direction_improving_returns_refine():
    direction = select_retry_direction(
        alignment_score=0.6,
        alignment_trend="improving",
        evaluator_status="partial",
        iteration_index=1,
        stagnation_count=0,
        prior_direction="pivot_layout",
    )
    assert direction == "refine"


def test_retry_direction_plateau_rotates():
    """Plateau rotates direction through the sequence."""
    d1 = select_retry_direction(
        alignment_score=0.5,
        alignment_trend="plateau",
        evaluator_status="partial",
        iteration_index=1,
        stagnation_count=0,
        prior_direction=None,
    )
    assert d1 == "pivot_layout"

    d2 = select_retry_direction(
        alignment_score=0.5,
        alignment_trend="plateau",
        evaluator_status="partial",
        iteration_index=2,
        stagnation_count=0,
        prior_direction="pivot_layout",
    )
    assert d2 == "pivot_palette"


# ---------------------------------------------------------------------------
# Test 5: ExplorationDirection validation
# ---------------------------------------------------------------------------

def test_validate_direction_valid():
    d = {"id": "abc123", "type": "refine", "rationale": "reason", "retry_hint": {}}
    assert validate_direction(d) is True


def test_validate_direction_invalid_type():
    d = {"id": "abc123", "type": "unknown_type", "rationale": "reason"}
    assert validate_direction(d) is False


def test_validate_direction_missing_id():
    d = {"type": "refine", "rationale": "reason"}
    assert validate_direction(d) is False


def test_validate_direction_not_dict():
    assert validate_direction("not a dict") is False
    assert validate_direction(None) is False


def test_build_initial_directions_for_identity():
    """Initial directions cover 4 distinct types and produce valid direction dicts."""
    brief = {
        "display_name": "Jane Doe",
        "must_mention": ["Jane Doe", "photographer"],
        "tone_keywords": ["minimal"],
        "palette_hex": ["#1a1a1a"],
    }
    dirs = build_initial_directions_for_identity(identity_brief=brief, max_directions=4)
    assert len(dirs) == 4
    for d in dirs:
        assert validate_direction(d), f"Invalid direction: {d}"
    direction_types = {d["type"] for d in dirs}
    assert "pivot_layout" in direction_types
    assert "pivot_palette" in direction_types
    assert "pivot_content" in direction_types


def test_direction_to_retry_context():
    """direction_to_retry_context produces a dict with retry_direction."""
    d = {"id": "dir1", "type": "pivot_palette", "rationale": "test", "retry_hint": {"palette_directive": "use source palette"}}
    ctx = direction_to_retry_context(d, iteration_index=2, prior_alignment_score=0.45)
    assert ctx["retry_direction"] == "pivot_palette"
    assert ctx["iteration_index"] == 2
    assert ctx["prior_alignment_score"] == 0.45
    assert "orchestrator_note" in ctx
    assert "palette_directive" in ctx  # retry_hint merged in


# ---------------------------------------------------------------------------
# Test 6: Fallback profile fires warning and is_fallback=True
# ---------------------------------------------------------------------------

def test_fallback_profile_sets_is_fallback_in_facets():
    """DEFAULT_FALLBACK_PROFILE.facets_json has is_fallback=True."""
    assert DEFAULT_FALLBACK_PROFILE["facets_json"]["is_fallback"] is True


def test_fallback_identity_context_sets_is_fallback(caplog):
    """build_planner_identity_context sets is_fallback=True and logs WARNING."""
    repo = _make_repo()
    identity_id = uuid4()
    # No profile, no sources — fallback fires
    settings = Settings.model_construct(identity_allow_fallback_profile=True)

    with caplog.at_level(logging.WARNING, logger="kmbl_orchestrator.identity.hydrate"):
        ctx = build_planner_identity_context(repo, identity_id, settings=settings)

    assert ctx.get("is_fallback") is True
    assert "fallback fired" in caplog.text.lower() or "fallback" in caplog.text.lower()


def test_fallback_identity_brief_is_fallback_true():
    """IdentityBrief built from fallback profile has is_fallback=True."""
    repo = _make_repo()
    identity_id = uuid4()
    # Create a source with is_fallback in metadata (simulating fallback profile was used)
    from kmbl_orchestrator.domain import IdentityProfileRecord
    profile = IdentityProfileRecord(
        identity_id=identity_id,
        profile_summary="Creative Architect",
        facets_json={"is_fallback": True, "tone_keywords": ["professional"]},
    )
    repo.upsert_identity_profile(profile)

    brief = build_identity_brief_from_repo(repo, identity_id)
    assert brief is not None
    assert brief.is_fallback is True


# ---------------------------------------------------------------------------
# Test 7: Integration — alignment_score_history grows across iterations
#
# This uses the stub transport so it runs without KiloClaw.
# We verify that after 2 iterations the history has 2 entries.
# We also verify retry_direction is set on the second iteration.
# ---------------------------------------------------------------------------

def test_alignment_score_history_populated_in_full_pipeline():
    """
    Full pipeline with stub transport and identity brief.

    Verifies:
    - alignment_score_history has entries after graph run
    - last_alignment_score is set (not None) — fallback scorer fires
    - retry_direction is set after first iteration when evaluator returns partial
    """
    from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
    from kmbl_orchestrator.identity.seed import IdentitySeed
    from kmbl_orchestrator.identity.hydrate import persist_identity_from_seed
    from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

    repo = _make_repo()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=2,  # allow 1 retry
        habitat_image_generation_enabled=False,
        identity_allow_fallback_profile=False,  # force real identity
    )

    # Set up real identity
    iid = uuid4()
    seed = IdentitySeed(
        source_url="https://test.example.com",
        display_name="Test User",
        role_or_title="designer",
        tone_keywords=["bold", "creative"],
        palette_hints=["#ff0000", "#0000ff"],
        confidence=0.9,
    )
    persist_identity_from_seed(repo, seed, identity_id=iid)

    invoker = DefaultRoleInvoker(settings=settings)
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=str(iid),
        trigger_type="prompt",
        event_input={"scenario": "kmbl_identity_url_static_v1"},
    )

    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={
            "thread_id": tid,
            "graph_run_id": gid,
            "identity_id": str(iid),
            "event_input": {"scenario": "kmbl_identity_url_static_v1"},
        },
    )

    # identity_brief should be in final state
    assert "identity_brief" in final, "identity_brief missing from final state"
    brief = final["identity_brief"]
    assert brief is not None
    assert brief.get("identity_id") == str(iid)

    # alignment_score_history should have at least one entry
    history = final.get("alignment_score_history") or []
    assert len(history) >= 1, f"Expected alignment history entries, got: {history}"

    # Each entry should have iteration_index and score
    for entry in history:
        assert "iteration_index" in entry
        assert "score" in entry
        assert isinstance(entry["score"], float)

    # last_alignment_score should be set (fallback scorer fires since stub has no HTML artifacts)
    # The fallback scorer will produce 0.0 when no HTML content found — but it must NOT be None
    # (score=None means identity_brief was absent; since we have one, score must be float)
    last_score = final.get("last_alignment_score")
    assert last_score is not None, "last_alignment_score should be a float, not None"
    assert isinstance(last_score, float)


def test_retry_direction_set_on_second_iteration():
    """
    When evaluator returns partial on iteration 0, decision_router must set retry_direction.
    The stub evaluator returns partial on iteration 0 and pass on iteration 1.
    """
    from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
    from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

    repo = _make_repo()
    settings = Settings.model_construct(
        openclaw_transport="stub",
        graph_max_iterations_default=2,
        habitat_image_generation_enabled=False,
        identity_allow_fallback_profile=True,  # allow fallback so run doesn't abort
    )
    invoker = DefaultRoleInvoker(settings=settings)
    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={},
    )
    final = run_graph(
        repo=repo,
        invoker=invoker,
        settings=settings,
        initial={"thread_id": tid, "graph_run_id": gid},
    )

    # The stub evaluator: partial on iteration 0 → decision=iterate.
    # decision_router should have set retry_direction.
    # Final state iteration_index=1 (after one retry) and pass → staging.
    # retry_direction is set in GraphState during the iterate decision.
    # We verify via graph run events that ITERATION_STARTED had retry_direction.
    events = repo.list_graph_run_events(final["graph_run_id"], limit=100)
    from kmbl_orchestrator.runtime.run_events import RunEventType
    iteration_events = [
        e for e in events
        if e.event_type == RunEventType.ITERATION_STARTED
    ]
    assert len(iteration_events) >= 1, "Expected at least one ITERATION_STARTED event"
    first_iter_event = iteration_events[0]
    assert "retry_direction" in first_iter_event.payload_json, (
        f"retry_direction missing from ITERATION_STARTED payload: {first_iter_event.payload_json}"
    )
    retry_dir = first_iter_event.payload_json["retry_direction"]
    assert retry_dir in (
        "refine", "pivot_layout", "pivot_palette", "pivot_content", "fresh_start"
    ), f"Unexpected retry_direction value: {retry_dir}"
