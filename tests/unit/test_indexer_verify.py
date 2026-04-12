"""
测试 indexer.verify_index 的 ID 提取逻辑

Issue #103: index verify 误报 missing/orphaned（文件名 slug 与索引 ID 不匹配）
"""

import pytest

from jfox.indexer import _extract_note_id_from_filename


class TestExtractNoteIdFromFilename:
    """从文件名 stem 提取笔记纯 ID 的单元测试"""

    def test_fleeting_filename(self):
        """Fleeting: YYYYMMDD-HHMMSSNNNN → YYYYMMDDHHMMSSNNNN"""
        assert _extract_note_id_from_filename("20260412-0150293323") == "202604120150293323"

    def test_literature_filename_with_chinese_slug(self):
        """Literature/Permanent: ID-中英文slug → ID"""
        assert (
            _extract_note_id_from_filename("202604120150293323-jfox-迭代历史")
            == "202604120150293323"
        )

    def test_permanent_filename_with_english_slug(self):
        """Permanent: ID-english-slug → ID"""
        assert (
            _extract_note_id_from_filename("202604120150293323-some-english-slug")
            == "202604120150293323"
        )

    def test_pure_id_no_slug(self):
        """向后兼容：纯 ID（无 slug）也正确提取"""
        assert _extract_note_id_from_filename("202604120150293323") == "202604120150293323"

    def test_empty_slug(self):
        """ID 后紧跟连字符但无 slug 内容"""
        assert _extract_note_id_from_filename("202604120150293323-") == "202604120150293323"

    def test_invalid_filename_returns_none(self):
        """非笔记文件名返回 None"""
        assert _extract_note_id_from_filename("readme") is None

    def test_random_filename_returns_none(self):
        """不含数字的文件名返回 None"""
        assert _extract_note_id_from_filename("notes") is None

    def test_partial_digits_returns_none(self):
        """不足 18 位的数字不匹配"""
        assert _extract_note_id_from_filename("20260412") is None

    def test_fleeting_wrong_dash_position_returns_none(self):
        """Fleeting 格式连字符不在第 8 位时不应匹配"""
        assert _extract_note_id_from_filename("202604-12015029323") is None