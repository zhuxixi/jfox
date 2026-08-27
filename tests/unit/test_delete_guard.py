"""测试 delete 命令的入链保护（delete guard）"""

import pytest
from datetime import datetime

from jfox.models import Note, NoteType


@pytest.fixture
def setup_delete_scenario(temp_kb):
    """创建测试场景：target 被 2 篇笔记引用"""
    now = datetime(2026, 8, 27, 10, 0)
    
    target = Note("TARGET", "Target", "target body", NoteType.PERMANENT, now, now)
    ref1 = Note("REF1", "Ref1", "content", NoteType.PERMANENT, now, now, links=["TARGET"])
    ref2 = Note("REF2", "Ref2", "[[Target]]", NoteType.PERMANENT, now, now)
    orphan = Note("ORPHAN", "Orphan", "no refs", NoteType.PERMANENT, now, now)
    
    for n in [target, ref1, ref2, orphan]:
        p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
        p.write_text(n.to_markdown(), encoding="utf-8")
    
    return temp_kb, target, [ref1, ref2], orphan


class TestDeleteGuard:
    """测试删除前入链检查"""
    
    def test_delete_refuses_when_referenced(self, cli, setup_delete_scenario):
        """有入链时拒绝删除"""
        temp_kb, target, refs, orphan = setup_delete_scenario
        
        result = cli.delete("TARGET", force=True)
        
        assert not result.success
        assert "reference" in result.stderr.lower()
        assert "REF1" in result.stderr or "REF2" in result.stderr
    
    def test_delete_succeeds_with_allow_dangling(self, cli, setup_delete_scenario):
        """--allow-dangling 跳过检查"""
        temp_kb, target, refs, orphan = setup_delete_scenario
        
        result = cli.delete("TARGET", force=True, allow_dangling=True)
        
        assert result.success
        # 验证文件已删除
        target_path = temp_kb / "notes/permanent/TARGET.md"
        assert not target_path.exists()
    
    def test_delete_succeeds_when_no_references(self, cli, setup_delete_scenario):
        """无入链时正常删除"""
        temp_kb, target, refs, orphan = setup_delete_scenario
        
        result = cli.delete("ORPHAN", force=True)
        
        assert result.success
        orphan_path = temp_kb / "notes/permanent/ORPHAN.md"
        assert not orphan_path.exists()
    
    def test_delete_guard_includes_archived_refs(self, cli, temp_kb):
        """归档来源的引用也被检查"""
        now = datetime.now()
        target = Note("TARGET", "Target", "body", NoteType.PERMANENT, now, now)
        archived_ref = Note("ARCH", "Archived", "[[Target]]", NoteType.PERMANENT, now, now, archived=True)
        
        for n in [target, archived_ref]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        result = cli.delete("TARGET", force=True)
        
        assert not result.success
        assert "reference" in result.stderr.lower()
    
    def test_delete_json_output_includes_references(self, cli, setup_delete_scenario):
        """JSON 输出包含引用方列表"""
        temp_kb, target, refs, orphan = setup_delete_scenario
        
        result = cli.delete("TARGET", force=True, output_format="json")
        
        assert not result.success
        data = result.json
        assert "references" in data
        assert data["references"]["total"] == 2
        assert any(r["id"] == "REF1" for r in data["references"]["frontmatter"])
        assert any(r["id"] == "REF2" for r in data["references"]["body"])
    
    def test_delete_suggests_redirect_in_error(self, cli, setup_delete_scenario):
        """错误提示建议使用 redirect"""
        temp_kb, target, refs, orphan = setup_delete_scenario
        
        result = cli.delete("TARGET", force=True)
        
        assert not result.success
        assert "redirect" in result.stderr.lower()


class TestDeleteWorkflow:
    """测试删除工作流"""
    
    def test_redirect_then_delete(self, cli, temp_kb):
        """先 redirect 再 delete 的完整流程"""
        now = datetime.now()
        old = Note("OLD", "Old", "body", NoteType.PERMANENT, now, now)
        keep = Note("KEEP", "Keep", "body", NoteType.PERMANENT, now, now)
        ref = Note("REF", "Ref", "[[Old]]", NoteType.PERMANENT, now, now)
        
        for n in [old, keep, ref]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        # Step 1: redirect
        redirect_result = cli.redirect("OLD", "KEEP")
        assert redirect_result.success
        
        # Step 2: delete 现在应该成功
        delete_result = cli.delete("OLD", force=True)
        assert delete_result.success
        
        # 验证
        old_path = temp_kb / "notes/permanent/OLD.md"
        assert not old_path.exists()
        
        ref_path = temp_kb / "notes/permanent/REF.md"
        content = ref_path.read_text(encoding="utf-8")
        assert "[[KEEP]]" in content
        assert "[[Old]]" not in content
