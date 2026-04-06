"""Settings validation for SUPABASE_URL shape."""

from __future__ import annotations

import pytest

from kmbl_orchestrator.config import Settings


def test_rejects_dashboard_style_url() -> None:
    with pytest.raises(ValueError, match="dashboard|project"):
        Settings(
            supabase_url="https://app.supabase.com/project/abc",
            supabase_service_role_key="x",
        )


def test_rejects_key_without_url() -> None:
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings(
            supabase_url="",
            supabase_service_role_key="secret",
        )


def test_accepts_typical_hosted_supabase_url() -> None:
    s = Settings(
        supabase_url="https://abcdefgh.supabase.co",
        supabase_service_role_key="test",
    )
    assert "supabase.co" in s.supabase_url
