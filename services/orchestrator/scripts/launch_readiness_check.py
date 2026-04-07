#!/usr/bin/env python3
"""
Launch readiness check for the KMBL orchestrator.

Validates critical configuration assumptions before a public/demo launch.
Exits with code 0 if all checks pass, 1 if any check fails or warns.

Run from `services/orchestrator`:

  set PYTHONPATH=src
  python scripts/launch_readiness_check.py

Or with venv:

  .venv\\Scripts\\python scripts/launch_readiness_check.py

The script does NOT perform live KiloClaw or Supabase calls — it checks
env/settings only, so it is safe to run in any environment without side effects.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_SRC = _ORCH / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@dataclass
class CheckResult:
    name: str
    passed: bool
    level: str  # "ok", "warn", "fail"
    message: str
    detail: str = ""


def _check(name: str, passed: bool, fail_msg: str, ok_msg: str, warn: bool = False, detail: str = "") -> CheckResult:
    if passed:
        return CheckResult(name, True, "ok", ok_msg, detail)
    level = "warn" if warn else "fail"
    return CheckResult(name, False, level, fail_msg, detail)


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    try:
        from kmbl_orchestrator.config import get_settings
        get_settings.cache_clear()
        s = get_settings()
    except Exception as e:
        results.append(CheckResult("settings_load", False, "fail", f"Settings failed to load: {e}"))
        return results

    # ── KiloClaw transport ──────────────────────────────────────────────────
    transport = getattr(s, "kiloclaw_transport", None) or ""
    results.append(_check(
        "kiloclaw_transport",
        transport in ("http", "auto"),
        f"KILOCLAW_TRANSPORT={transport!r} — set to 'http' or 'auto' for real calls",
        f"KILOCLAW_TRANSPORT={transport!r}",
        warn=(transport == "stub"),
        detail="stub transport means no real OpenClaw calls will be made",
    ))

    base_url = getattr(s, "kiloclaw_base_url", None) or ""
    results.append(_check(
        "kiloclaw_base_url",
        bool(base_url.strip()),
        "KILOCLAW_BASE_URL is not set — orchestrator cannot reach KiloClaw",
        f"KILOCLAW_BASE_URL={base_url!r}",
    ))

    # ── Supabase persistence ────────────────────────────────────────────────
    supa_url = getattr(s, "supabase_url", None) or ""
    supa_key = getattr(s, "supabase_service_role_key", None) or ""
    results.append(_check(
        "supabase_url",
        bool(supa_url.strip()),
        "SUPABASE_URL is not set — persistence will use in-memory repo (data lost on restart)",
        f"SUPABASE_URL={supa_url[:30]!r}...",
        warn=True,
        detail="in-memory repo is acceptable for smoke/local-only testing",
    ))
    results.append(_check(
        "supabase_service_role_key",
        bool(supa_key.strip()),
        "SUPABASE_SERVICE_ROLE_KEY is not set — no Supabase persistence",
        "SUPABASE_SERVICE_ROLE_KEY is set",
        warn=True,
    ))

    # ── Demo / public mode grounding ────────────────────────────────────────
    pub_base = getattr(s, "orchestrator_public_base_url", None) or ""
    public_base_source = getattr(s, "orchestrator_public_base_source", None) or "not_configured"

    is_demo_mode = bool(pub_base.strip())
    results.append(_check(
        "demo_mode_public_base_url",
        is_demo_mode,
        (
            "KMBL_ORCHESTRATOR_PUBLIC_BASE_URL is not set — evaluator will NOT enforce demo "
            "preview grounding. Evaluations may claim pass without browser-reachable previews. "
            "Set this to a publicly-reachable tunnel URL (cloudflared, ngrok) for honest demo testing."
        ),
        f"KMBL_ORCHESTRATOR_PUBLIC_BASE_URL={pub_base!r} (demo/public mode active)",
        warn=True,
        detail="without this, grounding_only_partial can never be True",
    ))

    if is_demo_mode:
        # Warn if public base looks like localhost (not actually public)
        is_local = any(h in pub_base for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        results.append(_check(
            "demo_mode_public_base_not_localhost",
            not is_local,
            f"KMBL_ORCHESTRATOR_PUBLIC_BASE_URL={pub_base!r} looks like a local address — "
            "the evaluator browser cannot reach this from outside your machine",
            f"KMBL_ORCHESTRATOR_PUBLIC_BASE_URL appears publicly reachable: {pub_base!r}",
        ))

    # ── Smoke contract override ─────────────────────────────────────────────
    smoke_contract = getattr(s, "orchestrator_smoke_contract_evaluator", False)
    results.append(_check(
        "smoke_contract_evaluator_off",
        not smoke_contract,
        "KMBL_ORCHESTRATOR_SMOKE_CONTRACT_EVALUATOR=true — demo grounding is SUPPRESSED. "
        "This is correct for smoke/CI testing but must be off for real demo launches.",
        "orchestrator_smoke_contract_evaluator=False (grounding enforcement active)",
        warn=True,
        detail="smoke_contract bypasses the grounding gate entirely",
    ))

    # ── Evaluator config key ────────────────────────────────────────────────
    eval_key = getattr(s, "openclaw_evaluator_config_key", None) or ""
    results.append(_check(
        "openclaw_evaluator_config_key",
        bool(eval_key.strip()),
        "openclaw_evaluator_config_key is not set",
        f"openclaw_evaluator_config_key={eval_key!r}",
    ))

    planner_key = getattr(s, "openclaw_planner_config_key", None) or ""
    results.append(_check(
        "openclaw_planner_config_key",
        bool(planner_key.strip()),
        "openclaw_planner_config_key is not set",
        f"openclaw_planner_config_key={planner_key!r}",
    ))

    generator_key = getattr(s, "openclaw_generator_config_key", None) or getattr(s, "openclaw_default_config_key", None) or ""
    results.append(_check(
        "openclaw_generator_config_key",
        bool(generator_key.strip()),
        "openclaw generator config key is not set",
        f"generator config key is set",
    ))

    # ── Max iterations ──────────────────────────────────────────────────────
    max_iter = getattr(s, "graph_max_iterations_default", 0)
    results.append(_check(
        "graph_max_iterations",
        int(max_iter) >= 1,
        f"graph_max_iterations_default={max_iter} — must be >= 1 for any iteration to occur",
        f"graph_max_iterations_default={max_iter}",
    ))

    return results


def main() -> int:
    print("KMBL Orchestrator - Launch Readiness Check")
    print("=" * 60)

    results = run_checks()

    fails = [r for r in results if r.level == "fail"]
    warns = [r for r in results if r.level == "warn" and not r.passed]
    oks = [r for r in results if r.level == "ok"]

    for r in results:
        icon = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}.get(r.level, "?   ")
        print(f"  [{icon}] [{r.name}] {r.message}")
        if r.detail:
            print(f"         note: {r.detail}")

    print()
    print(f"  {len(oks)} ok  |  {len(warns)} warn  |  {len(fails)} fail")

    if fails:
        print()
        print("RESULT: NOT READY — fix failing checks before launch.")
        return 1
    if warns:
        print()
        print("RESULT: READY WITH WARNINGS — review warnings above before demo launch.")
        return 0
    print()
    print("RESULT: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
