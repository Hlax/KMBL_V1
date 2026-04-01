"""Backward-compatible shim — re-exports from ``graph.nodes_pkg`` submodules.

Each function was originally a closure inside ``build_compiled_graph`` in
``graph/app.py``.  They now live in their own modules under ``graph/nodes_pkg/``
and accept an explicit ``(ctx, state)`` signature so they can be bound via
``functools.partial(fn, ctx)`` at graph-build time.
"""

from kmbl_orchestrator.graph.nodes_pkg.context_hydrator import context_hydrator
from kmbl_orchestrator.graph.nodes_pkg.planner import planner_node
from kmbl_orchestrator.graph.nodes_pkg.generator import generator_node
from kmbl_orchestrator.graph.nodes_pkg.evaluator import evaluator_node
from kmbl_orchestrator.graph.nodes_pkg.decision import decision_router
from kmbl_orchestrator.graph.nodes_pkg.staging import staging_node

__all__ = [
    "context_hydrator",
    "planner_node",
    "generator_node",
    "evaluator_node",
    "decision_router",
    "staging_node",
]
