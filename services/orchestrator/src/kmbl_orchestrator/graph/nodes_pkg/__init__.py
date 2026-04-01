"""Graph-node functions — **canonical** package for per-node implementations.

``graph/nodes.py`` re-exports this package for backward compatibility.

Each function accepts ``(ctx, state)`` and is bound via
``functools.partial(fn, ctx)`` at graph-build time in ``graph/app.py``.
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
