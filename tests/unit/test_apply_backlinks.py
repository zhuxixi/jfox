"""
测试类型: 单元测试
目标功能: note.backlinks_write_needed / note.apply_backlinks（#561 分歧即跳过窄写）
预估耗时: 1-2秒

不依赖真实知识库与 embedding：文件用 tmp_path，find_note_file 与索引走 patch。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from jfox import note as note_module
from jfox.models import Note, NoteType


class TestBacklinksWriteNeeded:
    """backlinks_write_needed 纯函数：目标值与现值（各自排序去重后）是否不同"""

    def test_equal_ignoring_order_and_duplicates(self):
        assert (
            note_module.backlinks_write_needed(["b", "a", "a"], ["x"], ["a", "b"], ["x"]) is False
        )

    def test_both_empty_equal(self):
        assert note_module.backlinks_write_needed([], [], [], []) is False

    def test_links_differ(self):
        assert note_module.backlinks_write_needed(["a"], [], ["a", "b"], []) is True

    def test_backlinks_differ(self):
        assert note_module.backlinks_write_needed([], [], [], ["c"]) is True

    def test_empty_to_nonempty(self):
        assert note_module.backlinks_write_needed([], [], ["a"], []) is True
