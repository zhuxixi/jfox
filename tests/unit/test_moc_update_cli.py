"""jfox moc update 命令测试。"""

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
    """簇含 1/2/3；MOC links 里 99 是死链、2 在簇内、新成员 3。"""
    hub = ClusterMember(id="1", title="Zima Hub", link_degree=10, mean_similarity=0.95)
    two = ClusterMember(id="2", title="Zima CR Flow", link_degree=5, mean_similarity=0.9)
    three = ClusterMember(id="3", title="Zima Gem V2", link_degree=3, mean_similarity=0.85)
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=3, vector=3, vector_orphans=0, bm25=3),
        threshold_sweep=[ThresholdSummary(0.65, 1, 3, 0)],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=3, members=[hub, two, three], hub=hub)],
        ),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def _moc_note():
    """一条 structure 类型 MOC 笔记，links 含死链 99。"""
    return Note(
        id="20260822000001",
        title="Zima Hub MOC",
        content="",
        type=NoteType.STRUCTURE,
        created=dt(2026, 8, 22),
        updated=dt(2026, 8, 22),
        links=["1", "2", "99"],
    )


def _mock_meta():
    """三条 live permanent 的元数据（99 不在 live 集合 → 死链）。"""
    return [
        NoteMeta(id="1", title="Zima Hub", type=NoteType.PERMANENT, tags=["zima"]),
        NoteMeta(id="2", title="Zima CR Flow", type=NoteType.PERMANENT, tags=["zima"]),
        NoteMeta(id="3", title="Zima Gem V2", type=NoteType.PERMANENT, tags=["zima"]),
    ]


def test_moc_update_help_registers_exact_contract():
    result = runner.invoke(app, ["moc", "update", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc update [OPTIONS]" in lines
    assert "重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。" in lines
    assert "--json" in " ".join(lines)


def test_moc_group_help_lists_create_and_update():
    """moc --help 同时列出 create 和 update 命令。"""
    result = runner.invoke(app, ["moc", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "│ create 从诊断主题簇生成 MOC 笔记草稿（dry-run 默认，--yes 落盘）。 │" in lines
    assert "│ update 重扫主题簇，diff 现有 MOC 成员（增补新笔记、摘除死链）。 │" in lines


def test_update_dry_run_shows_diff_json():
    """dry-run JSON 输出 diff：新增 3、摘除死链 99、保留 2。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                with patch(
                    "jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])
                ):
                    result = runner.invoke(app, ["moc", "update", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    updates = payload["updates"]
    assert len(updates) == 1
    first = updates[0]
    assert first["moc_id"] == "20260822000001"
    assert first["moc_title"] == "Zima Hub MOC"
    assert [m["id"] for m in first["add"]] == ["3"]
    assert first["remove"] == ["99"]
    assert first["kept"] == 2
    assert "warning" not in first


def test_update_dry_run_table():
    """dry-run table 输出 diff 行。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                with patch(
                    "jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])
                ):
                    result = runner.invoke(app, ["moc", "update", "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "[20260822000001] Zima Hub MOC" in output
    assert "+ [[Zima Gem V2]] (3)" in output
    assert "- 99 (dead link)" in output


def test_update_skips_moc_with_no_matching_cluster():
    """MOC links 与所有簇成员交集为 0 时跳过并输出 warning。"""
    # 簇只含成员 1，MOC links 全是不相交的 99/88
    hub = ClusterMember(id="1", title="Zima Hub", link_degree=10, mean_similarity=0.95)
    report = MocDiagnoseReport(
        coverage=CoverageReport(filesystem=1, vector=1, vector_orphans=0, bm25=1),
        threshold_sweep=[ThresholdSummary(0.65, 1, 1, 0)],
        suggest=SuggestedReport(
            threshold=0.65,
            clusters=[ClusterSummary(size=1, members=[hub], hub=hub)],
        ),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )
    moc = Note(
        id="20260822000002",
        title="Unmatched MOC",
        content="",
        type=NoteType.STRUCTURE,
        created=dt(2026, 8, 22),
        updated=dt(2026, 8, 22),
        links=["99", "88"],
    )
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=report):
        with patch("jfox.moc.cli.list_notes", return_value=[moc]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                with patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1"}, [])):
                    result = runner.invoke(app, ["moc", "update", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert len(payload["updates"]) == 1
    first = payload["updates"][0]
    assert first["add"] == []
    assert first["remove"] == []
    assert first["kept"] == 0
    assert "no matching cluster" in first["warning"]


def test_update_yes_applies_changes():
    """--yes 应用 diff：调 update_note + backfill + remove_backlinks。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]),
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.update_note") as mock_update,
            patch("jfox.moc.cli.backfill_moc_backlinks") as mock_backfill,
            patch("jfox.moc.cli.remove_moc_backlinks") as mock_remove,
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            mock_update.return_value = True
            with patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])):
                result = runner.invoke(app, ["moc", "update", "--yes", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["applied"] is True
    # update_note 至少调用一次（MOC links 改变后保存）
    assert mock_update.call_count >= 1
    # backfill 收到新增成员 3
    mock_backfill.assert_called_once()
    backfill_args = mock_backfill.call_args[0]
    assert "3" in backfill_args[1]
    # remove_backlinks 收到死链 99
    mock_remove.assert_called_once()
    remove_args = mock_remove.call_args[0]
    assert "99" in remove_args[1]


def test_update_yes_skips_backfill_when_update_fails():
    """update_note 返回 False 时不回填/摘除 backlinks，payload 含 warning。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]),
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.update_note", return_value=False),
            patch("jfox.moc.cli.backfill_moc_backlinks") as mock_backfill,
            patch("jfox.moc.cli.remove_moc_backlinks") as mock_remove,
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            with patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])):
                result = runner.invoke(app, ["moc", "update", "--yes", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["applied"] is False
    first = payload["updates"][0]
    assert "update failed" in first["warning"]
    mock_backfill.assert_not_called()
    mock_remove.assert_not_called()


def test_update_removes_dead_link_missing_from_disk():
    """current link id 在磁盘上不存在（不在 existing_ids）→ 出现在 remove。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                # 99 在磁盘上不存在 → existing_ids 不含 99 → remove 含 99
                with patch(
                    "jfox.moc.cli.verify_members_on_disk",
                    return_value=({"1", "2", "3"}, ["skipped ghost member 99 (...)"]),
                ):
                    result = runner.invoke(app, ["moc", "update", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    first = payload["updates"][0]
    assert "99" in first["remove"]
    assert [m["id"] for m in first["add"]] == ["3"]


def test_update_json_shorthand_matches_format_json():
    """--json 简写与 --format json 输出一致（diff add/remove/kept）。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                with patch(
                    "jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])
                ):
                    result = runner.invoke(app, ["moc", "update", "--json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    first = payload["updates"][0]
    assert first["moc_id"] == "20260822000001"
    assert [m["id"] for m in first["add"]] == ["3"]
    assert first["remove"] == ["99"]
    assert first["kept"] == 2
