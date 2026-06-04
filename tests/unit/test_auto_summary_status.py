"""验证 status 命令的进度显示和 JSON 输出"""
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

from jfox.auto_summary import ledger as ledger_module
from jfox.auto_summary.ledger import Ledger, LedgerEntry, SessionStatus
from jfox.global_config import AutoSummaryConfig

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _make_config(**overrides):
    defaults = {
        "enabled": True,
        "interval_minutes": 30,
        "idle_threshold_minutes": 30,
        "target_kb": None,
        "max_per_tick": 5,
        "max_session_size_mb": 10,
        "min_session_size_kb": 5,
        "skip_after_days": 0,
        "claude_timeout_seconds": 120,
        "claude_binary": None,
    }
    defaults.update(overrides)
    return AutoSummaryConfig(**defaults)


def _mock_session_file(session_id: str):
    from jfox.auto_summary.scanner import SessionFile

    return SessionFile(
        session_id=session_id,
        project_dir_name="test-project",
        path=Path(f"/fake/{session_id}.jsonl"),
        mtime=time.time() - 3600,
        size_bytes=5000,
    )


def _make_mock_ledger(sessions: dict | None = None):
    """构造不触发文件 I/O 的 Ledger 实例"""
    led = Ledger.__new__(Ledger)
    led._data = ledger_module._LedgerData(version=1, sessions=sessions or {})
    return led


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class TestProgressJsonOutput:
    """验证 --format json 包含 progress 字段"""

    @patch("jfox.auto_summary.cli.list_session_files")
    @patch("jfox.auto_summary.cli._config")
    def test_progress_field_present(self, mock_config, mock_list):
        """JSON 输出应包含 progress 字段"""
        mock_config.return_value = _make_config()
        mock_list.return_value = [
            _mock_session_file("s1"),
            _mock_session_file("s2"),
            _mock_session_file("s3"),
        ]
        led = _make_mock_ledger()
        with (
            patch("jfox.auto_summary.cli.Ledger", return_value=led),
        ):
            from typer.testing import CliRunner

            from jfox.auto_summary.cli import auto_summary_app

            runner = CliRunner()
            result = runner.invoke(auto_summary_app, ["status", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(_strip_ansi(result.output))
        assert "progress" in data
        assert data["progress"]["total_scannable"] == 3
        assert data["progress"]["pending"] == 3
        assert data["progress"]["success"] == 0

    @patch("jfox.auto_summary.cli.list_session_files")
    @patch("jfox.auto_summary.cli._config")
    def test_progress_counts_match_ledger(self, mock_config, mock_list):
        """progress 中的 success/skipped/failed 应与 ledger 匹配"""
        mock_config.return_value = _make_config()
        mock_list.return_value = [
            _mock_session_file("s1"),  # success
            _mock_session_file("s2"),  # skipped
            _mock_session_file("s3"),  # failed_transient
            _mock_session_file("s4"),  # pending (not in ledger)
        ]
        sessions = {
            "s1": LedgerEntry(
                project="p",
                processed_at="2026-01-01",
                status=SessionStatus.SUCCESS.value,
            ),
            "s2": LedgerEntry(
                project="p",
                processed_at="2026-01-01",
                status=SessionStatus.SKIPPED.value,
            ),
            "s3": LedgerEntry(
                project="p",
                processed_at="2026-01-01",
                status=SessionStatus.FAILED_TRANSIENT.value,
            ),
        }
        led = _make_mock_ledger(sessions)
        with (
            patch("jfox.auto_summary.cli.Ledger", return_value=led),
        ):
            from typer.testing import CliRunner

            from jfox.auto_summary.cli import auto_summary_app

            runner = CliRunner()
            result = runner.invoke(auto_summary_app, ["status", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(_strip_ansi(result.output))
        p = data["progress"]
        assert p["total_scannable"] == 4
        assert p["success"] == 1
        assert p["skipped"] == 1
        assert p["failed"] == 1
        assert p["pending"] == 1
        assert p["percentage"] == 50.0  # (success+skipped)/total = 2/4 = 50%


class TestProgressTableOutput:
    """验证 table 模式输出包含进度表"""

    @patch("jfox.auto_summary.cli.list_session_files")
    @patch("jfox.auto_summary.cli._config")
    def test_table_contains_progress(self, mock_config, mock_list):
        """table 输出应包含进度百分比"""
        mock_config.return_value = _make_config()
        mock_list.return_value = [_mock_session_file("s1")]

        led = _make_mock_ledger()
        with (
            patch("jfox.auto_summary.cli.Ledger", return_value=led),
        ):
            from typer.testing import CliRunner

            from jfox.auto_summary.cli import auto_summary_app

            runner = CliRunner()
            result = runner.invoke(auto_summary_app, ["status"])

        assert result.exit_code == 0
        assert "进度" in result.output
        assert "待处理" in result.output or "pending" in result.output.lower()
