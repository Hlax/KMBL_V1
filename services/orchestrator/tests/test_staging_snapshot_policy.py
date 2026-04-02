"""staging_snapshot_policy gating for automatic review snapshot rows.

Mirrors ``graph.nodes_pkg.staging._should_create_staging_snapshot`` / ``staging_node``
(automatic ``staging_snapshot`` rows). Operator materialization: ``materialize_review_snapshot_from_live``.
"""

from __future__ import annotations

from kmbl_orchestrator.graph.nodes_pkg.staging import _should_create_staging_snapshot


def test_policy_always() -> None:
    assert _should_create_staging_snapshot("always", False) is True
    assert _should_create_staging_snapshot("always", True) is True


def test_policy_never() -> None:
    assert _should_create_staging_snapshot("never", False) is False
    assert _should_create_staging_snapshot("never", True) is False


def test_policy_on_nomination() -> None:
    assert _should_create_staging_snapshot("on_nomination", False) is False
    assert _should_create_staging_snapshot("on_nomination", True) is True


def test_unknown_policy_defaults_safe() -> None:
    assert _should_create_staging_snapshot("unknown", False) is True
