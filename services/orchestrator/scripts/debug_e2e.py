#!/usr/bin/env python3
"""Debug E2E test with verbose logging."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_SRC = _ORCH / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Set DEBUG for kiloclaw to see raw content
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("kmbl_orchestrator.providers.kiloclaw").setLevel(logging.DEBUG)

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    repo = InMemoryRepository()
    invoker = DefaultRoleInvoker(settings=settings)

    tid, gid = persist_graph_run_start(
        repo,
        thread_id=None,
        graph_run_id=None,
        identity_id=None,
        trigger_type="prompt",
        event_input={"smoke": True, "note": "debug_e2e"},
    )
    print(f"Started: thread={tid} graph_run={gid}")

    try:
        final = run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": str(tid),
                "graph_run_id": str(gid),
                "event_input": {"smoke": True},
            },
        )
        print(f"Result: decision={final.get('decision')} status={final.get('status')}")
        return 0
    except Exception as e:
        print(f"Failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
