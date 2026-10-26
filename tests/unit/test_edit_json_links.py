"""#577：edit --json 的链接字段——纯函数单元测试。

测试类型: 单元测试
目标模块: jfox.cli.diff_links / jfox.cli._edit_result_note
预估耗时: <1 秒
依赖要求: 无外部依赖（不建 KB、不写盘）
"""

from datetime import datetime
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.models import Note, NoteType


def _note(**overrides) -> Note:
    """构造内存 Note，并用 set_filepath 钉住路径（避免读全局配置）。"""
    base = dict(
        id="20260101000000",
        title="T",
        content="c",
        type=NoteType.PERMANENT,
        created=datetime(2026, 1, 1),
        updated=datetime(2026, 1, 1),
    )
    base.update(overrides)
    n = Note(**base)
    if n._filepath is None:
        n.set_filepath(Path("/tmp/20260101000000-t.md"))
    return n


class TestDiffLinks:
    def test_added_preserves_new_order(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["a"], ["b", "a", "c"])

        assert added == ["b", "c"]
        assert removed == []

    def test_removed_preserves_old_order(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["c", "a", "b"], ["a"])

        assert added == []
        assert removed == ["c", "b"]

    def test_duplicates_collapse(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["a", "a"], ["a", "b", "b", "c"])

        assert added == ["b", "c"]
        assert removed == []

    def test_empty_inputs(self):
        from jfox.cli import diff_links

        assert diff_links([], []) == ([], [])
        assert diff_links([], ["x"]) == (["x"], [])
        assert diff_links(["x"], []) == ([], ["x"])


class TestEditResultNote:
    def test_key_set(self):
        from jfox.cli import _edit_result_note

        payload = _edit_result_note(_note())

        assert set(payload) == {"id", "title", "type", "filepath", "links", "backlinks"}
        assert payload["type"] == "permanent"
        assert payload["links"] == []
        assert payload["backlinks"] == []

    def test_list_copies_are_independent(self):
        from jfox.cli import _edit_result_note

        n = _note(links=["a"], backlinks=["b"])
        payload = _edit_result_note(n)
        payload["links"].append("mutated")
        payload["backlinks"].append("mutated")

        assert n.links == ["a"]
        assert n.backlinks == ["b"]
