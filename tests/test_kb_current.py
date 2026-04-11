"""测试 kb current 命令"""


class TestKBCurrent:
    """测试 kb current 命令"""

    def test_kb_current_json_output(self, cli):
        """测试 JSON 格式输出"""
        result = cli.kb_current()
        assert result.success

        data = result.json()  # 使用 json() 方法
        # 验证必需字段
        assert "name" in data
        assert "path" in data
        assert "description" in data
        assert "total_notes" in data
        assert "by_type" in data
        assert "fleeting" in data["by_type"]
        assert "literature" in data["by_type"]
        assert "permanent" in data["by_type"]
        assert "created" in data
        assert "last_used" in data
        assert data["is_current"] is True

    def test_kb_current_text_output(self, cli):
        """测试文本格式输出"""
        result = cli.kb_current(json_output=False)
        assert result.success

        stdout = result.stdout
        # 验证关键信息在输出中
        assert "Current Knowledge Base" in stdout
        assert "Property" in stdout
        assert "Value" in stdout
        assert "Name" in stdout
        assert "Path" in stdout
        assert "Total Notes" in stdout
        assert "Fleeting" in stdout
        assert "Literature" in stdout
        assert "Permanent" in stdout

    def test_kb_current_after_switch(self, cli):
        """测试切换知识库后显示更新"""
        # 创建第二个知识库
        result = cli.kb_create("kb2", description="Test KB 2")
        assert result.success

        # 切换到 kb2
        result = cli.kb_switch("kb2")
        assert result.success

        # 验证当前是 kb2
        result = cli.kb_current()
        assert result.success

        assert result.json()["name"] == "kb2"
        assert result.json()["description"] == "Test KB 2"

    def test_kb_current_with_notes(self, cli):
        """测试有笔记时的统计正确性"""
        # 添加不同类型笔记
        cli.add("fleeting note", note_type="fleeting")
        cli.add("literature note", note_type="literature")
        cli.add("permanent note", note_type="permanent")

        result = cli.kb_current()
        assert result.success

        data = result.json()
        # 应该至少有这些笔记（可能有其他测试遗留的）
        assert data["total_notes"] >= 3
        assert data["by_type"]["fleeting"] >= 1
        assert data["by_type"]["literature"] >= 1
        assert data["by_type"]["permanent"] >= 1

    def test_kb_current_default_format(self, cli):
        """测试默认输出格式是 JSON"""
        result = cli.kb_current()
        assert result.success

        # 默认应该是 JSON
        data = result.json()
        assert data is not None
        assert "name" in data


class TestKBCurrentIntegration:
    """集成测试"""

    def test_kb_current_in_workflow(self, cli):
        """测试在工作流中使用 kb current"""
        # 场景：Agent 需要确认当前知识库

        # 1. 确认当前知识库
        result = cli.kb_current()
        assert result.success
        result.json()["name"]

        # 2. 执行操作
        cli.add("test note")

        # 3. 验证笔记确实添加到了当前知识库
        result = cli.list()
        assert result.success
        notes = result.json()["notes"]
        assert len(notes) == 1
