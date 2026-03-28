"""
测试断言工具

提供 ZK CLI 专用的断言方法
"""

from typing import Dict, Any, List, Optional


class ZKAssertions:
    """ZK CLI 专用断言工具类"""
    
    @staticmethod
    def assert_success(result, message: Optional[str] = None):
        """
        断言命令执行成功
        
        Args:
            result: CLIResult 对象
            message: 可选的自定义错误消息
        """
        assert result.success, message or f"Command failed with returncode {result.returncode}: {result.stderr}"
    
    @staticmethod
    def assert_failure(result, message: Optional[str] = None):
        """
        断言命令执行失败
        
        Args:
            result: CLIResult 对象
            message: 可选的自定义错误消息
        """
        assert not result.success, message or f"Command should have failed but succeeded: {result.stdout}"
    
    @staticmethod
    def assert_note_exists(cli, note_id: str):
        """
        断言笔记存在
        
        Args:
            cli: ZKCLI 实例
            note_id: 笔记 ID
        """
        result = cli.refs(note_id=note_id)
        assert result.success, f"Failed to get note refs: {result.stderr}"
        assert result.data and result.data.get("note"), f"Note {note_id} not found"
        assert result.data["note"]["id"] == note_id, f"Note ID mismatch: expected {note_id}"
    
    @staticmethod
    def assert_note_count(cli, expected_count: int, note_type: Optional[str] = None):
        """
        断言笔记数量
        
        Args:
            cli: ZKCLI 实例
            expected_count: 期望的笔记数量
            note_type: 可选的笔记类型筛选
        """
        result = cli.status()
        assert result.success, f"Failed to get status: {result.stderr}"
        
        if note_type:
            actual_count = result.data.get("notes", {}).get(note_type, 0)
        else:
            actual_count = result.data.get("total_notes", 0)
        
        assert actual_count == expected_count, f"Expected {expected_count} notes, got {actual_count}"
    
    @staticmethod
    def assert_link_bidirectional(cli, from_id: str, to_id: str):
        """
        断言双向链接正确建立
        
        Args:
            cli: ZKCLI 实例
            from_id: 源笔记 ID
            to_id: 目标笔记 ID
        """
        # 检查正向链接
        from_refs = cli.refs(note_id=from_id)
        assert from_refs.success, f"Failed to get refs for {from_id}"
        
        forward_links = from_refs.data.get("forward_links", [])
        forward_ids = [link.get("id") for link in forward_links]
        assert to_id in forward_ids, f"Forward link from {from_id} to {to_id} not found"
        
        # 检查反向链接
        to_refs = cli.refs(note_id=to_id)
        assert to_refs.success, f"Failed to get refs for {to_id}"
        
        backward_links = to_refs.data.get("backward_links", [])
        backward_ids = [link.get("id") for link in backward_links]
        assert from_id in backward_ids, f"Backlink from {to_id} to {from_id} not found"
    
    @staticmethod
    def assert_search_finds(cli, query: str, expected_note_id: str, top: int = 10):
        """
        断言搜索能找到指定笔记
        
        Args:
            cli: ZKCLI 实例
            query: 搜索查询
            expected_note_id: 期望找到的笔记 ID
            top: 搜索返回数量
        """
        result = cli.search(query, top=top)
        assert result.success, f"Search failed: {result.stderr}"
        
        results = result.data.get("results", [])
        found_ids = [r.get("id") for r in results]
        assert expected_note_id in found_ids, f"Note {expected_note_id} not found in search results for '{query}'"
    
    @staticmethod
    def assert_valid_note_data(note_data: Dict[str, Any], expected_id: Optional[str] = None):
        """
        断言笔记数据格式正确
        
        Args:
            note_data: 笔记数据字典
            expected_id: 可选的期望笔记 ID
        """
        assert "id" in note_data, "Note missing 'id' field"
        assert "title" in note_data, "Note missing 'title' field"
        assert "type" in note_data, "Note missing 'type' field"
        assert "created" in note_data, "Note missing 'created' field"
        assert "updated" in note_data, "Note missing 'updated' field"
        
        if expected_id:
            assert note_data["id"] == expected_id, f"Note ID mismatch: expected {expected_id}, got {note_data['id']}"
    
    @staticmethod
    def assert_has_tags(note_data: Dict[str, Any], expected_tags: List[str]):
        """
        断言笔记包含指定标签
        
        Args:
            note_data: 笔记数据字典
            expected_tags: 期望的标签列表
        """
        actual_tags = note_data.get("tags", [])
        for tag in expected_tags:
            assert tag in actual_tags, f"Tag '{tag}' not found in note tags: {actual_tags}"
    
    @staticmethod
    def assert_graph_stats_valid(stats: Dict[str, Any]):
        """
        断言图谱统计数据有效
        
        Args:
            stats: 图谱统计数据
        """
        assert "nodes" in stats, "Stats missing 'nodes' field"
        assert "edges" in stats, "Stats missing 'edges' field"
        assert "orphans" in stats, "Stats missing 'orphans' field"
        assert "isolated_components" in stats, "Stats missing 'isolated_components' field"
        
        assert stats["nodes"] >= 0, f"Invalid node count: {stats['nodes']}"
        assert stats["edges"] >= 0, f"Invalid edge count: {stats['edges']}"
        assert stats["orphans"] >= 0, f"Invalid orphan count: {stats['orphans']}"


# 便捷函数（无需实例化）
def assert_success(result, message: Optional[str] = None):
    """断言命令执行成功"""
    ZKAssertions.assert_success(result, message)

def assert_failure(result, message: Optional[str] = None):
    """断言命令执行失败"""
    ZKAssertions.assert_failure(result, message)

def assert_note_exists(cli, note_id: str):
    """断言笔记存在"""
    ZKAssertions.assert_note_exists(cli, note_id)

def assert_link_bidirectional(cli, from_id: str, to_id: str):
    """断言双向链接正确建立"""
    ZKAssertions.assert_link_bidirectional(cli, from_id, to_id)
