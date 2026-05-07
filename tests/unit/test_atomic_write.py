"""
测试类型: 单元测试
目标模块: jfox.note (_atomic_write 函数)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import os
import tempfile
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.config import ZKConfig
from jfox.models import NoteType
from jfox.note import (
    _atomic_write,
    create_note,
    find_note_file,
    save_note,
    update_note,
)


class TestAtomicWrite:
    """测试 _atomic_write 原子写入"""

    def test_normal_write(self, tmp_path):
        """正常写入：文件内容正确"""
        filepath = tmp_path / "test.md"
        _atomic_write(filepath, "hello world")
        assert filepath.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dir(self, tmp_path):
        """目标目录不存在时自动创建"""
        filepath = tmp_path / "sub" / "dir" / "test.md"
        _atomic_write(filepath, "content")
        assert filepath.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path):
        """覆盖已有文件时内容正确"""
        filepath = tmp_path / "test.md"
        filepath.write_text("old content", encoding="utf-8")
        _atomic_write(filepath, "new content")
        assert filepath.read_text(encoding="utf-8") == "new content"

    def test_no_tmp_file_on_write_failure(self, tmp_path):
        """写入失败时不留临时文件，原文件不受影响"""
        filepath = tmp_path / "test.md"
        filepath.write_text("original", encoding="utf-8")

        # 模拟写入过程中异常
        with patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _atomic_write(filepath, "new content")

        # 原文件不受影响
        assert filepath.read_text(encoding="utf-8") == "original"
        # 无 .tmp 残留
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_no_empty_file_on_crash(self, tmp_path):
        """崩溃后不会产生 0 字节目标文件"""
        filepath = tmp_path / "test.md"
        filepath.write_text("original", encoding="utf-8")

        original_mkstemp = tempfile.mkstemp

        def failing_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            os.write(fd, b"partial")
            os.close(fd)
            raise KeyboardInterrupt

        with patch("tempfile.mkstemp", side_effect=failing_mkstemp):
            with pytest.raises(KeyboardInterrupt):
                _atomic_write(filepath, "new content")

        # 目标文件不受影响
        assert filepath.read_text(encoding="utf-8") == "original"


class TestUpdateNoteAtomic:
    """测试 update_note 使用原子写入"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_note_no_zero_byte_on_failure(
        self, mock_global_config, mock_note_config, tmp_path
    ):
        """update_note 写入失败时不留 0 字节文件"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="Test", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        # 修改内容
        n.content = "modified"

        # 模拟 _atomic_write 失败
        with patch("jfox.note._atomic_write", side_effect=RuntimeError("boom")):
            result = update_note(n, add_to_index=False)

        assert result is False
        # 磁盘上原文件不变
        old_file = find_note_file(cfg, n.id)
        assert old_file is not None
        assert "original" in old_file.read_text(encoding="utf-8")


class TestSaveNoteAtomic:
    """测试 save_note 使用原子写入"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    def test_save_note_uses_atomic_write(self, mock_config, tmp_path):
        """save_note 应通过 _atomic_write 写入"""
        cfg = self._make_config(tmp_path)
        mock_config.notes_dir = cfg.notes_dir

        n = create_note("test content", title="Test", note_type=NoteType.FLEETING)

        with patch("jfox.note._atomic_write", wraps=_atomic_write) as mock_aw:
            save_note(n, add_to_index=False)
            mock_aw.assert_called_once()

        # 验证文件内容正确
        assert n.filepath.exists()
        content = n.filepath.read_text(encoding="utf-8")
        assert "test content" in content

    @patch("jfox.note.config")
    def test_save_note_no_zero_byte_on_failure(self, mock_config, tmp_path):
        """save_note 写入失败时不留 0 字节文件"""
        cfg = self._make_config(tmp_path)
        mock_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="Test", note_type=NoteType.FLEETING)
        n.set_filepath(cfg.notes_dir / "fleeting" / "test.md")

        # 先创建一个有内容的文件
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        n.filepath.write_text("original content", encoding="utf-8")

        # 模拟 _atomic_write 失败
        with patch("jfox.note._atomic_write", side_effect=RuntimeError("boom")):
            result = save_note(n, add_to_index=False)

        assert result is False
        # 原文件不受影响（不会被截断为 0 字节）
        assert n.filepath.read_text(encoding="utf-8") == "original content"
