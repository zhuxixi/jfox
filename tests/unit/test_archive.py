"""测试类型: 单元测试 / 目标模块: jfox.archive (归档/软删除)"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app
from jfox.config import use_kb
from jfox.models import Note, NoteType
from jfox.note import archive_note, create_note, load_note_by_id, save_note, unarchive_note
from jfox.note_index import NoteIndex

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


class TestArchiveModel:
    """测试 Note 数据模型的归档字段"""

    def test_archived_roundtrip(self):
        """archived 字段可以正确序列化与反序列化"""
        note = create_note(
            content="test content",
            title="Test Note",
            note_type=NoteType.PERMANENT,
        )
        note.archived = True

        md = note.to_markdown()
        assert "archived: true" in md

        restored = Note.from_markdown(md, note.filepath)
        assert restored.archived is True

    def test_unarchived_not_in_frontmatter(self):
        """未归档笔记的 frontmatter 中不包含 archived 字段"""
        note = create_note(
            content="test content",
            title="Test Note",
            note_type=NoteType.PERMANENT,
        )
        note.archived = False

        md = note.to_markdown()
        assert "archived" not in md

        restored = Note.from_markdown(md, note.filepath)
        assert restored.archived is False

    def test_to_dict_includes_archived(self):
        """to_dict 输出包含 archived 字段"""
        note = create_note(
            content="test",
            title="Test",
            note_type=NoteType.PERMANENT,
        )
        note.archived = True
        data = note.to_dict()
        assert data["archived"] is True


class TestNoteIndexArchiveFilter:
    """测试 NoteIndex 对归档状态的过滤"""

    def test_list_meta_archive_filter(self):
        """list_meta 默认排除归档，支持 archived_only 和 include_archived"""
        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                from jfox.config import config as zk_config

                active = create_note("active", title="Active", note_type=NoteType.PERMANENT)
                archived = create_note("archived", title="Archived", note_type=NoteType.PERMANENT)
                archived.archived = True

                save_note(active, add_to_index=False)
                save_note(archived, add_to_index=False)

                idx = NoteIndex(zk_config)
                idx.rebuild()

                assert len(idx.list_meta()) == 1
                assert idx.list_meta()[0].id == active.id

                assert len(idx.list_meta(archived_only=True)) == 1
                assert idx.list_meta(archived_only=True)[0].id == archived.id

                assert len(idx.list_meta(include_archived=True)) == 2


class TestArchiveCommands:
    """测试 archive/unarchive CLI 命令及 list/search 过滤"""

    @staticmethod
    def _kb_args(kb_name, kb_path):
        return ["init", "--name", kb_name, "--path", str(kb_path)]

    @staticmethod
    def _add_args(kb_name, title, content, note_type="permanent"):
        return [
            "add",
            content,
            "--title",
            title,
            "--type",
            note_type,
            "--kb",
            kb_name,
            "--json",
        ]

    def _extract_id(self, output):
        data = json.loads(output)
        return data["note"]["id"]

    def test_archive_and_list_filter(self, temp_kb, mock_embedding_backend):
        """归档后默认 list 隐藏，--archived 和 --include-archived 可查看"""
        kb_name = "test_archive_list"
        with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
            result = runner.invoke(app, self._kb_args(kb_name, temp_kb))
            assert result.exit_code == 0, result.output

            active_result = runner.invoke(
                app, self._add_args(kb_name, "Active Note", "active content")
            )
            assert active_result.exit_code == 0, active_result.output
            active_id = self._extract_id(active_result.output)

            archived_result = runner.invoke(
                app, self._add_args(kb_name, "Archived Note", "archived content")
            )
            assert archived_result.exit_code == 0, archived_result.output
            archived_id = self._extract_id(archived_result.output)

            # 归档
            archive_result = runner.invoke(app, ["archive", archived_id, "--kb", kb_name, "--json"])
            assert archive_result.exit_code == 0, archive_result.output
            assert json.loads(archive_result.output)["archived"] == archived_id

            # 默认 list 只显示活跃笔记
            list_result = runner.invoke(app, ["list", "--kb", kb_name, "--json"])
            assert list_result.exit_code == 0, list_result.output
            list_data = json.loads(list_result.output)
            assert list_data["total"] == 1
            assert list_data["notes"][0]["id"] == active_id

            # --archived 只显示归档笔记
            archived_list = runner.invoke(app, ["list", "--archived", "--kb", kb_name, "--json"])
            assert archived_list.exit_code == 0, archived_list.output
            archived_data = json.loads(archived_list.output)
            assert archived_data["total"] == 1
            assert archived_data["notes"][0]["id"] == archived_id

            # --include-archived 显示全部
            all_list = runner.invoke(app, ["list", "--include-archived", "--kb", kb_name, "--json"])
            assert all_list.exit_code == 0, all_list.output
            all_data = json.loads(all_list.output)
            assert all_data["total"] == 2

            # show 仍可查看归档笔记
            show_result = runner.invoke(app, ["show", archived_id, "--kb", kb_name])
            assert show_result.exit_code == 0, show_result.output
            assert "archived: true" in show_result.output

            # 取消归档
            unarchive_result = runner.invoke(
                app, ["unarchive", archived_id, "--kb", kb_name, "--json"]
            )
            assert unarchive_result.exit_code == 0, unarchive_result.output
            assert json.loads(unarchive_result.output)["unarchived"] == archived_id

            # 默认 list 再次显示两条
            list_after = runner.invoke(app, ["list", "--kb", kb_name, "--json"])
            assert list_after.exit_code == 0, list_after.output
            assert json.loads(list_after.output)["total"] == 2

    def test_search_excludes_archived(self, temp_kb, mock_embedding_backend):
        """搜索默认排除归档笔记，--include-archived 可包含"""
        kb_name = "test_archive_search"
        with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
            result = runner.invoke(app, self._kb_args(kb_name, temp_kb))
            assert result.exit_code == 0, result.output

            active_result = runner.invoke(
                app, self._add_args(kb_name, "Active Alpha", "active alpha content")
            )
            assert active_result.exit_code == 0, active_result.output
            active_id = self._extract_id(active_result.output)

            archived_result = runner.invoke(
                app, self._add_args(kb_name, "Archived Alpha", "archived alpha content")
            )
            assert archived_result.exit_code == 0, archived_result.output
            archived_id = self._extract_id(archived_result.output)

            runner.invoke(app, ["archive", archived_id, "--kb", kb_name, "--json"])

            # 默认 keyword 搜索只返回活跃笔记
            search_result = runner.invoke(
                app,
                [
                    "search",
                    "Alpha",
                    "--mode",
                    "keyword",
                    "--top",
                    "10",
                    "--kb",
                    kb_name,
                    "--json",
                ],
            )
            assert search_result.exit_code == 0, search_result.output
            search_data = json.loads(search_result.output)
            assert search_data["total"] == 1
            assert search_data["results"][0]["id"] == active_id

            # --include-archived 返回两条
            include_result = runner.invoke(
                app,
                [
                    "search",
                    "Alpha",
                    "--mode",
                    "keyword",
                    "--top",
                    "10",
                    "--include-archived",
                    "--kb",
                    kb_name,
                    "--json",
                ],
            )
            assert include_result.exit_code == 0, include_result.output
            include_data = json.loads(include_result.output)
            assert include_data["total"] == 2

    def test_archive_note_functions(self):
        """archive_note / unarchive_note 直接修改文件与状态"""
        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                note = create_note("content", title="Note", note_type=NoteType.PERMANENT)
                save_note(note, add_to_index=False)

                assert archive_note(note.id) is True
                archived = load_note_by_id(note.id)
                assert archived is not None
                assert archived.archived is True
                assert "archived: true" in archived.filepath.read_text(encoding="utf-8")

                assert unarchive_note(note.id) is True
                restored = load_note_by_id(note.id)
                assert restored is not None
                assert restored.archived is False
                assert "archived" not in restored.filepath.read_text(encoding="utf-8")
