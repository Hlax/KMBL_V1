"""Golden-style fixtures for KiloClaw planner wire recovery (nested JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from kmbl_orchestrator.providers.kiloclaw_parsing import _find_planner_contract_dict

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kiloclaw"


def test_nested_planner_fixture_finds_build_spec() -> None:
    raw = json.loads((_FIXTURES / "planner_nested_response.json").read_text(encoding="utf-8"))
    found = _find_planner_contract_dict(raw)
    assert found is not None
    assert isinstance(found.get("build_spec"), dict)
    assert found["build_spec"].get("type") == "kmbl_nested_fixture_v1"
