"""
测试类型: 单元测试
目标模块: jfox.note (_atomic_write 函数)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.note import _atomic_write


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
