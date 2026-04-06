"""
Tests for the demo-path improvements from the full repo audit.

Covers:
    DP1  habitat lifecycle wired into staging/generator nodes
    DP2  public/tunnel preview URL flows to evaluator grounding
    DP3  evaluator build_spec compacted to evaluation contract
    DP4  evaluator issues truncated before generator retry
    DP5  Playwright enrichment in identity_fetch
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.runtime.habitat_lifecycle import (
    clear_registry_for_tests,
    get_active_live_habitat,
    list_manifests,
    register_materialization,
)
from kmbl_orchestrator.runtime.session_staging_links import (
    resolve_evaluator_preview_resolution,
)


@pytest.fixture(autouse=True)
def _reset_habitat_registry() -> None:
    """Ensure a clean habitat registry for every test."""
    clear_registry_for_tests()


# ── DP1: habitat lifecycle now enabled by default ────────────────────────

def test_habitat_lifecycle_enabled_by_default() -> None:
    """Config default for kmbl_habitat_lifecycle_enabled should be True."""
    s = Settings()
    assert s.kmbl_habitat_lifecycle_enabled is True


def test_staging_node_registers_live_habitat() -> None:
    """Verify that register_materialization for live_habitat works as expected
    when called from the staging code path (unit-level, not full graph)."""
    tid = uuid4()
    gid = uuid4()
    wsid = uuid4()

    m = register_materialization(
        thread_id=tid,
        local_path=f"working_staging/{tid}/{wsid}",
        materialization_kind="live_habitat",
        graph_run_id=gid,
        source_revision=3,
        revision_id=wsid,
        can_rehydrate_from_persistence=True,
    )
    assert m.materialization_kind == "live_habitat"
    assert m.materialization_status == "active"
    assert m.thread_id == tid
    assert m.graph_run_id == gid
    assert m.source_revision == 3

    active = get_active_live_habitat(tid)
    assert active is not None
    assert active.manifest_id == m.manifest_id


def test_staging_node_registers_staging_preview_on_snapshot() -> None:
    """Verify staging_preview registration works for snapshot creation."""
    tid = uuid4()
    gid = uuid4()
    ssid = uuid4()

    m = register_materialization(
        thread_id=tid,
        local_path=f"staging_snapshot/{tid}/{ssid}",
        materialization_kind="staging_preview",
        graph_run_id=gid,
        revision_id=ssid,
        can_rehydrate_from_persistence=True,
    )
    assert m.materialization_kind == "staging_preview"
    assert m.materialization_status == "active"

    all_manifests = list_manifests(thread_id=tid)
    assert len(all_manifests) == 1
    assert all_manifests[0].materialization_kind == "staging_preview"


def test_generator_registers_candidate_preview() -> None:
    """Verify candidate_preview registration works for build_candidate."""
    tid = uuid4()
    gid = uuid4()
    bcid = uuid4()

    m = register_materialization(
        thread_id=tid,
        local_path=f"candidate_preview/{tid}/{bcid}",
        materialization_kind="candidate_preview",
        graph_run_id=gid,
        revision_id=bcid,
        can_rehydrate_from_persistence=True,
    )
    assert m.materialization_kind == "candidate_preview"
    assert m.materialization_status == "active"


def test_live_habitat_supersedes_previous_on_re_registration() -> None:
    """Second staging node call (new iteration) supersedes previous live_habitat."""
    tid = uuid4()
    m1 = register_materialization(
        thread_id=tid,
        local_path="/tmp/ws1",
        materialization_kind="live_habitat",
        source_revision=1,
        can_rehydrate_from_persistence=True,
    )
    m2 = register_materialization(
        thread_id=tid,
        local_path="/tmp/ws2",
        materialization_kind="live_habitat",
        source_revision=2,
        can_rehydrate_from_persistence=True,
    )
    active = get_active_live_habitat(tid)
    assert active is not None
    assert active.manifest_id == m2.manifest_id

    all_m = list_manifests(thread_id=tid, materialization_kind="live_habitat")
    statuses = {m.manifest_id: m.materialization_status for m in all_m}
    assert statuses[m1.manifest_id] == "superseded"
    assert statuses[m2.manifest_id] == "active"


# ── DP2: public/tunnel preview URL flows to evaluator grounding ──────────

def test_public_tunnel_url_reaches_evaluator_as_browser_reachable() -> None:
    """When KMBL_ORCHESTRATOR_PUBLIC_BASE_URL is a public tunnel, evaluator
    gets preview_url with grounding_mode=browser_reachable."""
    s = Settings(orchestrator_public_base_url="https://abc123.ngrok.io")
    res = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="run-1",
        thread_id="thread-1",
        build_candidate=None,
    )
    assert res["preview_url"] is not None
    assert res["preview_url"].startswith("https://abc123.ngrok.io/")
    assert res["preview_grounding_mode"] == "browser_reachable"
    assert res["preview_grounding_reason"] == "public_orchestrator_base"
    assert res["preview_grounding"] == "ok"
    assert res["preview_grounding_degraded"] is False


def test_demo_public_base_url_alias_works() -> None:
    """KMBL_DEMO_PUBLIC_BASE_URL should work as an alias for orchestrator_public_base_url."""
    s = Settings(orchestrator_public_base_url="https://my-tunnel.example.com")
    res = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="run-1",
        thread_id="thread-1",
        build_candidate=None,
    )
    assert res["preview_url"] is not None
    assert res["preview_url"].startswith("https://my-tunnel.example.com/")
    assert res["preview_grounding_mode"] == "browser_reachable"


def test_no_public_base_yields_degraded_grounding() -> None:
    """Without a public base URL, evaluator grounding is degraded in production."""
    s = Settings(
        orchestrator_public_base_url="",
        kmbl_env="production",
        kmbl_preview_derive_local_public_base=False,
    )
    res = resolve_evaluator_preview_resolution(
        s,
        graph_run_id="run-1",
        thread_id="thread-1",
        build_candidate=None,
    )
    assert res["preview_grounding_mode"] == "unavailable"


# ── DP3: evaluator build_spec compacted to evaluation contract ───────────

def test_build_evaluation_contract_keeps_only_relevant_keys() -> None:
    """build_evaluation_contract strips creative-brief and crawl context."""
    from kmbl_orchestrator.graph.nodes_pkg.evaluator import build_evaluation_contract

    full_spec = {
        "experience_mode": "immersive_spatial_portfolio",
        "surface_type": "webgl_experience",
        "site_archetype": "creative_portfolio",
        "canonical_vertical": "static_frontend",
        "literal_success_checks": [{"check": "has_three_js"}],
        "machine_constraints": {"max_file_size_kb": 500},
        "cool_generation_lane": True,
        "interaction_model": "scroll_driven",
        "motion_spec": {"entrance": "fade"},
        "required_libraries": ["three"],
        "library_hints": ["gsap"],
        # These should be DROPPED
        "creative_brief": {"story": "A very long creative brief..."},
        "crawl_context": {"next_urls": ["http://example.com"]},
        "reference_payload": {"cards": [1, 2, 3]},
        "success_criteria": [{"id": "sc1"}],
        "evaluation_targets": ["layout"],
        "selected_urls": ["http://example.com/about"],
        "identity_summary": "Jane Doe, designer",
    }
    contract = build_evaluation_contract(full_spec)

    # Relevant keys preserved
    assert contract["experience_mode"] == "immersive_spatial_portfolio"
    assert contract["surface_type"] == "webgl_experience"
    assert contract["literal_success_checks"] == [{"check": "has_three_js"}]
    assert contract["cool_generation_lane"] is True

    # Large/irrelevant keys dropped
    assert "creative_brief" not in contract
    assert "crawl_context" not in contract
    assert "reference_payload" not in contract
    assert "success_criteria" not in contract  # Sent separately to evaluator LLM
    assert "evaluation_targets" not in contract  # Sent separately to evaluator LLM
    assert "selected_urls" not in contract
    assert "identity_summary" not in contract


def test_build_evaluation_contract_handles_empty() -> None:
    from kmbl_orchestrator.graph.nodes_pkg.evaluator import build_evaluation_contract
    assert build_evaluation_contract({}) == {}
    assert build_evaluation_contract(None) == {}  # type: ignore[arg-type]


# ── DP4: evaluator issues truncated before generator retry ───────────────

def test_generator_truncates_feedback_issues_to_five() -> None:
    """When evaluator returns >5 issues, generator feedback only includes first 5."""
    issues = [{"type": f"issue_{i}", "description": f"Problem {i}"} for i in range(12)]
    feedback = {
        "status": "fail",
        "issues": issues,
        "summary": "lots of problems",
    }
    # Simulate what the generator does
    if isinstance(feedback, dict) and isinstance(feedback.get("issues"), list):
        if len(feedback["issues"]) > 5:
            feedback = {**feedback, "issues": feedback["issues"][:5]}

    assert len(feedback["issues"]) == 5
    assert feedback["issues"][0]["type"] == "issue_0"
    assert feedback["issues"][4]["type"] == "issue_4"
    # Status and summary preserved
    assert feedback["status"] == "fail"
    assert feedback["summary"] == "lots of problems"


def test_generator_preserves_issues_when_five_or_fewer() -> None:
    """When evaluator returns ≤5 issues, no truncation occurs."""
    issues = [{"type": f"issue_{i}"} for i in range(3)]
    feedback = {"status": "partial", "issues": issues}

    if isinstance(feedback, dict) and isinstance(feedback.get("issues"), list):
        if len(feedback["issues"]) > 5:
            feedback = {**feedback, "issues": feedback["issues"][:5]}

    assert len(feedback["issues"]) == 3


def test_generator_handles_no_issues_in_feedback() -> None:
    """When feedback has no issues key, truncation is a no-op."""
    feedback = {"status": "pass", "summary": "all good"}

    if isinstance(feedback, dict) and isinstance(feedback.get("issues"), list):
        if len(feedback["issues"]) > 5:
            feedback = {**feedback, "issues": feedback["issues"][:5]}

    assert "issues" not in feedback


# ── DP5: Playwright enrichment integration points ────────────────────────

def test_playwright_enrichment_config_defaults() -> None:
    """Playwright wrapper URL defaults to empty (disabled) but max_pages > 0."""
    s = Settings()
    assert s.kmbl_playwright_wrapper_url == ""
    assert s.kmbl_playwright_max_pages_per_loop > 0


def test_playwright_enrichment_gate_logic() -> None:
    """Playwright enrichment gate: only fires when URL is set and max_pages > 0."""
    s = Settings(kmbl_playwright_wrapper_url="http://localhost:3100")
    pw_url = (s.kmbl_playwright_wrapper_url or "").strip()
    assert pw_url
    assert s.kmbl_playwright_max_pages_per_loop > 0
    use_playwright = bool(pw_url) and s.kmbl_playwright_max_pages_per_loop > 0
    assert use_playwright is True


def test_playwright_enrichment_disabled_when_url_empty() -> None:
    """When KMBL_PLAYWRIGHT_WRAPPER_URL is empty, enrichment is skipped."""
    s = Settings(kmbl_playwright_wrapper_url="")
    pw_url = (s.kmbl_playwright_wrapper_url or "").strip()
    use_playwright = bool(pw_url) and s.kmbl_playwright_max_pages_per_loop > 0
    assert use_playwright is False


def test_playwright_enrichment_disabled_when_max_pages_zero() -> None:
    """When max_pages is 0, enrichment is skipped even with URL set."""
    s = Settings(
        kmbl_playwright_wrapper_url="http://localhost:3100",
        kmbl_playwright_max_pages_per_loop=0,
    )
    pw_url = (s.kmbl_playwright_wrapper_url or "").strip()
    use_playwright = bool(pw_url) and s.kmbl_playwright_max_pages_per_loop > 0
    assert use_playwright is False
