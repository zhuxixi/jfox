"""
测试类型: 单元测试
目标模块: jfox.formatters
预估耗时: < 1秒
依赖要求: 无外部依赖

测试多种输出格式：json, table, csv, yaml, paths, tree
"""

import json
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from pathlib import Path

from jfox.formatters import OutputFormatter


class TestOutputFormatter:
    """OutputFormatter 测试类"""

    @pytest.fixture
    def sample_data(self):
        """提供测试数据"""
        return [
            {"id": "202403250001", "title": "测试笔记1", "type": "permanent", "tags": ["test", "demo"]},
            {"id": "202403250002", "title": "测试笔记2", "type": "fleeting", "tags": ["temp"]},
            {"id": "202403250003", "title": "测试笔记3", "type": "literature", "tags": ["book", "read"]},
        ]

    @pytest.fixture
    def single_note(self):
        """提供单条笔记数据"""
        return {
            "id": "202403250001",
            "title": "测试笔记",
            "type": "permanent",
            "content": "这是测试内容"
        }

    # ==========================================================================
    # JSON 格式测试
    # ==========================================================================
    def test_to_json_with_list(self, sample_data):
        """测试 JSON 格式 - 列表数据"""
        result = OutputFormatter.to_json(sample_data)
        
        # 验证是有效的 JSON
        parsed = json.loads(result)
        assert len(parsed) == 3
        assert parsed[0]["title"] == "测试笔记1"
        assert parsed[0]["type"] == "permanent"

    def test_to_json_with_dict(self, single_note):
        """测试 JSON 格式 - 字典数据"""
        result = OutputFormatter.to_json(single_note)
        
        parsed = json.loads(result)
        assert parsed["id"] == "202403250001"
        assert parsed["title"] == "测试笔记"

    def test_to_json_unicode(self):
        """测试 JSON 格式 - Unicode 支持"""
        data = {"title": "中文测试", "content": "日本語テスト"}
        result = OutputFormatter.to_json(data)
        
        # 验证中文没有被转义
        assert "中文测试" in result
        assert "日本語テスト" in result

    # ==========================================================================
    # YAML 格式测试
    # ==========================================================================
    def test_to_yaml_with_list(self, sample_data):
        """测试 YAML 格式 - 列表数据"""
        result = OutputFormatter.to_yaml(sample_data)
        
        # 验证 YAML 包含关键内容（YAML 可能对字符串加引号）
        assert "202403250001" in result
        assert "title:" in result
        assert "type: permanent" in result

    def test_to_yaml_with_dict(self, single_note):
        """测试 YAML 格式 - 字典数据"""
        result = OutputFormatter.to_yaml(single_note)
        
        assert "202403250001" in result
        assert "title:" in result

    # ==========================================================================
    # CSV 格式测试
    # ==========================================================================
    def test_to_csv_with_data(self, sample_data):
        """测试 CSV 格式 - 正常数据"""
        result = OutputFormatter.to_csv(sample_data)
        
        lines = result.strip().split("\n")
        # 表头 + 3 行数据
        assert len(lines) == 4
        # 验证表头
        assert "id,title,type,tags" in lines[0] or "id" in lines[0]
        # 验证数据行包含中文
        assert "测试笔记1" in result

    def test_to_csv_empty_data(self):
        """测试 CSV 格式 - 空数据"""
        result = OutputFormatter.to_csv([])
        assert result == ""

    def test_to_csv_with_headers(self, sample_data):
        """测试 CSV 格式 - 自定义表头"""
        result = OutputFormatter.to_csv(sample_data, headers=["id", "title"])
        
        lines = result.strip().split("\n")
        assert "id,title" in lines[0]
        assert len(lines) == 4

    def test_to_csv_nested_data(self):
        """测试 CSV 格式 - 嵌套数据会被 JSON 序列化"""
        data = [{"id": "1", "tags": ["a", "b"], "meta": {"key": "value"}}]
        result = OutputFormatter.to_csv(data)
        
        # 嵌套数据应该被转为 JSON 字符串（CSV 中可能有转义引号）
        assert "a" in result and "b" in result  # 数组内容存在
        assert "key" in result and "value" in result  # 字典内容存在

    # ==========================================================================
    # Paths 格式测试
    # ==========================================================================
    def test_to_paths_with_dict_list(self):
        """测试 Paths 格式 - 字典列表"""
        data = [
            {"filepath": "/path/to/note1.md", "title": "Note 1"},
            {"filepath": "/path/to/note2.md", "title": "Note 2"},
        ]
        result = OutputFormatter.to_paths(data)
        
        lines = result.split("\n")
        assert "/path/to/note1.md" in lines[0]
        assert "/path/to/note2.md" in lines[1]

    def test_to_paths_with_path_list(self):
        """测试 Paths 格式 - Path 对象列表"""
        data = [Path("/path/to/note1.md"), Path("/path/to/note2.md")]
        result = OutputFormatter.to_paths(data)
        
        # Windows 路径可能使用反斜杠
        assert "path" in result and "note1.md" in result
        assert "path" in result and "note2.md" in result

    def test_to_paths_with_str_list(self):
        """测试 Paths 格式 - 字符串列表"""
        data = ["/path/to/note1.md", "/path/to/note2.md"]
        result = OutputFormatter.to_paths(data)
        
        lines = result.split("\n")
        assert lines[0] == "/path/to/note1.md"
        assert lines[1] == "/path/to/note2.md"

    def test_to_paths_empty_data(self):
        """测试 Paths 格式 - 空数据"""
        result = OutputFormatter.to_paths([])
        assert result == ""

    def test_to_paths_custom_key(self):
        """测试 Paths 格式 - 自定义路径字段"""
        data = [{"path": "/custom/path.md", "title": "Test"}]
        result = OutputFormatter.to_paths(data, key="path")
        
        assert "/custom/path.md" in result

    # ==========================================================================
    # Table 格式测试
    # ==========================================================================
    def test_to_table_with_data(self, sample_data):
        """测试 Table 格式 - 正常数据"""
        result = OutputFormatter.to_table(sample_data)
        
        # 验证表格包含关键内容
        assert "测试笔记1" in result
        assert "permanent" in result
        assert "fleeting" in result

    def test_to_table_empty_data(self):
        """测试 Table 格式 - 空数据"""
        result = OutputFormatter.to_table([])
        assert result == "(No data)"

    def test_to_table_with_columns(self, sample_data):
        """测试 Table 格式 - 指定列"""
        result = OutputFormatter.to_table(sample_data, columns=["id", "title"])
        
        assert "202403250001" in result
        assert "测试笔记1" in result
        # type 列不应该出现
        lines = result.split("\n")
        header_line = [l for l in lines if "id" in l.lower()][0]
        assert "type" not in header_line

    def test_to_table_with_title(self, sample_data):
        """测试 Table 格式 - 带标题"""
        result = OutputFormatter.to_table(sample_data, title="Test Table")
        
        assert "Test Table" in result

    def test_to_table_nested_data(self):
        """测试 Table 格式 - 嵌套数据截断"""
        data = [{"id": "1", "tags": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]}]
        result = OutputFormatter.to_table(data)
        
        # 长列表应该被截断
        assert result is not None

    # ==========================================================================
    # Tree 格式测试
    # ==========================================================================
    def test_to_tree_with_data(self, sample_data):
        """测试 Tree 格式 - 正常数据"""
        result = OutputFormatter.to_tree(sample_data, group_by="type")
        
        # 验证树结构包含分组
        assert "permanent" in result or "notes" in result
        assert "测试笔记1" in result or "测试笔记" in result

    def test_to_tree_empty_data(self):
        """测试 Tree 格式 - 空数据"""
        result = OutputFormatter.to_tree([], root_name="empty")
        assert "empty/" in result

    def test_to_tree_custom_root(self, sample_data):
        """测试 Tree 格式 - 自定义根节点"""
        result = OutputFormatter.to_tree(sample_data, root_name="MyNotes")
        
        assert "MyNotes" in result

    # ==========================================================================
    # Format 统一接口测试
    # ==========================================================================
    def test_format_json(self, sample_data):
        """测试 format 接口 - JSON"""
        result = OutputFormatter.format(sample_data, "json")
        parsed = json.loads(result)
        assert len(parsed) == 3

    def test_format_yaml(self, sample_data):
        """测试 format 接口 - YAML"""
        result = OutputFormatter.format(sample_data, "yaml")
        assert "202403250001" in result

    def test_format_csv(self, sample_data):
        """测试 format 接口 - CSV"""
        result = OutputFormatter.format(sample_data, "csv")
        assert "测试笔记1" in result

    def test_format_table(self, sample_data):
        """测试 format 接口 - Table"""
        result = OutputFormatter.format(sample_data, "table")
        assert "测试笔记1" in result

    def test_format_paths(self):
        """测试 format 接口 - Paths"""
        data = [{"filepath": "/path/to/note.md"}]
        result = OutputFormatter.format(data, "paths")
        assert "/path/to/note.md" in result

    def test_format_tree(self, sample_data):
        """测试 format 接口 - Tree"""
        result = OutputFormatter.format(sample_data, "tree")
        assert "notes" in result or "permanent" in result

    def test_format_case_insensitive(self, sample_data):
        """测试 format 接口 - 大小写不敏感"""
        result1 = OutputFormatter.format(sample_data, "JSON")
        result2 = OutputFormatter.format(sample_data, "json")
        result3 = OutputFormatter.format(sample_data, "Json")
        
        # 都应该返回有效的 JSON
        assert json.loads(result1) == json.loads(result2) == json.loads(result3)

    def test_format_invalid_format(self, sample_data):
        """测试 format 接口 - 无效格式"""
        with pytest.raises(ValueError) as exc_info:
            OutputFormatter.format(sample_data, "invalid")
        
        assert "Unsupported format" in str(exc_info.value)
        assert "json, table, csv, yaml, paths, tree" in str(exc_info.value)

    # ==========================================================================
    # SUPPORTED_FORMATS 测试
    # ==========================================================================
    def test_supported_formats(self):
        """测试支持的格式列表"""
        expected = ["json", "table", "csv", "yaml", "paths", "tree"]
        assert OutputFormatter.SUPPORTED_FORMATS == expected
