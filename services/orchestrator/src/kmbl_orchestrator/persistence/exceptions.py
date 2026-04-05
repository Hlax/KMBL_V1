"""Persistence-layer errors with explicit semantics (no silent PostgREST fallbacks)."""


class ActiveGraphRunPerThreadConflictError(RuntimeError):
    """Insert/update would create a second active graph_run for the same thread (DB unique index)."""


class WriteSnapshotNotSupportedError(RuntimeError):
    """Entering ``in_memory_write_snapshot()`` on a Supabase-backed repository.

    PostgREST issues one HTTP request per call: there is **no** snapshot rollback
    spanning multiple repository methods. Multi-row atomicity on production paths
    uses Postgres RPC (``atomic_persist_staging_node_writes``,
    ``atomic_commit_working_staging_approval``, ``save_working_staging``).

    For unit tests that need rollback across several writes, use ``InMemoryRepository``.
    """

    def __init__(self) -> None:
        super().__init__(
            "in_memory_write_snapshot() is not supported on SupabaseRepository: "
            "PostgREST has no multi-statement rollback across HTTP calls. "
            "Use atomic_persist_staging_node_writes(), "
            "atomic_commit_working_staging_approval(), or save_working_staging() "
            "(all RPC-backed where applicable). For test rollback semantics, use InMemoryRepository."
        )
