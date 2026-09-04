"""jfox moc create 命令测试。"""

from __future__ import annotations

import json
import re
from datetime import datetime as dt
from unittest.mock import patch

from typer.testing import CliRunner

from jfox.cli import app
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseReport,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)
from jfox.models import Note, NoteType
from jfox.note_index import NoteMeta

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _help_lines(output: str) -> list[str]:
    return [" ".join(_strip_ansi(line).split()) for line in output.splitlines() if line.strip()]


def _report() -> MocDiagnoseReport:
    hub = ClusterMember(id="1", title="Zima Hub", link_degree=10, mean_similarity=0.95)
    member = ClusterMember(id="2", title="Zima CR Flow", link_degree=5, mean_similarity=0.9)
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=2, vector=2, vector_orphans=0, bm25=2),
        threshold_sweep=[ThresholdSummary(0.65, 1, 2, 0)],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=2, members=[hub, member], hub=hub)],
        ),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def _mock_meta():
    return [
        NoteMeta(id="1", title="Zima Hub", type=NoteType.PERMANENT, tags=["zima"]),
        NoteMeta(id="2", title="Zima CR Flow", type=NoteType.PERMANENT, tags=["zima", "cr"]),
    ]


def test_moc_create_help_registers_exact_contract():
    result = runner.invoke(app, ["moc", "create", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc create [OPTIONS]" in lines
    assert "从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。" in lines
    assert "--max-size" in " ".join(lines)
    assert "--include-orphans" in " ".join(lines)
    assert "--json" in " ".join(lines)


def test_moc_group_help_lists_create_and_update():
    """moc --help 同时列出 create 和 update 命令。"""
    result = runner.invoke(app, ["moc", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "│ create 从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。 │" in lines
    assert "│ update 重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。 │" in lines


def test_create_dry_run_prints_draft_without_writing():
    """dry-run 输出草稿预览，不落盘。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index:
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            with patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])):
                result = runner.invoke(app, ["moc", "create", "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "Cluster size 2; hub: Zima Hub" in output
    assert "MOC title: Zima Hub MOC" in output
    assert "## zima" in output
    assert "- [[1|Zima Hub]] — 10 links" in output


def test_create_yes_writes_moc():
    """--yes 调用 write_moc 落盘，JSON 输出含 created.id。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.write_moc") as mock_write,
            patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])),
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=dt(2026, 8, 22),
                updated=dt(2026, 8, 22),
            )
            mock_write.return_value = fake_moc
            result = runner.invoke(app, ["moc", "create", "--yes", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["created"]["id"] == "20260822000001"
    assert mock_write.call_count == 1


def test_create_yes_table_shows_confirmation():
    """table 模式 --yes 落盘后输出 Created MOC 确认行。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.write_moc") as mock_write,
            patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])),
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=dt(2026, 8, 22),
                updated=dt(2026, 8, 22),
            )
            fake_moc.set_filepath(__import__("pathlib").Path("/tmp/fake-moc.md"))
            mock_write.return_value = fake_moc
            result = runner.invoke(app, ["moc", "create", "--yes", "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    # 路径断言不做分隔符假设（Windows 为反斜杠），只断言确认行与 id/路径出现
    assert "Created MOC 20260822000001 at" in output
    assert str(fake_moc.filepath) in output


def test_create_rejects_oversized_cluster():
    """簇 size 超过 --max-size 时拒绝生成，输出错误。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index:
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            with patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])):
                result = runner.invoke(
                    app, ["moc", "create", "--max-size", "1", "--format", "json"]
                )

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is False
    assert "exceeds --max-size" in payload["error"]


def test_create_dry_run_shows_ghost_warnings_in_table():
    """table 模式下 ghost 成员的 warning 行可见。"""
    ghost_warning = "skipped ghost member 2 (Zima CR Flow)"
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index:
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            with patch(
                "jfox.moc.cli.verify_members_on_disk", return_value=({"1"}, [ghost_warning])
            ):
                result = runner.invoke(app, ["moc", "create", "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert f"Warning: {ghost_warning}" in output


def test_create_dry_run_shows_ghost_warnings_in_json():
    """JSON 模式下 ghost 成员的 warning 进 payload.warnings。"""
    ghost_warning = "skipped ghost member 2 (Zima CR Flow)"
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.get_note_index") as mock_index:
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            with patch(
                "jfox.moc.cli.verify_members_on_disk", return_value=({"1"}, [ghost_warning])
            ):
                result = runner.invoke(app, ["moc", "create", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert ghost_warning in payload["warnings"]


def test_create_json_shorthand_matches_format_json():
    """--json 简写与 --format json 输出一致（含 created 字段）。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.write_moc") as mock_write,
            patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])),
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=dt(2026, 8, 22),
                updated=dt(2026, 8, 22),
            )
            mock_write.return_value = fake_moc
            result = runner.invoke(app, ["moc", "create", "--yes", "--json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["created"]["id"] == "20260822000001"
    assert mock_write.call_count == 1
