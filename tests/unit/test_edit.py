"""
测试类型: 单元测试
目标模块: jfox.note (update_note 函数)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from jfox.models import Note, NoteType
from jfox.note import update_note, create_note, save_note, load_note_by_id
from jfox.config import ZKConfig


class TestUpdateNote:
    """测试 update_note 函数"""

    def _make_config(self, tmp_path):
        """创建临时配置"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_content_preserves_id_and_created(
        self, mock_global_config, mock_note_config, tmp_path
    ):
        """更新内容时保留 ID 和创建时间"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建笔记
        n = create_note("original content", title="Test", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        original_id = n.id
        original_created = n.created

        # 更新内容
        n.content = "updated content"
        updated = update_note(n, add_to_index=False)

        assert updated is True
        # 重新加载验证
        loaded = load_note_by_id(original_id, cfg=cfg)
        assert loaded is not None
        assert loaded.id == original_id
        assert loaded.created == original_created
        assert loaded.content == "updated content"
        assert loaded.updated > original_created

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_title_renames_file(
        self, mock_global_config, mock_note_config, tmp_path
    ):
        """更新标题时重命名文件"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="Old Title", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        # 记录旧路径
        old_filepath = n.filepath
        assert old_filepath.exists()

        # 修改标题
        n.title = "New Title"

        updated = update_note(n, add_to_index=False)
        assert updated is True

        # 旧文件应该不存在
        assert not old_filepath.exists()
        # 新文件应该存在
        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.title == "New Title"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_tags(self, mock_global_config, mock_note_config, tmp_path):
        """更新标签"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note(
            "content", title="Test", note_type=NoteType.PERMANENT, tags=["old"]
        )
        save_note(n, add_to_index=False)

        n.tags = ["new1", "new2"]
        updated = update_note(n, add_to_index=False)
        assert updated is True

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded.tags == ["new1", "new2"]

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_nonexistent_note_returns_false(
        self, mock_global_config, mock_note_config, tmp_path
    ):
        """更新不存在的笔记返回 False"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="Ghost", note_type=NoteType.PERMANENT)
        # 不调用 save_note，文件不存在

        updated = update_note(n, add_to_index=False)
        assert updated is False


class TestEditImpl:
    """测试 _edit_impl 内部实现"""

    def _make_config(self, tmp_path):
        """创建临时配置"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content(self, mock_global_config, mock_note_config, tmp_path):
        """通过 --content 编辑笔记内容"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建笔记
        n = create_note("original", title="EditMe", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="updated content",
            title=None,
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.content == "updated content"
        assert loaded.id == n.id
        assert loaded.title == "EditMe"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_title(self, mock_global_config, mock_note_config, tmp_path):
        """编辑笔记标题"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="OldTitle", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content=None,
            title="NewTitle",
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.title == "NewTitle"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_multiple_fields(self, mock_global_config, mock_note_config, tmp_path):
        """同时编辑多个字段"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("old content", title="Old", note_type=NoteType.LITERATURE, tags=["a"])
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="new content",
            title="New Title",
            tags=["x", "y"],
            note_type="permanent",
            source="book",
            json_output=True,
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.content == "new content"
        assert loaded.title == "New Title"
        assert loaded.tags == ["x", "y"]
        assert loaded.type == NoteType.PERMANENT
        assert loaded.source == "book"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_nonexistent_note_raises(self, mock_global_config, mock_note_config, tmp_path):
        """编辑不存在的笔记抛出异常"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        with pytest.raises(ValueError, match="笔记不存在"):
            _edit_impl(
                note_id="9999999999999999",
                content="x",
                title=None,
                tags=None,
                note_type=None,
                source=None,
                json_output=True,
            )

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_no_fields_specified_raises(self, mock_global_config, mock_note_config, tmp_path):
        """未指定任何编辑字段时抛出异常"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="NoEdit", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        with pytest.raises(ValueError, match="至少指定一个"):
            _edit_impl(
                note_id=n.id,
                content=None,
                title=None,
                tags=None,
                note_type=None,
                source=None,
                json_output=True,
            )

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_with_wiki_links_resolves(self, mock_global_config, mock_note_config, tmp_path):
        """编辑内容中的 [[链接]] 被解析"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建目标笔记
        target = create_note("target note", title="TargetNote", note_type=NoteType.PERMANENT)
        save_note(target, add_to_index=False)

        # 创建源笔记
        source = create_note("source note", title="SourceNote", note_type=NoteType.PERMANENT)
        save_note(source, add_to_index=False)

        # 编辑源笔记，添加 wiki link
        _edit_impl(
            note_id=source.id,
            content="see [[TargetNote]] for details",
            title=None,
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(source.id, cfg=cfg)
        assert loaded is not None
        assert target.id in loaded.links

        # 验证反向链接
        target_loaded = load_note_by_id(target.id, cfg=cfg)
        assert target_loaded is not None
        assert source.id in target_loaded.backlinks

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_removes_backlink_when_link_removed(self, mock_global_config, mock_note_config, tmp_path):
        """编辑内容移除 [[链接]] 时，反向链接也被移除"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建目标笔记
        target = create_note("target note", title="TargetNote", note_type=NoteType.PERMANENT)
        save_note(target, add_to_index=False)

        # 创建源笔记，带链接
        source = create_note(
            "see [[TargetNote]] for details",
            title="SourceNote",
            note_type=NoteType.PERMANENT,
            links=[target.id],
        )
        save_note(source, add_to_index=False)

        # 给目标笔记添加反向链接
        target.backlinks.append(source.id)
        save_note(target, add_to_index=False)

        # 编辑源笔记，移除链接
        _edit_impl(
            note_id=source.id,
            content="no more links here",
            title=None,
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(source.id, cfg=cfg)
        assert loaded is not None
        assert target.id not in loaded.links

        # 验证反向链接也被移除
        target_loaded = load_note_by_id(target.id, cfg=cfg)
        assert target_loaded is not None
        assert source.id not in target_loaded.backlinks

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_type_changes_directory(self, mock_global_config, mock_note_config, tmp_path):
        """编辑笔记类型时文件移动到新目录"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建 literature 笔记
        n = create_note("some content", title="DirMove", note_type=NoteType.LITERATURE)
        save_note(n, add_to_index=False)

        old_filepath = load_note_by_id(n.id, cfg=cfg).filepath
        assert old_filepath.exists()
        assert "literature" in str(old_filepath)

        # 修改类型为 permanent
        _edit_impl(
            note_id=n.id,
            content=None,
            title=None,
            tags=None,
            note_type="permanent",
            source=None,
            json_output=True,
        )

        # 旧文件应该不存在
        assert not old_filepath.exists()

        # 新文件应该在 permanent 目录
        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.type == NoteType.PERMANENT
        assert "permanent" in str(loaded.filepath)
        assert loaded.filepath.exists()
