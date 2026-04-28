"""
测试类型: 集成测试（CLI 层）
目标模块: jfox.cli (list --tag, search --tag)
预估耗时: < 5秒
依赖要求: 不需要 embedding

测试 CLI 层面的 --tag 标签过滤功能
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.fast]


class TestListTagFilterCLI:
    """jfox list --tag CLI 集成测试"""

    def test_list_filter_single_tag(self, cli):
        """单标签过滤"""
        cli.add("Python 编程基础", title="Python 基础", tags=["python", "编程"])
        cli.add("Java 编程入门", title="Java 入门", tags=["java", "编程"])
        cli.add("今日想法", title="想法")

        result = cli.list(tags=["python"])
        assert result.success
        data = result.json()
        assert data["total"] == 1
        assert data["notes"][0]["title"] == "Python 基础"

    def test_list_filter_multiple_tags_and(self, cli):
        """多标签 AND 逻辑"""
        cli.add("Python 编程基础", title="Python 基础", tags=["python", "编程"])
        cli.add("Python 机器学习", title="ML 笔记", tags=["python", "机器学习"])
        cli.add("Java 编程入门", title="Java 入门", tags=["java", "编程"])

        result = cli.list(tags=["python", "编程"])
        assert result.success
        data = result.json()
        assert data["total"] == 1
        assert data["notes"][0]["title"] == "Python 基础"

    def test_list_filter_nonexistent_tag(self, cli):
        """不存在的标签返回空"""
        cli.add("一些内容", title="测试笔记")

        result = cli.list(tags=["nonexistent"])
        assert result.success
        data = result.json()
        assert data["total"] == 0

    def test_list_filter_no_tag(self, cli):
        """不传 --tag 返回全部"""
        cli.add("笔记1", title="笔记1", tags=["tag1"])
        cli.add("笔记2", title="笔记2")

        result = cli.list()
        assert result.success
        data = result.json()
        assert data["total"] == 2


class TestSearchTagFilterCLI:
    """jfox search --tag CLI 集成测试

    注意：search 需要 embedding，标记为 embedding。
    仅在 core/full CI job 中运行。
    """

    pytestmark = [pytest.mark.integration, pytest.mark.embedding]

    def test_search_filter_by_tag(self, cli):
        """search --tag 按标签预过滤"""
        cli.add("Python 编程基础教程", title="Python 基础", tags=["python"])
        cli.add("Java 编程入门教程", title="Java 入门", tags=["java"])

        result = cli.search("编程教程", tags=["python"])
        assert result.success
        data = result.json()
        assert data["total"] >= 1
        for r in data["results"]:
            assert "python" in r.get("metadata", {}).get("tags", "")
