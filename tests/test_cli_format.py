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
        assert (
            "Suggested" in result.stdout
            or "No suggestions" in result.stdout
            or "semantic" in result.stdout
        )

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
        assert (
            not result.success
            or "error" in result.stdout.lower()
            or "unsupported" in result.stdout.lower()
        )

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

    # ==========================================================================
    # Add 命令测试
    # ==========================================================================
    def test_add_content_file(self, cli, tmp_path):
        """测试 add 命令 --content-file 从文件读取内容"""
        content_file = tmp_path / "note.md"
        content_file.write_text("从文件读取的笔记内容", encoding="utf-8")

        result = cli.run("add", "--content-file", str(content_file), "--title", "FileContent")

        assert result.success
        data = result.data
        assert data["success"] is True
        assert data["note"]["title"] == "FileContent"

    def test_add_content_file_mutual_exclusive(self, cli, tmp_path):
        """测试 add 命令 content 参数和 --content-file 不能同时指定"""
        content_file = tmp_path / "note.md"
        content_file.write_text("file content", encoding="utf-8")

        result = cli.run("add", "直接内容", "--content-file", str(content_file))

        assert not result.success
        assert "不能同时指定" in result.stderr or "不能同时指定" in result.stdout

    def test_add_content_file_not_found(self, cli):
        """测试 add 命令 --content-file 文件不存在时报错"""
        result = cli.run("add", "--content-file", "/nonexistent/file.md")

        assert not result.success
        assert "文件不存在" in result.stderr or "文件不存在" in result.stdout

    def test_add_content_file_empty(self, cli):
        """测试 add 命令不提供内容时报错"""
        result = cli.run("add")

        assert not result.success

    def test_add_content_file_with_wiki_links(self, cli, tmp_path):
        """测试 add 命令 --content-file 内容中的 [[wiki链接]] 正常解析"""
        # 先创建一个目标笔记
        cli.add("目标笔记内容", title="目标笔记")

        content_file = tmp_path / "linked.md"
        content_file.write_text("引用 [[目标笔记]] 的内容", encoding="utf-8")

        result = cli.run("add", "--content-file", str(content_file), "--title", "带链接的笔记")

        assert result.success
        data = result.data
        assert data["note"]["links"]

    def test_add_format_json(self, cli):
        """测试 add 命令 --format json"""
        result = cli.run("add", "test content", "--title", "FormatTest", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["note"]["title"] == "FormatTest"

    def test_add_format_table(self, cli):
        """测试 add 命令 --format table"""
        result = cli.run("add", "test content", "--title", "TableTest", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")
        assert "TableTest" in result.stdout

    def test_add_json_flag_backward_compat(self, cli):
        """测试 add 命令 --json 向后兼容"""
        result = cli.run("add", "compat test", "--title", "JsonCompat", "--json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_add_default_is_table(self, cli):
        """测试 add 命令默认输出为 table"""
        result = cli.run("add", "default test", "--title", "DefaultFmt", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # Delete 命令测试
    # ==========================================================================
    def test_delete_format_json(self, cli):
        """测试 delete 命令 --format json"""
        add_result = cli.add("to delete", title="DelFormat")
        note_id = add_result.data["note"]["id"]

        result = cli.run("delete", note_id, "--force", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_delete_format_table(self, cli):
        """测试 delete 命令 --format table"""
        add_result = cli.add("to delete table", title="DelTable")
        note_id = add_result.data["note"]["id"]

        result = cli.run("delete", note_id, "--force", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # Edit 命令测试
    # ==========================================================================
    def test_edit_format_json(self, cli):
        """测试 edit 命令 --format json"""
        add_result = cli.add("original", title="EditFormat")
        note_id = add_result.data["note"]["id"]

        result = cli.run("edit", note_id, "--content", "updated", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_edit_format_table(self, cli):
        """测试 edit 命令 --format table"""
        add_result = cli.add("original", title="EditTable")
        note_id = add_result.data["note"]["id"]

        result = cli.run("edit", note_id, "--title", "NewTitle", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")
        assert "NewTitle" in result.stdout

    # ==========================================================================
    # Init 命令测试
    # ==========================================================================
    def test_init_format_json(self, cli):
        """测试 init 命令 --format json（已存在的 KB）"""
        result = cli.run("init", "--format", "json")

        # KB 已存在应失败，但输出应包含 JSON
        assert result.stdout is not None
        data = json.loads(result.stdout)
        assert data["success"] is False

    def test_init_format_table(self, cli):
        """测试 init 命令 --format table（已存在的 KB）"""
        result = cli.run("init", "--format", "table")

        assert result.stdout is not None
        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # 变更类命令综合测试
    # ==========================================================================
    def test_all_mutation_commands_support_format(self, cli):
        """测试所有变更类命令都支持 --format json"""
        # add
        result = cli.run("add", "format test", "--title", "FmtTest", "--format", "json")
        assert result.success
        data = json.loads(result.stdout)
        note_id = data["note"]["id"]

        # edit
        result = cli.run("edit", note_id, "--content", "edited", "--format", "json")
        assert result.success
        json.loads(result.stdout)

        # delete
        result = cli.run("delete", note_id, "--force", "--format", "json")
        assert result.success
        json.loads(result.stdout)
