"""测试 redirect 核心功能"""

import pytest
from datetime import datetime
from pathlib import Path

from jfox.models import Note, NoteType
from jfox.redirect import scan_references, redirect_references, _rewrite_body_links


@pytest.fixture
def setup_redirect_scenario(temp_kb):
    """创建测试场景：OLD 被 3 篇笔记引用"""
    from jfox.note_index import reset_note_index
    
    now = datetime(2026, 8, 27, 10, 0)
    
    old = Note("OLD-ID", "Old Title", "old body", NoteType.PERMANENT, now, now)
    keep = Note("KEEP-ID", "Keep Title", "keep body", NoteType.PERMANENT, now, now)
    
    # 3 个来源：frontmatter links / body title / body ID
    src_fm = Note("SRC-FM", "Source FM", "content", NoteType.PERMANENT, now, now, links=["OLD-ID"])
    src_body_title = Note("SRC-BODY-T", "Source Body Title", "[[Old Title]]", NoteType.PERMANENT, now, now)
    src_body_id = Note("SRC-BODY-ID", "Source Body ID", "[[OLD-ID]]", NoteType.PERMANENT, now, now)
    
    for n in [old, keep, src_fm, src_body_title, src_body_id]:
        p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n.to_markdown(), encoding="utf-8")
    
    # 重建索引以便 load_note_by_id 能找到笔记
    reset_note_index()
    
    return temp_kb, old, keep, [src_fm, src_body_title, src_body_id]


class TestScanReferences:
    """测试入链扫描"""
    
    def test_scan_frontmatter_and_body_refs(self, setup_redirect_scenario):
        """扫描 frontmatter links 和正文 wiki link"""
        temp_kb, old, keep, sources = setup_redirect_scenario
        
        report = scan_references("OLD-ID", "Old Title")
        
        assert not report.old_not_found
        assert report.old_title == "Old Title"
        assert len(report.frontmatter_refs) == 1
        assert report.frontmatter_refs[0][0] == "SRC-FM"
        assert len(report.body_refs) == 2  # title + ID 形式
        assert report.has_references()
    
    def test_scan_detects_duplicate_titles(self, temp_kb):
        """重复标题被检测为 preflight 错误"""
        now = datetime.now()
        dup1 = Note("DUP1", "Same Title", "body1", NoteType.PERMANENT, now, now)
        dup2 = Note("DUP2", "Same Title", "body2", NoteType.PERMANENT, now, now)
        
        for n in [dup1, dup2]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        report = scan_references("DUP1", keep_id="KEEP")
        
        assert len(report.duplicate_old_titles) == 2
        assert not report.can_proceed()
    
    def test_scan_includes_archived_notes(self, temp_kb):
        """归档笔记的引用也被扫描"""
        now = datetime.now()
        old = Note("OLD", "Old", "body", NoteType.PERMANENT, now, now)
        archived_src = Note("ARCH", "Archived", "[[Old]]", NoteType.PERMANENT, now, now, archived=True)
        
        for n in [old, archived_src]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        report = scan_references("OLD", "Old")
        
        assert len(report.body_refs) == 1
        assert report.body_refs[0][0] == "ARCH"


