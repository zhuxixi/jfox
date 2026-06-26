"""
测试类型: 单元测试
目标功能: jfox add 创建目标笔记时，自动回填引用方的正向 links
预估耗时: < 2秒
依赖要求: 临时知识库，mock embedding backend

复现 GitHub issue #275：
先创建笔记 A 引用尚不存在的 B，再创建 B 引用 A。
期望 B 创建后，A 的 links 字段自动回填 B 的 id。
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


class TestAddBackwardBackfill:
    """测试 add 命令的 backward links 回填"""

    def test_add_backfills_unresolved_forward_link(self, mock_embedding_backend):
        """创建目标笔记后，引用方的出边应自动 resolve"""
        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                # 1. 创建笔记 A，引用尚不存在的笔记 B
                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "笔记A 正文，引用了 [[笔记B]]。",
                        "--title",
                        "笔记A",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_data = json.loads(a_result.output)
                a_id = a_data["note"]["id"]

                # 2. 创建笔记 B，引用 A
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "笔记B 正文，引用了 [[笔记A]]。",
                        "--title",
                        "笔记B",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_data = json.loads(b_result.output)
                b_id = b_data["note"]["id"]

                # add --json 返回的 links 字段应包含回填/解析后的结果
                assert a_id in b_data["note"]["links"], "B 的 JSON 输出 links 应包含 A"

                # 3. 验证 A 的 links 已回填 B，且 backlinks 包含 B
                refs_a = runner.invoke(app, ["refs", "--note", a_id, "--kb", kb_name, "--json"])
                assert refs_a.exit_code == 0, refs_a.output
                refs_a_data = json.loads(refs_a.output)
                forward_a = {link["id"] for link in refs_a_data.get("forward_links", [])}
                backward_a = {link["id"] for link in refs_a_data.get("backward_links", [])}

                assert b_id in forward_a, "A 的 links 应自动回填 B 的 id"
                assert b_id in backward_a, "A 的 backlinks 应包含 B"

                # 4. 验证 B 的 links/backlinks 也正确
                refs_b = runner.invoke(app, ["refs", "--note", b_id, "--kb", kb_name, "--json"])
                assert refs_b.exit_code == 0, refs_b.output
                refs_b_data = json.loads(refs_b.output)
                forward_b = {link["id"] for link in refs_b_data.get("forward_links", [])}
                backward_b = {link["id"] for link in refs_b_data.get("backward_links", [])}

                assert a_id in forward_b, "B 的 links 应包含 A"
                assert a_id in backward_b, "B 的 backlinks 应包含 A"

    def test_add_backfill_no_duplicate_links(self, mock_embedding_backend):
        """重复创建/引用不会导致 links/backlinks 重复"""
        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                # 创建 A（引用 B）
                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[B]]。",
                        "--title",
                        "A",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 创建 B（引用 A）触发回填
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B 引用 [[A]]。",
                        "--title",
                        "B",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                # 再次创建 C（引用 A），A 的 backlinks 应只新增 C，不重复 B
                c_result = runner.invoke(
                    app,
                    [
                        "add",
                        "C 引用 [[A]]。",
                        "--title",
                        "C",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert c_result.exit_code == 0, c_result.output
                c_id = json.loads(c_result.output)["note"]["id"]

                refs_a = runner.invoke(app, ["refs", "--note", a_id, "--kb", kb_name, "--json"])
                assert refs_a.exit_code == 0, refs_a.output
                refs_a_data = json.loads(refs_a.output)
                backward_a = [link["id"] for link in refs_a_data.get("backward_links", [])]

                assert backward_a.count(b_id) == 1
                assert backward_a.count(c_id) == 1
