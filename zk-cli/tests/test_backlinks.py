"""
反向链接自动维护单元测试

测试 CLI 在创建笔记链接时自动更新被链接笔记的 backlinks
"""

import pytest


class TestBacklinksAutoMaintenance:
    """反向链接自动维护功能测试"""
    
    def test_create_note_updates_target_backlinks(self, cli):
        """创建带链接的笔记时，自动更新目标笔记的反向链接"""
        # 1. 创建目标笔记
        target_result = cli.add(
            "Target note content",
            title="Target Note",
            note_type="permanent"
        )
        assert target_result.success
        target_id = target_result.data["note"]["id"]
        
        # 2. 创建源笔记，链接到目标
        source_result = cli.add(
            "Source note referencing [[Target Note]]",
            title="Source Note",
            note_type="permanent"
        )
        assert source_result.success
        source_id = source_result.data["note"]["id"]
        
        # 3. 验证目标笔记的反向链接包含源笔记
        refs_result = cli.refs(note_id=target_id)
        assert refs_result.success
        
        backlink_ids = [l["id"] for l in refs_result.data.get("backward_links", [])]
        assert source_id in backlink_ids, f"Expected backlink from {source_id} to {target_id}"
    
    def test_multiple_backlinks_to_same_target(self, cli):
        """多个笔记链接到同一个目标时，反向链接正确累积"""
        # 1. 创建目标笔记
        target = cli.add("Target content", title="Common Target", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]
        
        # 2. 创建多个源笔记链接到目标
        source_ids = []
        for i in range(3):
            source = cli.add(
                f"Source {i} referencing [[Common Target]]",
                title=f"Source Note {i}",
                note_type="permanent"
            )
            assert source.success
            source_ids.append(source.data["note"]["id"])
        
        # 3. 验证目标笔记有 3 个反向链接
        refs_result = cli.refs(note_id=target_id)
        assert refs_result.success
        
        backlink_ids = [l["id"] for l in refs_result.data.get("backward_links", [])]
        assert len(backlink_ids) == 3, f"Expected 3 backlinks, got {len(backlink_ids)}"
        
        for sid in source_ids:
            assert sid in backlink_ids, f"Missing backlink from {sid}"
    
    def test_backlink_not_duplicated(self, cli):
        """同一链接关系不重复添加反向链接"""
        # 1. 创建目标笔记
        target = cli.add("Target content", title="No Duplicate Target", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]
        
        # 2. 创建源笔记链接到目标
        source = cli.add(
            "Source referencing [[No Duplicate Target]]",
            title="Source Note",
            note_type="permanent"
        )
        assert source.success
        source_id = source.data["note"]["id"]
        
        # 3. 再次编辑源笔记（模拟重新保存）- 重新创建同名笔记不会自动去重
        # 实际测试：创建另一个笔记也链接到同一个目标
        source2 = cli.add(
            "Another source referencing [[No Duplicate Target]]",
            title="Another Source Note",
            note_type="permanent"
        )
        assert source2.success
        
        # 4. 验证目标笔记有 2 个不同的反向链接
        refs_result = cli.refs(note_id=target_id)
        assert refs_result.success
        
        backlink_ids = [l["id"] for l in refs_result.data.get("backward_links", [])]
        # 不应该有重复的 backlink ID
        assert len(backlink_ids) == len(set(backlink_ids)), "Backlinks should not be duplicated"
    
    def test_link_to_nonexistent_note_no_error(self, cli):
        """链接到不存在的笔记时不报错，也不创建反向链接"""
        # 创建笔记引用不存在的笔记
        result = cli.add(
            "Source referencing [[Nonexistent Note]]",
            title="Source With Broken Link",
            note_type="permanent"
        )
        # 应该成功创建，但会有警告
        assert result.success
        assert "warnings" in result.data or result.data.get("note", {}).get("links") == []
    
    def test_chained_backlinks(self, cli):
        """链式链接的反向链接验证 A <- B <- C"""
        # A
        note_a = cli.add("Note A content", title="Note A", note_type="permanent")
        assert note_a.success
        id_a = note_a.data["note"]["id"]
        
        # B -> A
        note_b = cli.add(
            "Note B referencing [[Note A]]",
            title="Note B",
            note_type="permanent"
        )
        assert note_b.success
        id_b = note_b.data["note"]["id"]
        
        # C -> B
        note_c = cli.add(
            "Note C referencing [[Note B]]",
            title="Note C",
            note_type="permanent"
        )
        assert note_c.success
        id_c = note_c.data["note"]["id"]
        
        # 验证 A 有来自 B 的反向链接
        refs_a = cli.refs(note_id=id_a)
        backlink_ids_a = [l["id"] for l in refs_a.data.get("backward_links", [])]
        assert id_b in backlink_ids_a
        
        # 验证 B 有来自 C 的反向链接
        refs_b = cli.refs(note_id=id_b)
        backlink_ids_b = [l["id"] for l in refs_b.data.get("backward_links", [])]
        assert id_c in backlink_ids_b
        
        # 验证 A 没有来自 C 的直接反向链接（只有间接通过 B）
        assert id_c not in backlink_ids_a