class TestRedirectReferences:
    """测试引用重定向"""
    
    def test_redirect_updates_frontmatter_links(self, setup_redirect_scenario):
        """frontmatter links 被更新为 KEEP-ID"""
        temp_kb, old, keep, sources = setup_redirect_scenario
        
        result = redirect_references("OLD-ID", "KEEP-ID")
        
        assert result.success
        assert result.frontmatter_links_updated == 1
        assert result.files_changed >= 1
        
        # 验证文件内容
        src_fm_path = temp_kb / "notes/permanent/SRC-FM.md"
        content = src_fm_path.read_text(encoding="utf-8")
        assert "links: [KEEP-ID]" in content or "links:\n- KEEP-ID" in content
        assert "OLD-ID" not in content
    
    def test_redirect_updates_body_wiki_links(self, setup_redirect_scenario):
        """正文 [[Old Title]] 被改写为 [[KEEP-ID]]"""
        temp_kb, old, keep, sources = setup_redirect_scenario
        
        result = redirect_references("OLD-ID", "KEEP-ID")
        
        assert result.success
        assert result.body_links_updated >= 2
        
        # 验证标题形式被改写
        src_body_title_path = temp_kb / "notes/permanent/SRC-BODY-T.md"
        content = src_body_title_path.read_text(encoding="utf-8")
        assert "[[KEEP-ID]]" in content
        assert "[[Old Title]]" not in content
        
        # 验证 ID 形式被改写
        src_body_id_path = temp_kb / "notes/permanent/SRC-BODY-ID.md"
        content = src_body_id_path.read_text(encoding="utf-8")
        assert "[[KEEP-ID]]" in content
        assert "[[OLD-ID]]" not in content
    
    def test_redirect_preserves_alias(self, temp_kb):
        """[[OLD|alias]] 被改写为 [[KEEP|alias]]"""
        now = datetime.now()
        old = Note("OLD", "Old", "body", NoteType.PERMANENT, now, now)
        keep = Note("KEEP", "Keep", "body", NoteType.PERMANENT, now, now)
        src = Note("SRC", "Source", "[[Old|别名]]", NoteType.PERMANENT, now, now)
        
        for n in [old, keep, src]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        result = redirect_references("OLD", "KEEP")
        
        assert result.success
        src_path = temp_kb / "notes/permanent/SRC.md"
        content = src_path.read_text(encoding="utf-8")
        assert "[[KEEP|别名]]" in content
        assert "[[Old|别名]]" not in content
    
    def test_redirect_preserves_anchor(self, temp_kb):
        """[[OLD#anchor]] 被改写为 [[KEEP#anchor]]"""
        now = datetime.now()
        old = Note("OLD", "Old", "body", NoteType.PERMANENT, now, now)
        keep = Note("KEEP", "Keep", "body", NoteType.PERMANENT, now, now)
        src = Note("SRC", "Source", "[[Old#section]]", NoteType.PERMANENT, now, now)
        
        for n in [old, keep, src]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        result = redirect_references("OLD", "KEEP")
        
        assert result.success
        src_path = temp_kb / "notes/permanent/SRC.md"
        content = src_path.read_text(encoding="utf-8")
        assert "[[KEEP#section]]" in content
        assert "[[Old#section]]" not in content
    
    def test_redirect_dry_run(self, setup_redirect_scenario):
        """dry_run 模式只报告、不写文件"""
        temp_kb, old, keep, sources = setup_redirect_scenario
        
        result = redirect_references("OLD-ID", "KEEP-ID", dry_run=True)
        
        assert result.success
        assert result.files_changed >= 1
        
        # 验证文件未被修改
        src_fm_path = temp_kb / "notes/permanent/SRC-FM.md"
        content = src_fm_path.read_text(encoding="utf-8")
        assert "OLD-ID" in content
        assert "KEEP-ID" not in content
    
    def test_redirect_fails_on_duplicate_titles(self, temp_kb):
        """重复标题导致 preflight 失败"""
        now = datetime.now()
        dup1 = Note("DUP1", "Same", "body1", NoteType.PERMANENT, now, now)
        dup2 = Note("DUP2", "Same", "body2", NoteType.PERMANENT, now, now)
        keep = Note("KEEP", "Keep", "body", NoteType.PERMANENT, now, now)
        
        for n in [dup1, dup2, keep]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        result = redirect_references("DUP1", "KEEP")
        
        assert not result.success
        assert any("Ambiguous" in err for err in result.errors)
    
    def test_redirect_preserves_unknown_frontmatter(self, temp_kb):
        """未知 frontmatter 字段被保留"""
        now = datetime.now()
        old = Note("OLD", "Old", "body", NoteType.PERMANENT, now, now)
        keep = Note("KEEP", "Keep", "body", NoteType.PERMANENT, now, now)
        src = Note("SRC", "Source", "content", NoteType.PERMANENT, now, now, links=["OLD"])
        
        # 手动添加未知字段
        src_path = temp_kb / "notes/permanent/SRC.md"
        src_path.write_text(
            src.to_markdown().replace(
                "backlinks: []",
                "backlinks: []\ncustom_field: keep_me\nanother_field: 123"
            ),
            encoding="utf-8"
        )
        
        for n in [old, keep]:
            p = temp_kb / "notes" / n.type.value / f"{n.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(n.to_markdown(), encoding="utf-8")
        
        result = redirect_references("OLD", "KEEP")
        
        assert result.success
        content = src_path.read_text(encoding="utf-8")
        assert "custom_field: keep_me" in content
        assert "another_field: 123" in content


class TestRewriteBodyLinks:
    """测试正文链接改写逻辑"""
    
    def test_rewrite_title_form(self):
        """[[Title]] → [[ID]]"""
        body = "前文 [[Old Title]] 后文"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert new_body == "前文 [[KEEP-ID]] 后文"
        assert count == 1
    
    def test_rewrite_id_form(self):
        """[[OLD-ID]] → [[KEEP-ID]]"""
        body = "前文 [[OLD-ID]] 后文"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert new_body == "前文 [[KEEP-ID]] 后文"
        assert count == 1
    
    def test_rewrite_with_alias(self):
        """[[Title|alias]] → [[ID|alias]]"""
        body = "前文 [[Old Title|别名]] 后文"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert new_body == "前文 [[KEEP-ID|别名]] 后文"
        assert count == 1
    
    def test_rewrite_with_anchor(self):
        """[[Title#anchor]] → [[ID#anchor]]"""
        body = "前文 [[Old Title#section]] 后文"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert new_body == "前文 [[KEEP-ID#section]] 后文"
        assert count == 1
    
    def test_rewrite_skips_code_blocks(self):
        """代码块内的链接不改写"""
        body = "```\n[[Old Title]]\n```\n正文 [[Old Title]]"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert "```\n[[Old Title]]\n```" in new_body
        assert "正文 [[KEEP-ID]]" in new_body
        assert count == 1
    
    def test_rewrite_skips_html_comments(self):
        """HTML 注释内的链接不改写"""
        body = "<!-- [[Old Title]] -->\n正文 [[Old Title]]"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert "<!-- [[Old Title]] -->" in new_body
        assert "正文 [[KEEP-ID]]" in new_body
        assert count == 1
    
    def test_rewrite_multiple_occurrences(self):
        """多处引用都被改写"""
        body = "[[Old Title]] 中间 [[Old Title]] [[OLD-ID]]"
        new_body, count = _rewrite_body_links(body, "OLD-ID", "Old Title", "KEEP-ID")
        assert new_body == "[[KEEP-ID]] 中间 [[KEEP-ID]] [[KEEP-ID]]"
        assert count == 3
