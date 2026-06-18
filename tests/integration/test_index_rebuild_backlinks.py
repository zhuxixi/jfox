"""
测试类型: 集成测试
目标功能: index rebuild --backlinks 重新计算反向链接
预估耗时: 10-30秒
依赖要求: 需要临时知识库

测试 jfox index rebuild --backlinks 在手动修改笔记文件后恢复 backlinks 关系
"""

from pathlib import Path

import pytest


@pytest.fixture
def _clear_backlinks():
    """辅助函数：清空指定笔记文件的 backlinks 字段"""

    def _clear(filepath: Path) -> None:
        from jfox.models import Note

        note = Note.from_markdown(filepath.read_text(encoding="utf-8"), filepath)
        note.backlinks = []
        filepath.write_text(note.to_markdown(), encoding="utf-8")

    return _clear


pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestIndexRebuildBacklinks:
    """index rebuild --backlinks 功能测试"""

    def test_index_rebuild_backlinks_restores_backlinks(self, cli_fast, _clear_backlinks):
        """手动清空目标笔记 backlinks 后，--backlinks 重建能恢复"""
        # 1. 创建目标笔记 A
        target = cli_fast.add("Target content", title="Target Note", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        # 2. 创建源笔记 B，引用 A
        source = cli_fast.add(
            "Source referencing [[Target Note]]", title="Source Note", note_type="permanent"
        )
        assert source.success
        source_id = source.data["note"]["id"]

        # 3. 验证初始 backlinks 正确
        refs_before = cli_fast.refs(note_id=target_id)
        assert refs_before.success
        backlink_ids_before = [link["id"] for link in refs_before.data.get("backward_links", [])]
        assert source_id in backlink_ids_before

        # 4. 手动清空 A 的 backlinks 字段（模拟迁移/手动修改）
        target_note_path = Path(target.data["note"]["filepath"])
        _clear_backlinks(target_note_path)

        # 5. 验证手动清空后 backlinks 丢失
        refs_after_clear = cli_fast.refs(note_id=target_id)
        assert refs_after_clear.success
        backlink_ids_after_clear = [
            link["id"] for link in refs_after_clear.data.get("backward_links", [])
        ]
        assert source_id not in backlink_ids_after_clear

        # 6. 执行 index rebuild --backlinks
        rebuild_result = cli_fast.index_rebuild(backlinks=True)
        assert rebuild_result.success
        data = rebuild_result.data
        assert data is not None
        assert data.get("backlinks_rebuilt") is True
        assert data.get("backlinks_updated", 0) >= 1
        assert data.get("backlinks_total", 0) >= 2

        # 7. 验证 backlinks 已恢复
        refs_after_rebuild = cli_fast.refs(note_id=target_id)
        assert refs_after_rebuild.success
        backlink_ids_after_rebuild = [
            link["id"] for link in refs_after_rebuild.data.get("backward_links", [])
        ]
        assert source_id in backlink_ids_after_rebuild

    def test_index_rebuild_without_backlinks_flag_does_not_touch_backlinks(
        self, cli_fast, _clear_backlinks
    ):
        """不带 --backlinks 时，index rebuild 不应修改 backlinks"""
        # 1. 创建目标笔记 A 和源笔记 B
        target = cli_fast.add("Target content", title="No Touch Target", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        source = cli_fast.add(
            "Source referencing [[No Touch Target]]", title="Source Note 2", note_type="permanent"
        )
        assert source.success
        source_id = source.data["note"]["id"]

        # 2. 手动清空 A 的 backlinks
        target_note_path = Path(target.data["note"]["filepath"])
        _clear_backlinks(target_note_path)

        # 3. 不带 --backlinks 重建索引
        rebuild_result = cli_fast.index_rebuild(backlinks=False)
        assert rebuild_result.success

        # 4. 验证 backlinks 仍然为空
        refs_after = cli_fast.refs(note_id=target_id)
        assert refs_after.success
        backlink_ids = [link["id"] for link in refs_after.data.get("backward_links", [])]
        assert source_id not in backlink_ids

    def test_index_rebuild_backlinks_multiple_sources(self, cli_fast, _clear_backlinks):
        """多个笔记链接到同一目标时，backlinks 应全部恢复"""
        target = cli_fast.add("Common target content", title="Common Target", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        source_ids = []
        for i in range(3):
            source = cli_fast.add(
                f"Source {i} referencing [[Common Target]]",
                title=f"Multi Source {i}",
                note_type="permanent",
            )
            assert source.success
            source_ids.append(source.data["note"]["id"])

        # 手动清空目标 backlinks
        target_note_path = Path(target.data["note"]["filepath"])
        _clear_backlinks(target_note_path)

        # 重建 backlinks
        rebuild_result = cli_fast.index_rebuild(backlinks=True)
        assert rebuild_result.success
        data = rebuild_result.data
        assert data.get("backlinks_updated", 0) >= 1

        # 验证全部 3 个反向链接
        refs_result = cli_fast.refs(note_id=target_id)
        assert refs_result.success
        backlink_ids = [link["id"] for link in refs_result.data.get("backward_links", [])]
        assert len(backlink_ids) == 3
        for sid in source_ids:
            assert sid in backlink_ids

    def test_index_rebuild_backlinks_reports_unresolved_links(self, cli_fast):
        """存在无法解析的链接时，应报告 unresolved_links"""
        result = cli_fast.add(
            "Note with [[Nonexistent Target]] link",
            title="Note With Broken Link",
            note_type="permanent",
        )
        assert result.success

        rebuild_result = cli_fast.index_rebuild(backlinks=True)
        assert rebuild_result.success
        data = rebuild_result.data
        assert "unresolved_links" in data
        assert "Nonexistent Target" in data["unresolved_links"]

    def test_index_rebuild_backlinks_does_not_overwrite_forward_links(
        self, cli_fast, _clear_backlinks
    ):
        """--backlinks 只重新计算 backlinks，不覆盖用户手写或已有的 forward links"""
        from jfox.models import Note

        # 1. 创建目标笔记 A
        target = cli_fast.add("Target content", title="Keep Forward Target", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        # 2. 创建源笔记 B，引用 A（B 的 forward links 会被 add 设置）
        source = cli_fast.add(
            "Source referencing [[Keep Forward Target]]",
            title="Source With Forward Link",
            note_type="permanent",
        )
        assert source.success
        source_id = source.data["note"]["id"]
        source_path = Path(source.data["note"]["filepath"])

        # 3. 在 B 的 frontmatter 中额外手写一个 forward link（模拟用户手写链接）
        note = Note.from_markdown(source_path.read_text(encoding="utf-8"), source_path)
        extra_link_id = "999999999999999999"
        note.links = sorted(set(note.links + [extra_link_id]))
        source_path.write_text(note.to_markdown(), encoding="utf-8")

        # 4. 清空 A 的 backlinks
        target_path = Path(target.data["note"]["filepath"])
        _clear_backlinks(target_path)

        # 5. 执行 index rebuild --backlinks
        rebuild_result = cli_fast.index_rebuild(backlinks=True)
        assert rebuild_result.success
        data = rebuild_result.data
        assert data.get("backlinks_rebuilt") is True
        assert data.get("backlinks_failed", -1) == 0

        # 6. 验证 A 的 backlinks 已恢复
        refs_after = cli_fast.refs(note_id=target_id)
        assert refs_after.success
        backlink_ids = [link["id"] for link in refs_after.data.get("backward_links", [])]
        assert source_id in backlink_ids

        # 7. 验证 B 的 forward links 保持不变（包含手写的 extra_link_id）
        note_after = Note.from_markdown(source_path.read_text(encoding="utf-8"), source_path)
        assert extra_link_id in note_after.links
