"""
Load orchestrator Settings (repo-root .env.local) and run strict RPC validation.

Usage (from repo root):

  cd services/orchestrator
  set PYTHONPATH=src
  python ../../scripts/live_validation_from_settings.py

Does not print secrets.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORCH = REPO / "services" / "orchestrator"


def main() -> int:
    sys.path.insert(0, str(ORCH / "src"))
    os.chdir(ORCH)
    from kmbl_orchestrator.config import Settings  # noqa: E402

    s = Settings()
    url = (s.supabase_url or "").strip()
    key = (s.supabase_service_role_key or "").strip()
    db = (s.supabase_db_url or "").strip()
    if not url or not key:
        print("FAIL: supabase_url / supabase_service_role_key missing in Settings (.env.local)")
        return 2

    env = os.environ.copy()
    env["SUPABASE_URL"] = url
    env["SUPABASE_SERVICE_ROLE_KEY"] = key
    if db:
        env["DATABASE_URL"] = db
        env["SUPABASE_DB_URL"] = db

    script = REPO / "scripts" / "validate_supabase_rpc_live.py"
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ORCH),
        env=env,
        text=True,
    )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
