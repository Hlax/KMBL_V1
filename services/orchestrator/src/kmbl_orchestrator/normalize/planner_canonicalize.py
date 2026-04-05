"""Canonicalize planner wire JSON before persistence (LLM shape drift vs PlannerRoleOutput)."""

from __future__ import annotations

import copy
from typing import Any


def canonicalize_planner_raw(raw: dict[str, Any]) -> list[str]:
    """
    Mutate ``raw`` in place so top-level keys match the persisted contract.

    - Hoist ``success_criteria`` / ``evaluation_targets`` from ``build_spec`` when top-level empty.
    - Promote ``creative_brief.execution_contract`` to ``build_spec.execution_contract`` when missing.
    - Remove nested duplicates after hoist/promote to avoid contradictory state.

    Returns human-readable fix labels for observability (run events / logs).
    """
    fixes: list[str] = []
    bs = raw.get("build_spec")
    if not isinstance(bs, dict):
        return fixes

    def _top_level_empty(key: str) -> bool:
        v = raw.get(key)
        if v is None:
            return True
        if isinstance(v, list):
            return len(v) == 0
        return False

    # --- success_criteria ---
    if _top_level_empty("success_criteria"):
        nested = bs.get("success_criteria")
        if isinstance(nested, list) and nested:
            raw["success_criteria"] = copy.deepcopy(nested)
            del bs["success_criteria"]
            fixes.append("hoisted_success_criteria_from_build_spec")

    # --- evaluation_targets ---
    if _top_level_empty("evaluation_targets"):
        nested = bs.get("evaluation_targets")
        if isinstance(nested, list) and nested:
            raw["evaluation_targets"] = copy.deepcopy(nested)
            del bs["evaluation_targets"]
            fixes.append("hoisted_evaluation_targets_from_build_spec")

    # --- execution_contract: creative_brief → build_spec ---
    cb = bs.get("creative_brief")
    if isinstance(cb, dict):
        nested_ec = cb.get("execution_contract")
        top_ec = bs.get("execution_contract")
        has_top = isinstance(top_ec, dict) and bool(top_ec)
        if isinstance(nested_ec, dict) and nested_ec:
            if not has_top:
                bs["execution_contract"] = copy.deepcopy(nested_ec)
                del cb["execution_contract"]
                fixes.append("promoted_execution_contract_from_creative_brief")
            else:
                # Top-level wins; drop nested duplicate only.
                del cb["execution_contract"]
                fixes.append("deduped_nested_execution_contract_under_creative_brief")

    return fixes
