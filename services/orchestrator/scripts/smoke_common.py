"""
Shared smoke-test flow: health, POST /orchestrator/runs/start, poll, optional detail + staging fetch.

Used by run_full_graph_smoke.py and run_gallery_strip_smoke.py (and ``--preset`` entry).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_ORCH = Path(__file__).resolve().parents[1]


def _ensure_src_path() -> None:
    src = _ORCH / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def print_compact_smoke_summary(
    *,
    preset: str,
    start_body: dict[str, Any],
    final_status: dict[str, Any] | None,
    detail_json: dict[str, Any] | None,
    staging_payload: dict[str, Any] | None,
    base_public: str = "http://localhost:3000",
) -> None:
    """Human-readable block — no huge JSON dumps."""
    print()
    print("========== SMOKE SUMMARY ==========")
    print(f"scenario_preset:     {preset}")
    gid = start_body.get("graph_run_id") or (final_status or {}).get("graph_run_id")
    tid = start_body.get("thread_id") or (final_status or {}).get("thread_id")
    print(f"graph_run_id:        {gid}")
    print(f"thread_id:           {tid}")
    if start_body.get("scenario_preset") is not None:
        print(f"start echo preset:   {start_body.get('scenario_preset')}")

    ei = start_body.get("effective_event_input")
    if isinstance(ei, dict):
        c = ei.get("constraints")
        if isinstance(c, dict) and "deterministic" in c:
            print(f"constraints.deterministic: {c.get('deterministic')}")
        v = ei.get("variation")
        if isinstance(v, dict):
            print("--- variation (from start effective_event_input) ---")
            for k in (
                "run_nonce",
                "variation_seed",
                "theme_variant",
                "subject_variant",
                "layout_variant",
                "tone_variant",
            ):
                if k in v:
                    print(f"  {k}: {v[k]}")

    if final_status:
        print(f"final status:        {final_status.get('status')}")
        st = final_status.get("scenario_tag")
        if st:
            print(f"scenario_tag:        {st}")
        snap = final_status.get("snapshot")
        if isinstance(snap, dict) and snap.get("staging_snapshot_id"):
            print(f"staging (snapshot):  {snap.get('staging_snapshot_id')}")

    sid = None
    if detail_json and isinstance(detail_json.get("associated_outputs"), dict):
        sid = detail_json["associated_outputs"].get("staging_snapshot_id")
    if not sid and final_status:
        snap = final_status.get("snapshot")
        if isinstance(snap, dict):
            sid = snap.get("staging_snapshot_id")
    if sid:
        print(f"staging_snapshot_id: {sid}")
        print(f"review URL path:     /review/staging/{sid}")
        print(f"control-plane (dev): {base_public.rstrip('/')}/review/staging/{sid}")

    _ensure_src_path()
    from kmbl_orchestrator.runtime.scenario_visibility import (
        gallery_strip_visibility_from_staging_payload,
    )

    gv_note: dict[str, Any] | None = None
    if staging_payload:
        gv_note = gallery_strip_visibility_from_staging_payload(staging_payload)
    elif final_status and isinstance(final_status.get("snapshot"), dict):
        # No separate staging GET — cannot derive strip counts without payload
        pass

    print("--- gallery strip (from staging payload if fetched) ---")
    if gv_note:
        print(f"gallery strip detected: {'yes' if gv_note.get('has_gallery_strip') else 'no'}")
        print(f"gallery items:          {gv_note.get('gallery_strip_item_count', 0)}")
        print(f"image artifacts:      {gv_note.get('gallery_image_artifact_count', 0)}")
        print(f"total artifact refs:  {gv_note.get('total_artifact_refs', 0)}")
        print(f"items w/ artifact key:{gv_note.get('gallery_items_with_artifact_key', 0)}")
    else:
        print("(staging payload not fetched — run with smoke_common fetch_staging=True or open review URL)")
    print("====================================")
    print()


def fetch_staging_payload(base: str, staging_snapshot_id: str) -> dict[str, Any] | None:
    r = httpx.get(
        f"{base}/orchestrator/staging/{staging_snapshot_id}",
        timeout=60.0,
    )
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return None
    sp = data.get("snapshot_payload_json")
    return sp if isinstance(sp, dict) else None


def run_smoke_flow(
    *,
    preset: str,
    port: int,
    log_path: Path | None,
    spawn_server: bool,
    keywords_for_log: list[str],
    venv_python: Path | None = None,
    validate_stability: bool = False,
) -> int:
    """
    POST ``{"scenario_preset": preset}``, poll until terminal, print summary.

    If ``spawn_server``, kills port (Windows), starts uvicorn, terminates in finally.
    """
    proc = None
    logf = None
    base = f"http://127.0.0.1:{port}"
    py = venv_python or Path(sys.executable)

    if spawn_server:
        _stop_listener_win(port)
        time.sleep(1.0)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_ORCH / "src")
        env["ORCHESTRATOR_SMOKE_PLANNER_ONLY"] = "false"
        env["ORCHESTRATOR_VERBOSE_LOGS"] = "1"
        if log_path is not None:
            log_path.write_text("", encoding="utf-8")
            logf = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [
                str(py),
                "-m",
                "uvicorn",
                "kmbl_orchestrator.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(_ORCH),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )

    start_body: dict[str, Any] = {}
    final_status: dict[str, Any] | None = None
    detail_json: dict[str, Any] | None = None
    staging_payload: dict[str, Any] | None = None
    poll_status_codes: list[int] = []
    detail_http_status: int | None = None
    staging_fetch_attempted = False
    exit_code = 0

    try:
        for _ in range(60):
            time.sleep(0.5)
            try:
                httpx.get(f"{base}/health", timeout=2.0)
                break
            except Exception:
                continue
        else:
            print("SERVER_FAILED — health check did not succeed", file=sys.stderr)
            return 1

        r = httpx.post(
            f"{base}/orchestrator/runs/start",
            json={"scenario_preset": preset},
            timeout=120.0,
        )
        print("POST_START_STATUS", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1
        start_body = r.json()
        print("POST_START_BODY", json.dumps(start_body)[:2000])
        gid = start_body.get("graph_run_id")
        if not gid:
            return 1

        for _ in range(600):
            time.sleep(1.0)
            s = httpx.get(f"{base}/orchestrator/runs/{gid}", timeout=60.0)
            poll_status_codes.append(s.status_code)
            if s.status_code != 200:
                continue
            final_status = s.json()
            st = final_status.get("status")
            if st in ("completed", "failed"):
                print("RUN_TERMINAL_STATUS", st)
                break
        else:
            print("TIMEOUT_POLL")

        d = httpx.get(f"{base}/orchestrator/runs/{gid}/detail", timeout=60.0)
        detail_http_status = d.status_code
        print("DETAIL_STATUS", d.status_code)
        if d.status_code == 200:
            detail_json = d.json()
            print("DETAIL_JSON", json.dumps(detail_json)[:4000])

        sid = None
        if detail_json and isinstance(detail_json.get("associated_outputs"), dict):
            sid = detail_json["associated_outputs"].get("staging_snapshot_id")
        if not sid and final_status:
            snap = final_status.get("snapshot")
            if isinstance(snap, dict):
                sid = snap.get("staging_snapshot_id")
        if isinstance(sid, str) and sid:
            staging_fetch_attempted = True
            staging_payload = fetch_staging_payload(base, sid)

        print_compact_smoke_summary(
            preset=preset,
            start_body=start_body,
            final_status=final_status,
            detail_json=detail_json,
            staging_payload=staging_payload,
        )

        log_text: str | None = None
        if log_path is not None and log_path.exists() and log_path.stat().st_size > 0:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            print("--- ORDERED_LOG_LINES ---")
            for line in log_text.splitlines():
                if any(k in line for k in keywords_for_log):
                    print(line)

        if validate_stability:
            from smoke_stability import (  # noqa: PLC0415
                evaluate_gallery_stability,
                print_stability_report,
                stability_exit_code,
            )

            st = evaluate_gallery_stability(
                preset=preset,
                start_body=start_body,
                final_status=final_status,
                detail_json=detail_json,
                detail_http_status=detail_http_status,
                staging_payload=staging_payload,
                staging_fetch_attempted=staging_fetch_attempted,
                poll_status_codes=poll_status_codes,
                log_text=log_text,
            )
            print_stability_report(st)
            exit_code = stability_exit_code(st)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if logf is not None:
            logf.close()

    return exit_code


def _stop_listener_win(port: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import subprocess as sp

        r = sp.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"
                f"| Select-Object -Unique",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid > 0:
                    sp.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=30,
                    )
    except Exception:
        pass


def parse_cli_preset() -> tuple[str, int, bool, bool]:
    """Parse ``python -m scripts.foo`` style argv: --preset X --port N --no-server [--validate-stability]."""
    import argparse

    p = argparse.ArgumentParser(description="Graph smoke (shared)")
    p.add_argument(
        "--preset",
        choices=[
            "seeded_local_v1",
            "seeded_gallery_strip_v1",
            "seeded_gallery_strip_varied_v1",
            "kiloclaw_image_only_test_v1",
        ],
        default="seeded_local_v1",
    )
    p.add_argument("--port", type=int, default=int(os.environ.get("ORCHESTRATOR_PORT", "8010")))
    p.add_argument(
        "--no-server",
        action="store_true",
        help="Do not spawn uvicorn (use existing server on --port).",
    )
    p.add_argument(
        "--validate-stability",
        action="store_true",
        help="After run, print gallery stability checklist and exit 1 if stability_check is fail.",
    )
    ns, _rest = p.parse_known_args()
    return ns.preset, ns.port, ns.no_server, ns.validate_stability
