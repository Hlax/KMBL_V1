"""Demo/public-mode preview grounding contract for the evaluator.

In demo/public runs (``KMBL_ORCHESTRATOR_PUBLIC_BASE_URL`` explicitly configured),
the evaluator must ground its output in a browser-reachable preview.  If this
contract cannot be satisfied the evaluation is explicitly marked degraded so that
downstream consumers (metrics, operator dashboards) can tell the difference between
"evaluated against a real rendered page" and "evaluated against artifacts only".

Key concepts
------------
*demo mode*
    Active when ``orchestrator_public_base_source == "configured"`` — i.e. an
    operator set an explicit public URL (not the local-dev derived fallback).
    In this mode preview grounding is *required*.

*grounding satisfied*
    True only when the evaluator has a browser-reachable preview URL
    (``preview_grounding_mode == "browser_reachable"`` in the resolution dict).

*normalized grounding mode*
    Translates session_staging_links vocabulary into the evaluator-report enum:
    - ``browser``   ← browser_reachable
    - ``snippet``   ← operator_local_only (artifact/spec inspection, no live page)
    - ``manifest``  ← (future: manifest-first offline grounding)
    - ``none``      ← unavailable / unknown

The three new fields written to ``metrics_json``
-----------------------------------------------
``preview_grounding_required : bool``
    True in demo mode; False outside (silent fallback is acceptable).
``preview_grounding_satisfied : bool``
    True when the grounding contract is met.  Always True outside demo mode.
``preview_grounding_fallback_reason : str | None``
    Set only when required=True and satisfied=False.  Describes *why* grounding
    could not be met (e.g. ``private_host_blocked_by_gateway_policy``).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Grounding mode normalisation
# ---------------------------------------------------------------------------

# Maps the preview_grounding_mode values from session_staging_links to the
# canonical evaluator-report enum expected by the grounding contract.
_GROUNDING_MODE_NORMALIZE: dict[str, str] = {
    "browser_reachable": "browser",
    "operator_local_only": "snippet",
    "unavailable": "none",
}


def is_demo_mode_from_resolution(preview_resolution: dict[str, Any]) -> bool:
    """Return True when the orchestrator is running in demo/public mode.

    Demo mode is inferred from the preview resolution dict: it is active whenever
    ``orchestrator_public_base_source`` is ``"configured"`` — meaning an explicit
    public base URL was provided by the operator rather than derived from localhost.
    """
    return preview_resolution.get("orchestrator_public_base_source") == "configured"


def compute_demo_preview_grounding_state(
    preview_resolution: dict[str, Any],
) -> dict[str, Any]:
    """Derive the four grounding-contract fields for the evaluation report.

    This is the *single* authoritative place that determines whether preview
    grounding is required, satisfied, and what mode/reason applies.

    Returns
    -------
    dict with exactly these four keys:

    ``preview_grounding_required : bool``
        True in demo mode; False otherwise (non-demo allows silent fallback).
    ``preview_grounding_satisfied : bool``
        True when the grounding contract is met.
    ``preview_grounding_mode : str``
        Normalised mode: ``browser`` | ``snippet`` | ``manifest`` | ``none``.
    ``preview_grounding_fallback_reason : str | None``
        Reason grounding is not satisfied (only set when required + !satisfied).

    Smoke-contract suppression
    --------------------------
    When ``preview_grounding_reason == "smoke_contract_evaluator"`` the
    function short-circuits to ``required=False`` so local smoke runs are not
    incorrectly penalised even when a public base URL is configured.
    """
    # Smoke contract mode: local payload-only contract run — suppress enforcement.
    if preview_resolution.get("preview_grounding_reason") == "smoke_contract_evaluator":
        return {
            "preview_grounding_required": False,
            "preview_grounding_satisfied": True,
            "preview_grounding_mode": "none",
            "preview_grounding_fallback_reason": "smoke_contract_evaluator",
        }

    demo = is_demo_mode_from_resolution(preview_resolution)
    raw_mode = preview_resolution.get("preview_grounding_mode", "unavailable")
    normalized_mode = _GROUNDING_MODE_NORMALIZE.get(raw_mode, "none")

    # Grounding is required only in demo mode.
    # Grounding is satisfied when not required OR when the mode is browser-reachable.
    required = demo
    satisfied = (not demo) or (normalized_mode == "browser")

    fallback_reason: str | None = None
    if required and not satisfied:
        # Prefer the existing degrade_reason; derive a clear fallback otherwise.
        fallback_reason = (
            preview_resolution.get("preview_grounding_degrade_reason")
            or preview_resolution.get("preview_grounding_reason")
            or "preview_not_browser_reachable"
        )

    return {
        "preview_grounding_required": required,
        "preview_grounding_satisfied": satisfied,
        "preview_grounding_mode": normalized_mode,
        "preview_grounding_fallback_reason": fallback_reason,
    }
