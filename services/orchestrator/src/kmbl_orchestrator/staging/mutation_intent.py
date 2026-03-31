"""
Staging mutation intent — forward-compatible layer for generator-declared mutation semantics.

CURRENT STATUS: The fallback path is always used in practice because no KiloClaw agent
currently emits _kmbl_mutation_intent or mutation_intent fields. The intent system exists
to allow future generators to declare explicit mutation modes (append, replace, merge, etc.)
without requiring orchestrator code changes.

When a generator starts emitting mutation_intent, this module will transparently activate.
Until then, extract_mutation_intent() returns None and resolve_mutation_plan() uses the
simple fallback (path-keyed merge on patch, full replace on rebuild).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MutationIntent(BaseModel):
    """Normalized mutation intent for working staging application.

    Generators can optionally emit this structure to explicitly declare
    their intent. If absent, fallback logic applies based on update mode.
    """

    mode: Literal[
        "append",
        "replace",
        "merge",
        "remove_stale",
        "rebuild_full",
    ]
    scope: Literal["artifact", "section", "block", "full_surface"] = "artifact"
    target_paths: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    preserve_paths: list[str] = Field(default_factory=list)
    explanation: str = ""


class MutationPlan(BaseModel):
    """Resolved mutation plan combining intent with current state."""

    effective_mode: Literal["patch", "rebuild"]
    intents: list[MutationIntent] = Field(default_factory=list)
    paths_to_add: list[str] = Field(default_factory=list)
    paths_to_replace: list[str] = Field(default_factory=list)
    paths_to_remove: list[str] = Field(default_factory=list)
    paths_to_preserve: list[str] = Field(default_factory=list)
    fallback_used: bool = False


def extract_mutation_intent(
    raw_output: dict[str, Any],
) -> list[MutationIntent] | None:
    """Extract mutation intents from generator output if present.

    Looks for `_kmbl_mutation_intent` or `mutation_intent` in the raw output.
    Returns None if no structured intent is present (fallback logic should apply).
    """
    intent_raw = raw_output.get("_kmbl_mutation_intent") or raw_output.get("mutation_intent")

    if intent_raw is None:
        return None

    if isinstance(intent_raw, dict):
        intent_raw = [intent_raw]

    if not isinstance(intent_raw, list):
        return None

    intents: list[MutationIntent] = []
    for item in intent_raw:
        if not isinstance(item, dict):
            continue
        mode = item.get("mode")
        if mode not in ("append", "replace", "merge", "remove_stale", "rebuild_full"):
            continue
        intents.append(MutationIntent(
            mode=mode,
            scope=item.get("scope", "artifact"),
            target_paths=_extract_string_list(item.get("target_paths")),
            target_roles=_extract_string_list(item.get("target_roles")),
            preserve_paths=_extract_string_list(item.get("preserve_paths")),
            explanation=str(item.get("explanation", "")),
        ))

    return intents if intents else None


def resolve_mutation_plan(
    *,
    update_mode: Literal["patch", "rebuild"],
    intents: list[MutationIntent] | None,
    new_artifact_refs: list[Any],
    existing_artifact_refs: list[Any],
) -> MutationPlan:
    """Resolve a mutation plan from intent and current state.

    If intents are absent, uses fallback logic based on update_mode.
    """
    new_paths = _extract_paths(new_artifact_refs)
    existing_paths = _extract_paths(existing_artifact_refs)

    if intents is None:
        if update_mode == "rebuild":
            return MutationPlan(
                effective_mode="rebuild",
                intents=[],
                paths_to_add=new_paths,
                paths_to_replace=[],
                paths_to_remove=list(existing_paths - set(new_paths)),
                paths_to_preserve=[],
                fallback_used=True,
            )
        else:
            added = set(new_paths) - existing_paths
            replaced = set(new_paths) & existing_paths
            return MutationPlan(
                effective_mode="patch",
                intents=[],
                paths_to_add=list(added),
                paths_to_replace=list(replaced),
                paths_to_remove=[],
                paths_to_preserve=list(existing_paths - set(new_paths)),
                fallback_used=True,
            )

    paths_to_add: set[str] = set()
    paths_to_replace: set[str] = set()
    paths_to_remove: set[str] = set()
    paths_to_preserve: set[str] = set(existing_paths)
    effective_mode = update_mode

    for intent in intents:
        if intent.mode == "rebuild_full":
            effective_mode = "rebuild"
            paths_to_add = set(new_paths)
            paths_to_remove = existing_paths - set(new_paths)
            paths_to_preserve = set()
            break
        elif intent.mode == "append":
            for path in new_paths:
                if path not in existing_paths:
                    paths_to_add.add(path)
        elif intent.mode == "replace":
            targets = set(intent.target_paths) if intent.target_paths else set(new_paths)
            for path in new_paths:
                if path in targets:
                    if path in existing_paths:
                        paths_to_replace.add(path)
                    else:
                        paths_to_add.add(path)
        elif intent.mode == "merge":
            for path in new_paths:
                if path in existing_paths:
                    paths_to_replace.add(path)
                else:
                    paths_to_add.add(path)
        elif intent.mode == "remove_stale":
            for path in intent.target_paths:
                if path in existing_paths:
                    paths_to_remove.add(path)
                    paths_to_preserve.discard(path)

        for path in intent.preserve_paths:
            if path in existing_paths:
                paths_to_preserve.add(path)
                paths_to_remove.discard(path)

    return MutationPlan(
        effective_mode=effective_mode,
        intents=intents,
        paths_to_add=sorted(paths_to_add),
        paths_to_replace=sorted(paths_to_replace),
        paths_to_remove=sorted(paths_to_remove),
        paths_to_preserve=sorted(paths_to_preserve),
        fallback_used=False,
    )


def apply_mutation_plan_to_refs(
    plan: MutationPlan,
    existing_refs: list[Any],
    new_refs: list[Any],
) -> list[Any]:
    """Apply a mutation plan to produce the final artifact refs list.

    This implements the resolved plan's intent on the actual artifact data.
    """
    if plan.effective_mode == "rebuild":
        return list(new_refs)

    by_path: dict[str, Any] = {}

    for ref in existing_refs:
        if not isinstance(ref, dict):
            continue
        path = ref.get("path", "")
        if not path:
            continue
        if path in plan.paths_to_remove:
            continue
        by_path[path] = ref

    for ref in new_refs:
        if not isinstance(ref, dict):
            continue
        path = ref.get("path", "")
        if not path:
            continue
        if path in plan.paths_to_add or path in plan.paths_to_replace:
            by_path[path] = ref

    return list(by_path.values())


def _extract_string_list(value: Any) -> list[str]:
    """Extract a list of strings from a value."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str)]


def _extract_paths(refs: list[Any]) -> set[str]:
    """Extract paths from artifact refs."""
    paths = set()
    for ref in refs:
        if isinstance(ref, dict):
            path = ref.get("path", "")
            if isinstance(path, str) and path.strip():
                paths.add(path.strip())
    return paths
