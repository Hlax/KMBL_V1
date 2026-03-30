"""Sanitized checkpoint shapes for GET /orchestrator/runs/{id}."""

from __future__ import annotations

from kmbl_orchestrator.runtime.run_snapshot_sanitize import sanitize_checkpoint_state_for_api


def test_sanitize_drops_role_blobs() -> None:
    raw = {
        "thread_id": "a",
        "graph_run_id": "b",
        "iteration_index": 2,
        "decision": "accept",
        "build_spec": {"title": "secret", "raw": "kc"},
        "build_candidate": {"blob": "x"},
        "evaluation_report": {"y": 1},
        "identity_context": {"k": "v"},
        "event_input": {"scenario": "kmbl_seeded_local_v1", "task": "do not leak"},
    }
    out = sanitize_checkpoint_state_for_api(raw)
    assert out is not None
    assert out.get("iteration_index") == 2
    assert "build_spec" not in out
    assert out.get("event_input") == {"scenario": "kmbl_seeded_local_v1"}


def test_sanitize_includes_gallery_variation_provenance() -> None:
    raw = {
        "thread_id": "a",
        "graph_run_id": "b",
        "event_input": {
            "scenario": "kmbl_seeded_gallery_strip_varied_v1",
            "task": "hidden",
            "constraints": {
                "deterministic": False,
                "gallery_variation_mode": "explicit_bounded",
                "extra": "omit",
            },
            "variation": {
                "run_nonce": "abc123",
                "variation_seed": 42,
                "theme_variant": "pastel",
            },
        },
    }
    out = sanitize_checkpoint_state_for_api(raw)
    assert out is not None
    ei = out.get("event_input")
    assert isinstance(ei, dict)
    assert ei.get("scenario") == "kmbl_seeded_gallery_strip_varied_v1"
    assert ei.get("constraints") == {
        "deterministic": False,
        "gallery_variation_mode": "explicit_bounded",
    }
    assert ei.get("variation", {}).get("run_nonce") == "abc123"


def test_sanitize_none() -> None:
    assert sanitize_checkpoint_state_for_api(None) is None
