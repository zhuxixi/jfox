#!/usr/bin/env python
"""
测试 suggest_links 功能

Issue #16: Add suggest-links command to recommend related notes
Issue #54: 移除 try/except + pytest.skip 模式，使用 fixture 进行真实测试
"""

import pytest

from jfox.config import ZKConfig
from jfox.note import extract_keywords, suggest_links


class TestExtractKeywords:
    """测试关键词提取功能"""

    def test_extract_keywords_basic(self):
        """基本关键词提取"""
        content = "今天学习了 Python 的 async/await 机制，用于并发编程"
        keywords = extract_keywords(content, max_keywords=5)

        assert isinstance(keywords, list)
        assert len(keywords) <= 5
        assert any(
            "python" in kw.lower() or "async" in kw.lower() or "await" in kw.lower()
            for kw in keywords
        )

    def test_extract_keywords_empty(self):
        """空内容应返回空列表"""
        keywords = extract_keywords("", max_keywords=5)
        assert keywords == []

    def test_extract_keywords_short_content(self):
        """短内容处理"""
        keywords = extract_keywords("Hi", max_keywords=5)
        assert isinstance(keywords, list)

    def test_extract_keywords_no_stopwords(self):
        """停用词应被过滤"""
        content = "这个是一个测试，的 了 在 是"
        keywords = extract_keywords(content, max_keywords=10)
        stopwords = ["这个", "一个", "的", "了", "在", "是"]
        for kw in keywords:
            assert kw not in stopwords


@pytest.mark.unit
class TestSuggestLinks:
    """测试 suggest_links 功能，使用 cli_fast fixture 搭建临时知识库"""

    def _setup_notes(self, cli_fast):
        """创建一批测试笔记用于 suggest_links 测试"""
        notes = [
            ("Python 并发编程", "学习 Python 的 async/await 和多线程编程"),
            ("JavaScript 异步编程", "Promise 和 async/await 在 JS 中的使用"),
            ("机器学习入门", "监督学习和非监督学习的基本概念"),
            ("深度学习框架", "PyTorch 和 TensorFlow 的对比分析"),
            ("数据库设计原则", "关系型数据库的范式和索引设计"),
        ]
        for title, content in notes:
            cli_fast.add(content, title=title, note_type="permanent")

    def test_suggest_links_returns_list(self, cli_fast, temp_kb):
        """suggest_links 应返回列表"""
        self._setup_notes(cli_fast)

        cfg = ZKConfig(base_dir=temp_kb)
        result = suggest_links("Python 编程", top_k=5, threshold=0.6, cfg=cfg)
        assert isinstance(result, list)

    def test_suggest_links_structure(self, cli_fast, temp_kb):
        """检查结果结构"""
        self._setup_notes(cli_fast)

        cfg = ZKConfig(base_dir=temp_kb)
        result = suggest_links("Python programming", top_k=3, threshold=0.1, cfg=cfg)

        for item in result:
            assert "id" in item
            assert "title" in item
            assert "type" in item
            assert "score" in item
            assert "match_type" in item
            assert item["match_type"] in ["semantic", "keyword"]
            assert 0 <= item["score"] <= 1

    def test_suggest_links_respects_top_k(self, cli_fast, temp_kb):
        """检查 top_k 参数是否生效"""
        self._setup_notes(cli_fast)

        cfg = ZKConfig(base_dir=temp_kb)
        result = suggest_links("编程学习", top_k=3, threshold=0.1, cfg=cfg)
        assert len(result) <= 3

    def test_suggest_links_respects_threshold(self, cli_fast, temp_kb):
        """检查 threshold 参数是否生效"""
        self._setup_notes(cli_fast)

        cfg = ZKConfig(base_dir=temp_kb)
        result = suggest_links("编程学习", top_k=10, threshold=0.9, cfg=cfg)
        for item in result:
            assert item["score"] >= 0.9

    def test_suggest_links_exclude_ids(self, cli_fast, temp_kb):
        """检查 exclude_ids 参数"""
        self._setup_notes(cli_fast)

        cfg = ZKConfig(base_dir=temp_kb)
        result1 = suggest_links("编程学习", top_k=5, threshold=0.1, cfg=cfg)
        if result1:
            exclude_id = result1[0]["id"]
            result2 = suggest_links(
                "编程学习",
                top_k=5,
                threshold=0.1,
                exclude_ids=[exclude_id],
                cfg=cfg,
            )
            assert exclude_id not in [r["id"] for r in result2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
