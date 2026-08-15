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
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                # 1. 创建 B（被引用方）
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
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
                b_id = json.loads(b_result.output)["note"]["id"]

                # 2. 创建 A 引用 B
                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
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

    def test_delete_cleanup_write_failure_warns_but_deletes(self, mock_embedding_backend):
        """target 写盘失败时 delete 仍成功（A 文件已删），仅 warning——与 promote 回填容错语义一致"""
        import jfox.note as note_module

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
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
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
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
                a_id = json.loads(a_result.output)["note"]["id"]

                # 只让写 B 的那次 _atomic_write 失败（用 b_id 定位），其余走原逻辑
                original_atomic_write = note_module._atomic_write

                def failing_atomic_write(filepath, content):
                    if b_id in str(filepath):
                        raise OSError("simulated disk failure")
                    return original_atomic_write(filepath, content)

                with patch.object(note_module, "_atomic_write", side_effect=failing_atomic_write):
                    del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                    assert del_result.exit_code == 0, del_result.output

                # A 已删：show A 找不到（exit 1 + not found）
                show_a = runner.invoke(app, ["show", a_id, "--kb", kb_name, "--json"])
                assert show_a.exit_code == 1, "删除后 show A 应失败（not found）"

                # B.backlinks 仍含 A（清理失败 = bug 修复前状态，rebuild 兜底语义）
                show_b = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b.exit_code == 0, show_b.output
                assert a_id in json.loads(show_b.output)["backlinks"]

    def test_delete_note_without_links_succeeds(self, mock_embedding_backend):
        """无 links 的笔记删除不受影响（清理循环空转不崩）"""
        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                c_result = runner.invoke(
                    app,
                    [
                        "add",
                        "孤岛笔记正文，无任何 wiki link。",
                        "--title",
                        "孤岛笔记",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert c_result.exit_code == 0, c_result.output
                c_id = json.loads(c_result.output)["note"]["id"]

                del_result = runner.invoke(app, ["delete", c_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                show_c = runner.invoke(app, ["show", c_id, "--kb", kb_name, "--json"])
                assert show_c.exit_code == 1, "删除后 show C 应失败（not found）"

    def test_delete_skips_rewrite_when_backlink_absent(self, mock_embedding_backend):
        """不对称状态（A.links 含 B 但 B.backlinks 不含 A）→ membership 守卫跳过，B 文件不被重写"""
        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
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
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
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
                a_id = json.loads(a_result.output)["note"]["id"]

                # 手工构造不对称：清空 B.backlinks 后落盘（模拟历史数据不一致）
                with use_kb(kb_name):
                    import jfox.note as note_module

                    b_note = note_module.load_note_by_id(b_id)
                    b_note.backlinks = []
                    note_module._atomic_write(b_note.filepath, b_note.to_markdown())
                    b_mtime = b_note.filepath.stat().st_mtime_ns

                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 守卫判否 → B 未被重写（mtime 不变）
                with use_kb(kb_name):
                    b_path = note_module.load_note_by_id(b_id).filepath
                    assert b_path.stat().st_mtime_ns == b_mtime, "守卫跳过时不应重写 B 文件"

    def test_delete_tolerates_null_backlinks_target(self, mock_embedding_backend):
        """target 手工编辑成 backlinks: null（解析为 None）时，delete 仍成功不中断"""
        import re

        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
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
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
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
                a_id = json.loads(a_result.output)["note"]["id"]

                # 手工编辑 B 的 frontmatter：把 backlinks 列表改成 null（模拟手改笔记）
                with use_kb(kb_name):
                    import jfox.note as note_module

                    b_path = note_module.load_note_by_id(b_id).filepath
                    text = b_path.read_text(encoding="utf-8")
                    # 替换 "backlinks:" 行及其后的列表项行（"- ..."）为 "backlinks: null"
                    text = re.sub(
                        r"backlinks:.*(?:\n[ \t]*-[ \t]+.*)*",
                        "backlinks: null",
                        text,
                        count=1,
                    )
                    b_path.write_text(text, encoding="utf-8")

                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # A 已真正删除
                show_a = runner.invoke(app, ["show", a_id, "--kb", kb_name, "--json"])
                assert show_a.exit_code == 1, "删除后 show A 应失败（not found）"

                # B 文件仍在（清理 target 失败仅 warning，不影响 delete 主流程）
                assert b_path.exists(), "B 文件应仍存在"
