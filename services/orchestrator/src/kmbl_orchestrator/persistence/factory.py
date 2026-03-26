"""Select Supabase vs in-memory repository from settings."""

from __future__ import annotations

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.persistence.repository import InMemoryRepository, Repository
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository

_repo_singleton: Repository | None = None


def get_repository(settings: Settings) -> Repository:
    """Single process-wide repository — recreate only when settings/env change at restart."""
    global _repo_singleton
    if _repo_singleton is not None:
        return _repo_singleton
    url = (settings.supabase_url or "").strip()
    key = (settings.supabase_service_role_key or "").strip()
    if url and key:
        _repo_singleton = SupabaseRepository(settings)
    else:
        _repo_singleton = InMemoryRepository()
    return _repo_singleton


def reset_repository_singleton_for_tests() -> None:
    global _repo_singleton
    _repo_singleton = None
