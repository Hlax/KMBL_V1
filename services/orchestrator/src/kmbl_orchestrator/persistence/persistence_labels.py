"""Small helpers for observability (which persistence path executed a write)."""

from __future__ import annotations


def staging_atomic_persistence_label(repo: object) -> str:
    """``supabase_rpc`` when Postgres RPC provides real transaction atomicity; else in-memory."""
    from kmbl_orchestrator.persistence.supabase_repository import SupabaseRepository

    return "supabase_rpc" if isinstance(repo, SupabaseRepository) else "in_memory_transaction"
