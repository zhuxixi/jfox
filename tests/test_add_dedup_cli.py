"""
测试类型: 集成测试（CLI 子进程）
目标: jfox add permanent 防重端到端（#383）

子进程无 daemon → embedding 通道自动降级，标题通道覆盖主路径。
"""

import pytest

pytestmark = [pytest.mark.integration]


class TestAddDedupCLI:
    def test_title_duplicate_blocked(self, cli):
        r1 = cli._run("add", "第一条内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r1.success
        r2 = cli._run("add", "第二条不同内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r2.returncode == 1
        assert r2.data is not None
        assert r2.data["success"] is False
        assert r2.data["skipped"] == "duplicate"
        assert r2.data["duplicate"]["matched_by"] == "title"
        assert r2.data["duplicate"]["matched_id"] == r1.data["note"]["id"]

    def test_force_bypasses_duplicate(self, cli):
        r1 = cli._run("add", "内容一", "--title", "Dup-Title-F", "--type", "permanent")
        assert r1.success
        r2 = cli._run("add", "内容二", "--title", "Dup-Title-F", "--type", "permanent", "--force")
        assert r2.success
        assert r2.data["success"] is True

    def test_fleeting_not_checked(self, cli):
        cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        r2 = cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        assert r2.success

    def test_different_title_permanent_passes(self, cli):
        cli._run("add", "正文一", "--title", "Dup-Title-H", "--type", "permanent")
        r2 = cli._run("add", "正文二", "--title", "Dup-Title-H2", "--type", "permanent")
        assert r2.success
