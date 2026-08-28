"""
测试类型: 单元测试
目标功能: jfox delete 入链保护（issue #435 delete guard）
预估耗时: < 2秒
依赖要求: 临时知识库，mock embedding backend

删除被引用笔记前必须显式决策：默认拒绝并提示 redirect 迁移，
--allow-dangling 才放行。redirect 迁移后删除应畅通。
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


def _add(runner, kb_name, title, content):
    """创建笔记并返回 (exit_code, note_id, output)"""
    result = runner.invoke(
        app,
        [
            "add",
            content,
            "--title",
            title,
            "--type",
            "permanent",
            "--kb",
            kb_name,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["note"]["id"]


def _show(runner, kb_name, note_id):
    shown = runner.invoke(app, ["show", note_id, "--kb", kb_name, "--json"])
    assert shown.exit_code == 0, shown.output
    return json.loads(shown.output)


class TestDeleteGuard:
    """delete 命令的入链保护"""

    def test_delete_blocked_when_referenced(self, mock_embedding_backend):
        """被引用笔记默认拒绝删除，错误信息指向 redirect"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                b_id = _add(runner, kb_name, "笔记B", "B body")
                _add(runner, kb_name, "笔记A", "A 引用 [[笔记B]]")

                result = runner.invoke(app, ["delete", b_id, "--force", "--kb", kb_name, "--json"])

                assert result.exit_code == 1
                payload = json.loads(result.output)
                assert payload["success"] is False
                assert "redirect" in payload["error"]
                assert payload["references"]["total"] >= 1

                # 笔记未被删除
                assert _show(runner, kb_name, b_id)["id"] == b_id

    def test_delete_unreferenced_note_ok(self, mock_embedding_backend):
        """无引用笔记正常删除，不需要 --allow-dangling"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                b_id = _add(runner, kb_name, "孤立笔记", "no refs")
                _add(runner, kb_name, "其他笔记", "不引用任何笔记")

                result = runner.invoke(app, ["delete", b_id, "--force", "--kb", kb_name, "--json"])

                assert result.exit_code == 0, result.output
                payload = json.loads(result.output)
                assert payload["success"] is True

    def test_delete_allow_dangling_flag(self, mock_embedding_backend):
        """--allow-dangling 显式放行，产生悬空引用由用户承担"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                b_id = _add(runner, kb_name, "笔记B", "B body")
                a_id = _add(runner, kb_name, "笔记A", "A 引用 [[笔记B]]")

                result = runner.invoke(
                    app,
                    ["delete", b_id, "--force", "--allow-dangling", "--kb", kb_name, "--json"],
                )

                assert result.exit_code == 0, result.output
                # 悬空引用保留在 A 的 frontmatter（不做静默清理）
                a_note = _show(runner, kb_name, a_id)
                assert b_id in a_note["links"]

    def test_redirect_then_delete_succeeds(self, mock_embedding_backend):
        """先 redirect 迁移引用，再删除旧笔记：#435 的标准工作流"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                b_id = _add(runner, kb_name, "笔记B", "B body")
                c_id = _add(runner, kb_name, "笔记C", "C body")
                a_id = _add(runner, kb_name, "笔记A", "A 引用 [[笔记B]]")

                # 1. 迁移引用 B → C
                redirect_result = runner.invoke(
                    app, ["redirect", b_id, c_id, "--kb", kb_name, "--json"]
                )
                assert redirect_result.exit_code == 0, redirect_result.output

                # 2. 删除 B 不再被拦截
                delete_result = runner.invoke(
                    app, ["delete", b_id, "--force", "--kb", kb_name, "--json"]
                )
                assert delete_result.exit_code == 0, delete_result.output

                # 3. A 的引用已指向 C（frontmatter 与正文）
                a_note = _show(runner, kb_name, a_id)
                assert c_id in a_note["links"]
                assert b_id not in a_note["links"]
                assert f"[[{c_id}]]" in a_note["content"]

    def test_guard_covers_archived_references(self, mock_embedding_backend):
        """归档笔记的引用同样构成删除保护（不能静默过滤）"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                b_id = _add(runner, kb_name, "笔记B", "B body")
                src_id = _add(runner, kb_name, "归档来源", "旧文引用 [[笔记B]]")

                # 归档来源笔记
                archive_result = runner.invoke(app, ["archive", src_id, "--kb", kb_name, "--json"])
                assert archive_result.exit_code == 0, archive_result.output

                result = runner.invoke(app, ["delete", b_id, "--force", "--kb", kb_name, "--json"])
                assert result.exit_code == 1
                payload = json.loads(result.output)
                assert payload["references"]["total"] >= 1
