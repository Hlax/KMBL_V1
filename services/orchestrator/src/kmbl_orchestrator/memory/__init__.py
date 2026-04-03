"""Cross-run memory: typed, explainable preference persistence per identity."""

from kmbl_orchestrator.memory.keys import (
    KEY_AGGREGATE_RUN_OUTCOME,
    KEY_AESTHETIC_TASTE,
    KEY_LIKELY_EXPERIENCE_MODE,
    KEY_PREFERRED_EXPERIENCE_MODE,
    KEY_VISUAL_STYLE_HINTS,
)
from kmbl_orchestrator.memory.models import MemoryReadTrace, MemoryWriteTrace, TasteProfileSummary
from kmbl_orchestrator.memory.ops import (
    append_memory_event,
    load_cross_run_memory_context,
    memory_bias_for_experience_mode,
    maybe_write_identity_derived_memory,
    record_operator_memory_from_publication,
    record_operator_memory_from_staging_approval,
    record_run_outcome_memory,
)

__all__ = [
    "KEY_AGGREGATE_RUN_OUTCOME",
    "KEY_AESTHETIC_TASTE",
    "KEY_LIKELY_EXPERIENCE_MODE",
    "KEY_PREFERRED_EXPERIENCE_MODE",
    "KEY_VISUAL_STYLE_HINTS",
    "MemoryReadTrace",
    "MemoryWriteTrace",
    "TasteProfileSummary",
    "append_memory_event",
    "load_cross_run_memory_context",
    "memory_bias_for_experience_mode",
    "maybe_write_identity_derived_memory",
    "record_operator_memory_from_publication",
    "record_operator_memory_from_staging_approval",
    "record_run_outcome_memory",
]
