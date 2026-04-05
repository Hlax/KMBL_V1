"""Shared role strings for multi-file HTML/CSS/JS bundles (static vs interactive lane)."""

from __future__ import annotations

FRONTEND_FILE_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {
        "static_frontend_file_v1",
        "interactive_frontend_app_v1",
    }
)


def is_frontend_file_artifact_role(role: object | None) -> bool:
    return isinstance(role, str) and role in FRONTEND_FILE_ARTIFACT_ROLES
