"""staging_snapshot_policy gating for automatic review snapshot rows.

Mirrors ``runtime.staging_snapshot_policy_v1.should_create_staging_snapshot`` used by
``staging_node``. Operator materialization: ``materialize_review_snapshot_from_live``.
"""

from __future__ import annotations

from kmbl_orchestrator.runtime.staging_snapshot_policy_v1 import should_create_staging_snapshot


def _call(
    policy: str,
    marked: bool,
    *,
    evaluation_status: str = "pass",
    allow_partial_under_always: bool = False,
) -> bool:
    return should_create_staging_snapshot(
        policy,
        marked,
        evaluation_status=evaluation_status,
        allow_partial_under_always=allow_partial_under_always,
    )


def test_policy_always_pass() -> None:
    assert _call("always", False, evaluation_status="pass") is True
    assert _call("always", True, evaluation_status="pass") is True


def test_policy_always_partial_skips_by_default() -> None:
    assert _call("always", True, evaluation_status="partial") is False


def test_policy_always_partial_when_flag() -> None:
    assert _call(
        "always",
        True,
        evaluation_status="partial",
        allow_partial_under_always=True,
    ) is True


def test_policy_never() -> None:
    assert _call("never", False) is False
    assert _call("never", True) is False


def test_policy_on_nomination() -> None:
    assert _call("on_nomination", False) is False
    assert _call("on_nomination", True) is True


def test_unknown_policy_defaults_safe() -> None:
    assert _call("unknown", False) is True
