"""
测试类型: 集成测试
目标功能: issue #541 — --content-file 输入标准化后的回灌端到端验收（A6/A7）
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


def _count_structure(filepath: str) -> tuple:
    """返回 (frontmatter 分隔行数, H1 标题行数)"""
    # 注：全局计数，假定正文不含 fenced code block 与 --- 分隔线（当前受控输入成立）
    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    fm_delims = sum(1 for line in lines if line == "---")
    h1s = sum(1 for line in lines if line.startswith("# "))
    return fm_delims, h1s


class TestEditRoundTrip:
    """A6：show → 追加 → edit --content-file 回灌，结构恒定（issue 实验 B 自动化）"""

    def test_edit_roundtrip_content_body(self, cli_fast, tmp_path):
        """content_body 回灌（含 H1、无 frontmatter）：恰好 1 个 fm 块 + 1 个 H1，追加与原文俱在"""
        # 1. 建笔记
        r = cli_fast.add("原始正文第一段。", title="回灌复现笔记")
        assert r.success
        note_id = r.data["note"]["id"]
        filepath = r.data["note"]["filepath"]

        # 2. show --json 取 content_body（含 H1、无 frontmatter——即 #541 实验 B 输入）
        s = cli_fast._run("show", note_id)
        assert s.success
        body = s.data["content_body"]
        assert body.startswith("# ")

        # 3. 追加后整体回灌（文件路径通道）
        f = tmp_path / "body.md"
        f.write_text(body + "\n追加内容 B。\n", encoding="utf-8")
        e = cli_fast.edit(note_id, content_file=str(f))
        assert e.success

        # 4. 结构断言：恰好 1 个 fm 块（2 个 --- 行）、1 个 H1 行，追加内容在正文中
        fm_delims, h1s = _count_structure(filepath)
        assert fm_delims == 2
        assert h1s == 1
        n = _load_note(filepath)
        assert "追加内容 B。" in n.content
        assert "原始正文第一段。" in n.content

    def test_add_content_file_h1_title_derivation(self, cli_fast, tmp_path):
        """A7/D3：add --content-file 传 H1 开头正文，H1 被剥，标题派生自剥后首段"""
        f = tmp_path / "doc.md"
        f.write_text("# 外部文档标题\n\n真正的第一段。", encoding="utf-8")
        r = cli_fast._run("add", "--content-file", str(f))
        assert r.success
        filepath = r.data["note"]["filepath"]

        fm_delims, h1s = _count_structure(filepath)
        assert fm_delims == 2
        assert h1s == 1
        n = _load_note(filepath)
        assert n.title == "真正的第一段。"
        assert "# 外部文档标题" not in n.content
