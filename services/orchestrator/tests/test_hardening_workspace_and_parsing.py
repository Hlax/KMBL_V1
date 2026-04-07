"""Tests for the hardening pass: workspace lifecycle, truncation detection, and structured diagnostics."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from kmbl_orchestrator.config import Settings
from kmbl_orchestrator.providers.kiloclaw_parsing import (
    _looks_like_truncated_json,
    _parse_chat_completion_json_content,
    detect_truncation,
)
from kmbl_orchestrator.providers.kiloclaw_protocol import KiloClawInvocationError
from kmbl_orchestrator.runtime.workspace_retention import (
    PARSE_FAIL_MARKER,
    ensure_clean_workspace,
    mark_workspace_parse_failed,
    prune_stale_generator_workspaces,
)


# ---------------------------------------------------------------------------
# A.  Workspace cleanup / lifecycle
# ---------------------------------------------------------------------------


class TestParseFailMarker:
    def test_mark_creates_marker_file(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "thread" / "run"
        mark_workspace_parse_failed(run_dir)
        assert (run_dir / PARSE_FAIL_MARKER).is_file()

    def test_mark_is_idempotent(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "thread" / "run"
        mark_workspace_parse_failed(run_dir)
        mark_workspace_parse_failed(run_dir)
        assert (run_dir / PARSE_FAIL_MARKER).is_file()


class TestEnsureCleanWorkspace:
    def test_creates_dir_when_missing(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "thread" / "run"
        assert not run_dir.exists()
        ensure_clean_workspace(run_dir)
        assert run_dir.is_dir()

    def test_preserves_existing_dir_without_marker(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "file.txt").write_text("keep me")
        ensure_clean_workspace(run_dir)
        assert (run_dir / "file.txt").is_file()

    def test_wipes_dir_with_parse_fail_marker(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "stale.txt").write_text("old residue")
        mark_workspace_parse_failed(run_dir)
        assert (run_dir / PARSE_FAIL_MARKER).is_file()
        ensure_clean_workspace(run_dir)
        assert run_dir.is_dir()
        assert not (run_dir / "stale.txt").exists()
        assert not (run_dir / PARSE_FAIL_MARKER).exists()

    def test_new_run_workspace_isolation(self, tmp_path: Path) -> None:
        """Two distinct run IDs get fully isolated workspaces."""
        root = tmp_path / "ws"
        tid = uuid4()
        run1 = root / str(tid) / str(uuid4())
        run2 = root / str(tid) / str(uuid4())
        ensure_clean_workspace(run1)
        (run1 / "artifact.html").write_text("r1")
        ensure_clean_workspace(run2)
        assert (run1 / "artifact.html").is_file()
        assert not list(run2.iterdir())  # run2 is clean (empty dir)


class TestParseFailed_FastPrune:
    """Parse-failed workspaces are pruned faster (24h default) instead of 14 days."""

    def test_parse_failed_pruned_by_short_retention(self, tmp_path: Path) -> None:
        root = tmp_path / "w"
        tid = uuid4()
        rid = uuid4()
        run_dir = root / str(tid) / str(rid)
        run_dir.mkdir(parents=True)
        mark_workspace_parse_failed(run_dir)
        # Set mtime to 30 hours ago (> 24h default)
        old = time.time() - 30 * 3600
        os.utime(run_dir, (old, old))

        s = Settings.model_construct(
            kmbl_generator_workspace_root=str(root),
            kmbl_generator_workspace_retention_enabled=True,
            kmbl_generator_workspace_retention_min_age_days=14.0,
            kmbl_generator_workspace_parse_fail_retention_hours=24.0,
            kmbl_generator_workspace_debug_retention=False,
        )
        r = prune_stale_generator_workspaces(s, dry_run=False, now=time.time())
        assert str(run_dir) in r.deleted_paths
        assert str(run_dir) in r.deleted_parse_failed
        assert not run_dir.exists()

    def test_parse_failed_not_pruned_if_too_recent(self, tmp_path: Path) -> None:
        root = tmp_path / "w"
        tid = uuid4()
        rid = uuid4()
        run_dir = root / str(tid) / str(rid)
        run_dir.mkdir(parents=True)
        mark_workspace_parse_failed(run_dir)
        # mtime = 1 hour ago (< 24h default)
        recent = time.time() - 1 * 3600
        os.utime(run_dir, (recent, recent))

        s = Settings.model_construct(
            kmbl_generator_workspace_root=str(root),
            kmbl_generator_workspace_retention_enabled=True,
            kmbl_generator_workspace_retention_min_age_days=14.0,
            kmbl_generator_workspace_parse_fail_retention_hours=24.0,
            kmbl_generator_workspace_debug_retention=False,
        )
        r = prune_stale_generator_workspaces(s, dry_run=False, now=time.time())
        assert r.deleted_paths == []
        assert run_dir.is_dir()

    def test_debug_retention_overrides_fast_prune(self, tmp_path: Path) -> None:
        """With debug_retention=True, parse-failed workspaces use the long normal window."""
        root = tmp_path / "w"
        tid = uuid4()
        rid = uuid4()
        run_dir = root / str(tid) / str(rid)
        run_dir.mkdir(parents=True)
        mark_workspace_parse_failed(run_dir)
        old = time.time() - 30 * 3600  # 30 hours old
        os.utime(run_dir, (old, old))

        s = Settings.model_construct(
            kmbl_generator_workspace_root=str(root),
            kmbl_generator_workspace_retention_enabled=True,
            kmbl_generator_workspace_retention_min_age_days=14.0,
            kmbl_generator_workspace_parse_fail_retention_hours=24.0,
            kmbl_generator_workspace_debug_retention=True,
        )
        r = prune_stale_generator_workspaces(s, dry_run=False, now=time.time())
        # 30h < 14 days → still retained because debug_retention is on
        assert r.deleted_paths == []
        assert run_dir.is_dir()

    def test_normal_dir_not_affected_by_fast_prune(self, tmp_path: Path) -> None:
        """Non-parse-failed dirs still use the normal 14-day window."""
        root = tmp_path / "w"
        tid = uuid4()
        rid = uuid4()
        run_dir = root / str(tid) / str(rid)
        run_dir.mkdir(parents=True)
        old = time.time() - 30 * 3600  # 30 hours old (no parse-fail marker)
        os.utime(run_dir, (old, old))

        s = Settings.model_construct(
            kmbl_generator_workspace_root=str(root),
            kmbl_generator_workspace_retention_enabled=True,
            kmbl_generator_workspace_retention_min_age_days=14.0,
            kmbl_generator_workspace_parse_fail_retention_hours=24.0,
            kmbl_generator_workspace_debug_retention=False,
        )
        r = prune_stale_generator_workspaces(s, dry_run=False, now=time.time())
        # 30h < 14 days → still kept for normal dirs
        assert r.deleted_paths == []
        assert run_dir.is_dir()


# ---------------------------------------------------------------------------
# B.  Generator output truncation detection
# ---------------------------------------------------------------------------


class TestTruncationHeuristic:
    def test_balanced_json_not_truncated(self) -> None:
        assert not _looks_like_truncated_json('{"key": "value"}')

    def test_unbalanced_braces_detected(self) -> None:
        assert _looks_like_truncated_json('{"key": {"nested": "val')

    def test_trailing_comma_detected(self) -> None:
        assert _looks_like_truncated_json('{"key": "value",')

    def test_trailing_colon_detected(self) -> None:
        assert _looks_like_truncated_json('{"key":')

    def test_empty_string_not_truncated(self) -> None:
        assert not _looks_like_truncated_json("")

    def test_complete_large_json_not_truncated(self) -> None:
        payload = json.dumps({"items": [{"id": i} for i in range(100)]})
        assert not _looks_like_truncated_json(payload)


class TestDetectTruncation:
    def test_finish_reason_length(self) -> None:
        msg = detect_truncation('{"ok": true}', role_type="generator", finish_reason="length")
        assert msg is not None
        assert "OPENCLAW_CHAT_MAX_TOKENS_GENERATOR" in msg
        assert "truncated" in msg.lower()

    def test_finish_reason_max_tokens(self) -> None:
        msg = detect_truncation('{"ok": true}', role_type="evaluator", finish_reason="max_tokens")
        assert msg is not None
        assert "OPENCLAW_CHAT_MAX_TOKENS_EVALUATOR" in msg

    def test_heuristic_incomplete_json(self) -> None:
        msg = detect_truncation('{"key": {"nested": "val', role_type="generator")
        assert msg is not None
        assert "incomplete" in msg.lower() or "unbalanced" in msg.lower()

    def test_no_truncation_normal(self) -> None:
        msg = detect_truncation('{"key": "value"}', role_type="generator", finish_reason="stop")
        assert msg is None


class TestTruncatedParseProducesSpecificError:
    """A truncated generator payload should raise with error_type='truncated_output'."""

    def test_truncated_json_raises_truncation_error(self) -> None:
        truncated_content = '{"artifact_outputs": [{"role": "static_frontend_file_v1", "content": "<!DOCTYPE html><html><body>'
        data = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": truncated_content},
                    "finish_reason": "length",
                }
            ]
        }
        with pytest.raises(KiloClawInvocationError) as exc_info:
            _parse_chat_completion_json_content(data, role_type="generator")
        assert "truncated" in str(exc_info.value).lower()
        assert exc_info.value.normalized["error_type"] == "truncated_output"
        assert "OPENCLAW_CHAT_MAX_TOKENS_GENERATOR" in exc_info.value.normalized["message"]

    def test_truncated_json_heuristic_only(self) -> None:
        """Truncation detected by heuristic even without finish_reason=length."""
        truncated_content = '{"artifact_outputs": [{"role": "static_frontend_file_v1",'
        data = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": truncated_content},
                    "finish_reason": "stop",
                }
            ]
        }
        with pytest.raises(KiloClawInvocationError) as exc_info:
            _parse_chat_completion_json_content(data, role_type="generator")
        # Should detect via heuristic (trailing comma + unbalanced braces)
        assert exc_info.value.normalized["error_type"] == "truncated_output"


# ---------------------------------------------------------------------------
# C.  Structured diagnostics / fallback scanner logging
# ---------------------------------------------------------------------------


class TestFallbackScannerLogging:
    """Verify structured WARNING logs are emitted when parsing uses recovery paths."""

    def test_multi_object_recovery_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When JSON starts with prose and has multiple objects, recovery should log."""
        # Construct raw text: prose + two JSON objects, second is the role output
        obj1 = json.dumps({"metadata": "ignore"})
        obj2 = json.dumps({"updated_state": {"rev": 1}, "artifact_outputs": []})
        raw = f"Here is the output:\n{obj1}\n{obj2}"
        data = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": raw},
                    "finish_reason": "stop",
                }
            ]
        }
        with caplog.at_level(logging.WARNING, logger="kmbl_orchestrator.providers.kiloclaw_parsing"):
            result = _parse_chat_completion_json_content(data, role_type="generator")
        assert result.get("updated_state") is not None
        # Check that a recovery diagnostic was logged
        assert any("kiloclaw_parsing_recovery" in r.message for r in caplog.records)

    def test_list_root_recovery_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When the model returns a JSON array, recovery should log."""
        items = [{"metadata": "x"}, {"updated_state": {"rev": 1}, "artifact_outputs": []}]
        data = {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(items)},
                    "finish_reason": "stop",
                }
            ]
        }
        with caplog.at_level(logging.WARNING, logger="kmbl_orchestrator.providers.kiloclaw_parsing"):
            result = _parse_chat_completion_json_content(data, role_type="generator")
        assert result.get("updated_state") is not None
        assert any("kiloclaw_parsing_recovery" in r.message for r in caplog.records)
        assert any("list_root_recovery" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# D.  Generator max_tokens config wiring
# ---------------------------------------------------------------------------


class TestGeneratorMaxTokenConfig:
    def test_default_generator_max_tokens_is_16384(self) -> None:
        """Config default for generator max tokens should be 16384."""
        s = Settings.model_construct()
        assert s.openclaw_chat_max_tokens_generator == 16384

    def test_planner_max_tokens_unchanged_at_8192(self) -> None:
        s = Settings.model_construct()
        assert s.openclaw_chat_max_tokens_planner == 8192

    def test_evaluator_max_tokens_unchanged_at_8192(self) -> None:
        s = Settings.model_construct()
        assert s.openclaw_chat_max_tokens_evaluator == 8192


# ---------------------------------------------------------------------------
# E.  Config settings exist and have correct defaults
# ---------------------------------------------------------------------------


class TestHardeningConfigDefaults:
    def test_parse_fail_retention_hours_default(self) -> None:
        s = Settings.model_construct()
        assert s.kmbl_generator_workspace_parse_fail_retention_hours == 24.0

    def test_debug_retention_default_false(self) -> None:
        s = Settings.model_construct()
        assert s.kmbl_generator_workspace_debug_retention is False
