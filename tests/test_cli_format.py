"""
CLI --format 参数集成测试

测试 list, search, status, refs, graph, suggest-links 等命令的 --format 支持
"""

import json
import pytest


class TestCLIFormat:
    """CLI 多格式输出测试类"""

    @pytest.fixture
    def sample_notes(self, cli):
        """创建测试笔记"""
        notes = []
        for i in range(3):
            result = cli.add(f"测试内容 {i}", title=f"测试笔记 {i}", note_type="permanent")
            assert result.success
            notes.append(result.data["note"])
        return notes

    # ==========================================================================
    # List 命令测试
    # ==========================================================================
    def test_list_format_json(self, cli, sample_notes):
        """测试 list 命令 --format json"""
        result = cli.run("list", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        # list 命令返回 {"notes": [...], "total": N} 格式
        if isinstance(data, dict) and "notes" in data:
            assert len(data["notes"]) >= 3
            assert data["total"] >= 3
        else:
            assert isinstance(data, list)
            assert len(data) >= 3

    def test_list_format_table(self, cli, sample_notes):
        """测试 list 命令 --format table"""
        result = cli.run("list", "--format", "table")
        
        assert result.success
        # Table 格式应该有表格边框和标题
        assert "ID" in result.stdout or "Title" in result.stdout

    def test_list_format_csv(self, cli, sample_notes):
        """测试 list 命令 --format csv"""
        result = cli.run("list", "--format", "csv")
        
        assert result.success
        lines = result.stdout.strip().split("\n")
        # CSV 应该有表头和数据行
        assert len(lines) >= 4  # header + 3 notes
        assert "," in lines[0]  # CSV 分隔符

    def test_list_format_yaml(self, cli, sample_notes):
        """测试 list 命令 --format yaml"""
        result = cli.run("list", "--format", "yaml")
        
        assert result.success
        # YAML 格式应该有 id: 和 title:
        assert "id:" in result.stdout
        assert "title:" in result.stdout

    def test_list_format_paths(self, cli, sample_notes):
        """测试 list 命令 --format paths"""
        result = cli.run("list", "--format", "paths")
        
        assert result.success
        lines = result.stdout.strip().split("\n")
        # 每行应该是一个路径
        assert len(lines) >= 3
        assert ".md" in result.stdout or "/" in result.stdout

    def test_list_format_tree(self, cli, sample_notes):
        """测试 list 命令 --format tree"""
        result = cli.run("list", "--format", "tree")
        
        assert result.success
        # Tree 格式应该有树形结构
        assert "permanent" in result.stdout or "notes" in result.stdout

    def test_list_json_flag_backward_compat(self, cli, sample_notes):
        """测试 list 命令 --json 向后兼容"""
        result = cli.run("list", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        # list 命令可能返回 dict 或 list 格式
        if isinstance(data, dict):
            assert "notes" in data
        else:
            assert isinstance(data, list)

    def test_list_format_short_flag(self, cli, sample_notes):
        """测试 list 命令 -f 短标志"""
        result = cli.run("list", "-f", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        # list 命令返回 {"notes": [...], "total": N} 格式
        if isinstance(data, dict) and "notes" in data:
            assert len(data["notes"]) >= 3
        else:
            assert isinstance(data, list)

    # ==========================================================================
    # Search 命令测试
    # ==========================================================================
    def test_search_format_json(self, cli, sample_notes):
        """测试 search 命令 --format json"""
        result = cli.run("search", "测试", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        # 搜索结果可能包含 results 或 results/hybrid 字段
        assert "results" in data or "hybrid" in data

    def test_search_format_table(self, cli, sample_notes):
        """测试 search 命令 --format table"""
        result = cli.run("search", "测试", "--format", "table")
        
        assert result.success
        # Table 格式应该有表头
        assert "Score" in result.stdout or "Title" in result.stdout or "测试" in result.stdout

    def test_search_json_flag_backward_compat(self, cli, sample_notes):
        """测试 search 命令 --json 向后兼容"""
        result = cli.run("search", "测试", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "results" in data or "hybrid" in data

    # ==========================================================================
    # Status 命令测试
    # ==========================================================================
    def test_status_format_json(self, cli):
        """测试 status 命令 --format json"""
        result = cli.run("status", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "knowledge_base" in data
        assert "stats" in data
        assert "backend" in data

    def test_status_format_table(self, cli):
        """测试 status 命令 --format table"""
        result = cli.run("status", "--format", "table")
        
        assert result.success
        assert "Knowledge Base Status" in result.stdout or "Base Path" in result.stdout

    def test_status_format_yaml(self, cli):
        """测试 status 命令 --format yaml"""
        result = cli.run("status", "--format", "yaml")
        
        assert result.success
        assert "knowledge_base:" in result.stdout

    def test_status_json_flag_backward_compat(self, cli):
        """测试 status 命令 --json 向后兼容"""
        result = cli.run("status", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "knowledge_base" in data

    # ==========================================================================
    # Refs 命令测试
    # ==========================================================================
    def test_refs_format_json(self, cli, sample_notes):
        """测试 refs 命令 --format json"""
        result = cli.run("refs", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "notes" in data

    def test_refs_format_table(self, cli, sample_notes):
        """测试 refs 命令 --format table"""
        result = cli.run("refs", "--format", "table")
        
        assert result.success
        assert "Note References" in result.stdout or "ID" in result.stdout

    def test_refs_json_flag_backward_compat(self, cli, sample_notes):
        """测试 refs 命令 --json 向后兼容"""
        result = cli.run("refs", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "notes" in data

    def test_refs_note_format_json(self, cli, sample_notes):
        """测试 refs --note 命令 --format json"""
        note_id = sample_notes[0]["id"]
        result = cli.run("refs", "--note", note_id, "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "note" in data
        assert "forward_links" in data
        assert "backward_links" in data

    # ==========================================================================
    # Graph 命令测试
    # ==========================================================================
    def test_graph_stats_format_json(self, cli, sample_notes):
        """测试 graph --stats --format json"""
        result = cli.run("graph", "--stats", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "total_nodes" in data
        assert "total_edges" in data

    def test_graph_stats_format_table(self, cli, sample_notes):
        """测试 graph --stats --format table"""
        result = cli.run("graph", "--stats", "--format", "table")
        
        assert result.success
        assert "Total Notes" in result.stdout or "Knowledge Graph Statistics" in result.stdout

    def test_graph_json_flag_backward_compat(self, cli, sample_notes):
        """测试 graph 命令 --json 向后兼容"""
        result = cli.run("graph", "--stats", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "total_nodes" in data

    # ==========================================================================
    # Suggest-links 命令测试
    # ==========================================================================
    def test_suggest_links_format_json(self, cli, sample_notes):
        """测试 suggest-links 命令 --format json"""
        result = cli.run("suggest-links", "测试内容", "--format", "json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "suggestions" in data
        assert "content" in data

    def test_suggest_links_format_table(self, cli, sample_notes):
        """测试 suggest-links 命令 --format table"""
        result = cli.run("suggest-links", "测试内容", "--format", "table")
        
        assert result.success
        # Table 格式可能有建议列表或"No suggestions"提示
        assert "Suggested" in result.stdout or "No suggestions" in result.stdout or "semantic" in result.stdout

    def test_suggest_links_json_flag_backward_compat(self, cli, sample_notes):
        """测试 suggest-links 命令 --json 向后兼容"""
        result = cli.run("suggest-links", "测试内容", "--json")
        
        assert result.success
        data = json.loads(result.stdout)
        assert "suggestions" in data

    # ==========================================================================
    # 错误处理测试
    # ==========================================================================
    def test_list_invalid_format(self, cli):
        """测试 list 命令无效格式处理"""
        result = cli.run("list", "--format", "invalid")
        
        # 应该失败或显示错误
        assert not result.success or "error" in result.stdout.lower() or "unsupported" in result.stdout.lower()

    def test_search_invalid_format(self, cli):
        """测试 search 命令无效格式处理"""
        result = cli.run("search", "test", "--format", "invalid")
        
        assert not result.success or "error" in result.stdout.lower()

    # ==========================================================================
    # 综合测试
    # ==========================================================================
    def test_all_commands_support_format_flag(self, cli, sample_notes):
        """测试所有命令都支持 --format 标志"""
        commands = [
            ("list", ["--format", "json"]),
            ("search", ["测试", "--format", "json"]),
            ("status", ["--format", "json"]),
            ("refs", ["--format", "json"]),
            ("graph", ["--stats", "--format", "json"]),
            ("suggest-links", ["测试", "--format", "json"]),
        ]
        
        for cmd, args in commands:
            result = cli.run(cmd, *args)
            assert result.success, f"Command '{cmd}' with --format failed: {result.stderr}"
            # 验证输出是有效的 JSON
            try:
                json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail(f"Command '{cmd}' output is not valid JSON: {result.stdout[:100]}")

    def test_json_and_format_json_equivalent(self, cli, sample_notes):
        """测试 --json 和 --format json 输出等效"""
        # list 命令
        result1 = cli.run("list", "--json")
        result2 = cli.run("list", "--format", "json")
        
        assert result1.success and result2.success
        data1 = json.loads(result1.stdout)
        data2 = json.loads(result2.stdout)
        assert len(data1) == len(data2)
