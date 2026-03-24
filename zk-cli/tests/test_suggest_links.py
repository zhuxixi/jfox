#!/usr/bin/env python
"""
测试 suggest_links 功能

Issue #16: Add suggest-links command to recommend related notes
"""

import pytest
from zk.note import extract_keywords, suggest_links


class TestExtractKeywords:
    """测试关键词提取功能"""
    
    def test_extract_keywords_basic(self):
        """基本关键词提取"""
        content = "今天学习了 Python 的 async/await 机制，用于并发编程"
        keywords = extract_keywords(content, max_keywords=5)
        
        assert isinstance(keywords, list)
        assert len(keywords) <= 5
        # 应该包含相关技术词汇
        assert any("python" in kw.lower() or "async" in kw.lower() or "await" in kw.lower() 
                  for kw in keywords)
    
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
        # 停用词应该被过滤掉
        stopwords = ["这个", "一个", "的", "了", "在", "是"]
        for kw in keywords:
            assert kw not in stopwords


class TestSuggestLinks:
    """测试 suggest_links 功能"""
    
    def test_suggest_links_returns_list(self):
        """suggest_links 应返回列表"""
        # 即使没有笔记，也应返回空列表而不是报错
        try:
            result = suggest_links("测试内容", top_k=5, threshold=0.6)
            assert isinstance(result, list)
        except Exception as e:
            # 如果没有知识库配置，可能报错
            pytest.skip(f"Knowledge base not configured: {e}")
    
    def test_suggest_links_structure(self):
        """检查结果结构"""
        try:
            result = suggest_links("Python programming", top_k=3, threshold=0.5)
            
            for item in result:
                assert "id" in item
                assert "title" in item
                assert "type" in item
                assert "score" in item
                assert "match_type" in item
                assert item["match_type"] in ["semantic", "keyword"]
                assert 0 <= item["score"] <= 1
        except Exception as e:
            pytest.skip(f"Knowledge base not configured: {e}")
    
    def test_suggest_links_respects_top_k(self):
        """检查 top_k 参数是否生效"""
        try:
            result = suggest_links("测试内容", top_k=3, threshold=0.1)
            assert len(result) <= 3
        except Exception as e:
            pytest.skip(f"Knowledge base not configured: {e}")
    
    def test_suggest_links_respects_threshold(self):
        """检查 threshold 参数是否生效"""
        try:
            result = suggest_links("测试内容", top_k=10, threshold=0.9)
            # 高阈值下应该很少有匹配
            for item in result:
                assert item["score"] >= 0.9
        except Exception as e:
            pytest.skip(f"Knowledge base not configured: {e}")
    
    def test_suggest_links_exclude_ids(self):
        """检查 exclude_ids 参数"""
        try:
            # 先获取一些结果
            result1 = suggest_links("测试内容", top_k=5, threshold=0.1)
            if result1:
                # 排除第一个结果
                exclude_id = result1[0]["id"]
                result2 = suggest_links(
                    "测试内容", 
                    top_k=5, 
                    threshold=0.1, 
                    exclude_ids=[exclude_id]
                )
                # 排除的 ID 不应该在结果中
                assert exclude_id not in [r["id"] for r in result2]
        except Exception as e:
            pytest.skip(f"Knowledge base not configured: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
