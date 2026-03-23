#!/usr/bin/env python
"""
MCP Server 扩展接口测试

测试 Issue #15 新增的方法:
- 知识库管理: kb_list, kb_switch, kb_current
- 引用关系查询: get_backlinks, get_graph_stats, get_orphans
- 高级搜索: search_by_tag, daily_notes, query_semantic_graph
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from zk.mcp_server import ZKMCPHandler


class TestMCPKnowledgeBaseManagement:
    """测试知识库管理接口"""
    
    def test_kb_list_returns_list(self):
        """kb_list 应返回知识库列表"""
        handler = ZKMCPHandler()
        result = handler.kb_list()
        
        assert isinstance(result, list)
        if result:  # 如果有知识库
            kb = result[0]
            assert "name" in kb
            assert "path" in kb
            assert "description" in kb
            assert "total_notes" in kb
            assert "is_current" in kb
    
    def test_kb_current_returns_current_kb(self):
        """kb_current 应返回当前知识库信息"""
        handler = ZKMCPHandler()
        result = handler.kb_current()
        
        # 可能有错误信息（如果没有配置知识库）
        if "error" in result:
            assert result["error"]  # 错误信息非空
        else:
            assert "name" in result
            assert "path" in result
            assert "total_notes" in result
            assert "by_type" in result
    
    def test_kb_switch_nonexistent_kb(self):
        """kb_switch 对不存在的知识库应返回失败"""
        handler = ZKMCPHandler()
        result = handler.kb_switch("nonexistent_kb_xyz")
        
        assert isinstance(result, dict)
        assert "success" in result
        assert result["success"] is False
        assert "message" in result


class TestMCPReferenceQueries:
    """测试引用关系查询接口"""
    
    def test_get_backlinks_nonexistent_note(self):
        """获取不存在笔记的反向链接应返回空列表"""
        handler = ZKMCPHandler()
        result = handler.get_backlinks("nonexistent_id")
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    def test_get_graph_stats_structure(self):
        """get_graph_stats 应返回正确的统计结构"""
        handler = ZKMCPHandler()
        result = handler.get_graph_stats()
        
        assert isinstance(result, dict)
        assert "total_nodes" in result
        assert "total_edges" in result
        assert "avg_degree" in result
        assert "isolated_nodes" in result
        assert "clusters" in result
        
        # 类型检查
        assert isinstance(result["total_nodes"], int)
        assert isinstance(result["total_edges"], int)
        assert isinstance(result["avg_degree"], (int, float))
        assert isinstance(result["isolated_nodes"], int)
        assert isinstance(result["clusters"], int)
    
    def test_get_orphans_returns_list(self):
        """get_orphans 应返回孤立笔记列表"""
        handler = ZKMCPHandler()
        result = handler.get_orphans(limit=10)
        
        assert isinstance(result, list)
        # 列表中的每个元素应有 id, title, type
        for orphan in result:
            assert "id" in orphan
            assert "title" in orphan
            assert "type" in orphan
    
    def test_get_orphans_respects_limit(self):
        """get_orphans 应遵守 limit 参数"""
        handler = ZKMCPHandler()
        result = handler.get_orphans(limit=5)
        
        assert len(result) <= 5


class TestMCPAdvancedSearch:
    """测试高级搜索接口"""
    
    def test_search_by_tag_returns_list(self):
        """search_by_tag 应返回笔记列表"""
        handler = ZKMCPHandler()
        result = handler.search_by_tag("test", limit=10)
        
        assert isinstance(result, list)
        for note in result:
            assert "id" in note
            assert "title" in note
            assert "type" in note
            assert "tags" in note
    
    def test_search_by_tag_respects_limit(self):
        """search_by_tag 应遵守 limit 参数"""
        handler = ZKMCPHandler()
        result = handler.search_by_tag("test", limit=3)
        
        assert len(result) <= 3
    
    def test_daily_notes_today(self):
        """daily_notes 不传参数应返回今天的笔记"""
        handler = ZKMCPHandler()
        result = handler.daily_notes()
        
        assert isinstance(result, list)
        for note in result:
            assert "id" in note
            assert "title" in note
            assert "type" in note
    
    def test_daily_notes_specific_date(self):
        """daily_notes 应支持特定日期"""
        handler = ZKMCPHandler()
        # 使用过去的日期（可能没有笔记）
        result = handler.daily_notes("2024-01-01")
        
        assert isinstance(result, list)
    
    def test_query_semantic_graph_structure(self):
        """query_semantic_graph 应返回增强的搜索结果"""
        handler = ZKMCPHandler()
        result = handler.query_semantic_graph("test query", top_k=3, graph_depth=2)
        
        assert isinstance(result, list)
        # 检查结果结构
        for item in result:
            assert "id" in item
            assert "title" in item
            assert "content" in item
            assert "type" in item
            assert "score" in item
            assert "related_notes" in item
            assert "graph_neighbors" in item


class TestMCPRequestHandling:
    """测试 MCP 请求处理"""
    
    def test_handle_kb_list(self):
        """handle 应正确处理 kb_list 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "kb_list",
            "params": {}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert response["jsonrpc"] == "2.0"
        assert "id" in response
        assert response["id"] == 1
        assert "result" in response
    
    def test_handle_kb_current(self):
        """handle 应正确处理 kb_current 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "kb_current",
            "params": {}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "result" in response or "error" in response
    
    def test_handle_get_graph_stats(self):
        """handle 应正确处理 get_graph_stats 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "get_graph_stats",
            "params": {}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "result" in response
    
    def test_handle_search_by_tag(self):
        """handle 应正确处理 search_by_tag 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "search_by_tag",
            "params": {"tag": "test", "limit": 5}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "result" in response
    
    def test_handle_daily_notes(self):
        """handle 应正确处理 daily_notes 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "daily_notes",
            "params": {"date": "2024-03-20"}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "result" in response
    
    def test_handle_query_semantic_graph(self):
        """handle 应正确处理 query_semantic_graph 请求"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "query_semantic_graph",
            "params": {"query": "test", "top_k": 3, "graph_depth": 2}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "result" in response
    
    def test_handle_unknown_method(self):
        """handle 对未知方法应返回错误"""
        handler = ZKMCPHandler()
        request = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "unknown_method",
            "params": {}
        }
        
        response = handler.handle(request)
        
        assert "jsonrpc" in response
        assert "id" in response
        assert "error" in response
        assert response["error"]["code"] == -32601


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
