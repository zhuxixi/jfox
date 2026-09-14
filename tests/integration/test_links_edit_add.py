"""
测试类型: 集成测试
目标功能: issue #511 — add/edit 不自链、正文字面量不误链
预估耗时: 5-15秒
依赖要求: 临时隔离知识库（cli_fast fixture，mock embedding）
"""

from pathlib import Path

import pytest

from jfox.models import Note

pytestmark = [pytest.mark.integration]


def _load_note(filepath: str) -> Note:
    p = Path(filepath)
    return Note.from_markdown(p.read_text(encoding="utf-8"), p)


class TestEditSelfLink:
    """edit 路径（A5/A7）"""

    def test_edit_no_self_link(self, cli_fast):
        """A5：edit 追加含 [[ID|标题]] 字面量正文后，links/backlinks 均不含自身 ID"""
        # 1. 建标题含 "ID" 的 permanent（issue 复现场景）
        r = cli_fast.add("初始内容", title="某机制与 ID canonical 说明", note_type="permanent")
        assert r.success
        note_id = r.data["note"]["id"]
        filepath = r.data["note"]["filepath"]

        # 2. edit 追加含字面量的正文
        new_content = "初始内容\n\n说明文字 [[ID|标题]] 示例\n"
        e = cli_fast.edit(note_id, content=new_content)
        assert e.success

        # 3. links/backlinks 不含自身 ID（自链过滤生效）
        n = _load_note(filepath)
        assert note_id not in n.links
        assert note_id not in n.backlinks
        # 正文完整性：剥离只影响解析输入，落盘内容与输入一致
        assert "[[ID|标题]]" in n.content

    def test_edit_dedup(self):
        pass  # 占位由 test_edit_dedup_impl 承载——见下

    def test_edit_dedup_impl(self, cli_fast):
        """A2 链路级：edit 正文两次引用同一目标，links 去重"""
        t = cli_fast.add("T", title="去重目标", note_type="permanent")
        target_id = t.data["note"]["id"]
        r = cli_fast.add("源", title="去重源", note_type="permanent")
        src_path = r.data["note"]["filepath"]

        e = cli_fast.edit(r.data["note"]["id"], content="见 [[去重目标]] 再 [[去重目标]]")
        assert e.success
        assert _load_note(src_path).links == [target_id]


class TestAddSelfLink:
    """add 路径（A6/A7）"""

    def test_add_no_false_self_link(self, cli_fast):
        """A6：add 正文含与自身标题相关的字面量，links 不含自身 ID"""
        r = cli_fast.add(
            "说明文字 [[ID|标题]] 示例",
            title="某机制与 ID canonical 说明",
            note_type="permanent",
        )
        assert r.success
        note_id = r.data["note"]["id"]
        n = _load_note(r.data["note"]["filepath"])
        assert note_id not in n.links
        assert note_id not in n.backlinks

    def test_add_dedup(self, cli_fast):
        """A2 链路级：add 正文两次引用同一目标，links 去重"""
        t = cli_fast.add("T", title="add去重目标", note_type="permanent")
        target_id = t.data["note"]["id"]
        r = cli_fast.add(
            "见 [[add去重目标]] 再 [[add去重目标]]", title="add去重源", note_type="permanent"
        )
        assert r.success
        assert _load_note(r.data["note"]["filepath"]).links == [target_id]


class TestLiteralStripped:
    """字面量剥离（A7）"""

    def test_literal_in_fence_and_inline_not_linked(self, cli_fast):
        """fenced 块与反引号内的 [[...]] 不进 links；正文原样落盘"""
        t = cli_fast.add("T", title="剥离目标笔记", note_type="permanent")
        target_id = t.data["note"]["id"]

        content = (
            "正常引用 [[剥离目标笔记]]\n\n"
            "```\n示例 [[剥离目标笔记]] 在 fenced 内\n```\n\n"
            "行内 `[[剥离目标笔记]]` 示例\n"
        )
        r = cli_fast.add(content, title="剥离测试源", note_type="permanent")
        assert r.success
        n = _load_note(r.data["note"]["filepath"])
        # 正常引用解析一次；fenced 与 inline 内的字面量不进 links
        assert n.links == [target_id]
        # 剥离区域正文原样落盘（解析剥离 ≠ 落盘剥离）
        assert "`[[剥离目标笔记]]`" in n.content
        assert "示例 [[剥离目标笔记]] 在 fenced 内" in n.content
