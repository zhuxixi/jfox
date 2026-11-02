"""suggest_links 语义分支修复回归（issue #583）。

命名约束（关键）：tests/conftest.py 的 pytest_collection_modifyitems 会按
nodeid 关键词自动加标记——semantic/vector/embedding → embedding+very_slow；
search/suggest/query → slow。本文件与所有测试函数名刻意避开这些词，保证被
`-m "not embedding and not slow"`（CI Fast 口径）收集。改名前先看该文件。

接缝：全进程内。temp_kb_registered + use_kb（先切库重置单例）+ 进程内
create_note/save_note（走已 patch 的 384 维 mock 后端）+ 进程内 suggest_links。
mock 后端返回全正随机向量（cosine≈0.75 无区分度），所以只断言量纲与阈值，
不断言「相近/无关」的排序。
"""

import unittest.mock

import pytest
from utils.temp_kb import temp_kb_registered

from jfox import embedding_backend
from jfox.config import use_kb
from jfox.models import NoteType
from jfox.note import create_note, save_note, suggest_links

CORPUS = [
    ("Python 并发编程", "学习 Python 的 async/await 和多线程编程"),
    ("JavaScript 异步编程", "Promise 和 async/await 在 JS 中的使用"),
    ("机器学习入门", "监督学习和非监督学习的基本概念"),
]


@pytest.fixture
def _indexed_kb(mock_embedding_backend):
    """在 patch 下建临时注册库、切库、写入笔记。"""
    with unittest.mock.patch.object(
        embedding_backend, "get_backend", lambda: mock_embedding_backend
    ):
        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                for title, body in CORPUS:
                    note = create_note(content=body, title=title, note_type=NoteType.PERMANENT)
                    assert save_note(note), f"save_note failed for {title}"
                yield kb_name


class TestCosineScale:
    def test_link_scores_use_cosine_scale(self, _indexed_kb):
        """A1：语义分支现在应返回 cosine 量纲（>0.1，RRF 只有 0.016–0.033）。"""
        results = suggest_links("Python 编程", top_k=5, threshold=0.05)
        semantic_items = [r for r in results if r["match_type"] == "semantic"]
        assert semantic_items, "修复后应有 semantic 结果（此前恒为空）"
        for item in semantic_items:
            assert item["score"] > 0.1, f"分数应非 RRF 量级: {item['score']}"
            assert item["score"] <= 1.0

    def test_threshold_filters_cosine_items(self, _indexed_kb):
        """A2：先证低阈值有结果，再证高阈值过滤（防「空集空断言」）。"""
        low = suggest_links("Python 编程", top_k=5, threshold=0.05)
        assert any(r["match_type"] == "semantic" for r in low)

        high = suggest_links("Python 编程", top_k=5, threshold=0.999)
        # 注意：不断言整体为空——keyword 项的准入线是 threshold×0.5，可能仍在
        assert not any(r["match_type"] == "semantic" for r in high)

    def test_missing_backend_degrades_to_keyword(self, _indexed_kb):
        """A3：embedding 不可用时降级不炸，返回 keyword 或空。"""
        from jfox.embedding_backend import EmbedDependencyMissingError

        with unittest.mock.patch.object(
            embedding_backend,
            "get_backend",
            side_effect=EmbedDependencyMissingError("test: no embed"),
        ):
            results = suggest_links("Python 编程", top_k=5, threshold=0.05)
        assert isinstance(results, list)
        assert not any(r["match_type"] == "semantic" for r in results)
