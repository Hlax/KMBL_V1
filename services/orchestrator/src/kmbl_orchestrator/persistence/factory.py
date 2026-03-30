"""Select Supabase vs in-memory repository from settings."""

from __future__ import annotations

from typing import Literal

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.persistence.repository import InMemoryRepository, Repository
from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository


def repository_backend(settings: Settings) -> Literal["supabase", "in_memory"]:
    """Which persistence backend would be selected (does not instantiate the singleton)."""
    url = (settings.supabase_url or "").strip()
    key = (settings.supabase_service_role_key or "").strip()
    return "supabase" if (url and key) else "in_memory"


def persisted_graph_runs_available(settings: Settings) -> bool:
    """True when thread/graph_run/role rows can be written to Supabase (not in-memory dev mode)."""
    return repository_backend(settings) == "supabase"

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
