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
