"""
测试类型: 单元测试
目标功能: jfox delete 清理目标笔记 backlinks（issue #386）
预估耗时: < 2秒
依赖要求: 临时知识库，mock embedding backend

复现 GitHub issue #386：A 引用 B，删除 A 后 B 的 frontmatter backlinks
不应残留 A 的 id。断言一律用 show --json 读 frontmatter 真值——
refs 会静默过滤悬空 backlink（load 不到的 id 不进输出），用它断言是假绿灯。
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


class TestDeleteCleansBacklinks:
    """测试 delete 命令的 backlinks 增量移除（与 promote 回填对称）"""

    def test_delete_removes_note_from_target_backlinks(self, mock_embedding_backend):
        """删除 A 后，B 的 backlinks 不残留 A 的 id（issue #386 核心）"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend", return_value=mock_embedding_backend
            ):
                # 1. 创建 B（被引用方）
                b_result = runner.invoke(
                    app,
                    [
                        "add", "B body",
                        "--title", "笔记B", "--type", "permanent",
                        "--kb", kb_name, "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                # 2. 创建 A 引用 B
                a_result = runner.invoke(
                    app,
                    [
                        "add", "A 引用 [[笔记B]]。",
                        "--title", "笔记A", "--type", "permanent",
                        "--kb", kb_name, "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 前置确认：B.backlinks 已含 A（add 回填正常，否则测试自身无效）
                show_b = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b.exit_code == 0, show_b.output
                assert a_id in json.loads(show_b.output)["backlinks"]

                # 3. 删除 A
                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 4. 断言 frontmatter 真值：B.backlinks 不再含 A
                show_b2 = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b2.exit_code == 0, show_b2.output
                backlinks_b = json.loads(show_b2.output)["backlinks"]
                assert a_id not in backlinks_b, "delete 后 B.backlinks 不应残留已删 A 的 id"
