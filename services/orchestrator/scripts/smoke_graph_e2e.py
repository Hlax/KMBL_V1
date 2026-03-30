#!/usr/bin/env python3
"""
End-to-end LangGraph smoke: planner → generator → evaluator → decision → staging.

Uses an in-memory repository (no Supabase required). Loads the same `.env` / `.env.local`
as the API (see `kmbl_orchestrator.config`).

Run from repo root or `services/orchestrator`::

  cd services/orchestrator
  set PYTHONPATH=src
  python scripts/smoke_graph_e2e.py

Or with venv::

  .venv\\Scripts\\python scripts/smoke_graph_e2e.py

Restart the process after changing env files (`get_settings` is cached per process).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_SRC = _ORCH / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kmbl_orchestrator.config import get_settings
from kmbl_orchestrator.graph.app import persist_graph_run_start, run_graph
from kmbl_orchestrator.persistence.repository import InMemoryRepository
from kmbl_orchestrator.roles.invoke import DefaultRoleInvoker

_LOG = logging.getLogger("kmbl.smoke_e2e")


def _log_event(event: str, **fields: object) -> None:
    parts = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields))
    _LOG.info("%s %s", event, parts)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
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
        event_input={"smoke": True, "note": "smoke_graph_e2e"},
    )
    _log_event("smoke_start", thread_id=tid, graph_run_id=gid)

    try:
        final = run_graph(
            repo=repo,
            invoker=invoker,
            settings=settings,
            initial={
                "thread_id": tid,
                "graph_run_id": gid,
                "event_input": {"smoke": True},
            },
        )
    except Exception as e:
        _log_event("smoke_failed", error=repr(e))
        _LOG.exception("graph run failed")
        return 1

    _log_event(
        "smoke_ok",
        decision=final.get("decision"),
        status=final.get("status"),
        iteration_index=final.get("iteration_index"),
    )
    print("decision:", final.get("decision"))
    print("status:", final.get("status"))
    print("build_spec_id:", final.get("build_spec_id"))
    print("evaluation_report:", final.get("evaluation_report"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
