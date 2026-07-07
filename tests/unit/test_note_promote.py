"""candidate promote/reject 单元测试。目标模块: jfox.note"""

import pytest
from utils.temp_kb import temp_kb_registered

from jfox.config import use_kb
from jfox.models import Note, NoteType
from jfox.note import create_note, load_note_by_id, promote_note, save_note

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_reject_reason_roundtrip():
    """reject_reason 字段可序列化与反序列化"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    n.reject_reason = "知识不准确"
    md = n.to_markdown()
    assert "reject_reason: 知识不准确" in md
    restored = Note.from_markdown(md, n.filepath)
    assert restored.reject_reason == "知识不准确"


def test_reject_reason_not_written_when_none():
    """无 reject_reason 时不写入 frontmatter"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    assert "reject_reason" not in n.to_markdown()


def _make_candidate(title, content, grounded_by=None):
    """构造并保存一条 candidate 笔记。"""
    n = create_note(content, title=title, note_type=NoteType.CANDIDATE)
    n.gem_level = "flawed"
    n.confidence = 0.8
    n.status = "pending"
    n.source_fragments = [1, 2]
    n.grounded_by = grounded_by or []
    n.knowledge_type = "factual"
    save_note(n, add_to_index=False)
    return n


def test_promote_changes_type_to_permanent():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容 [[目标笔记]]")
            assert promote_note(c.id) is True
            assert load_note_by_id(c.id).type == NoteType.PERMANENT


def test_promote_moves_file_to_permanent_dir():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            from jfox.config import config

            c = _make_candidate("测试候选", "内容")
            candidate_path = config.notes_dir / "candidate" / c.filename
            assert candidate_path.exists()
            promote_note(c.id)
            assert (config.notes_dir / "permanent" / c.filename).exists()
            assert not candidate_path.exists()


def test_promote_clears_candidate_frontmatter_fields():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容")
            promote_note(c.id)
            md = load_note_by_id(c.id).filepath.read_text(encoding="utf-8")
            for field in (
                "gem_level",
                "confidence",
                "status",
                "source_fragments",
                "grounded_by",
                "knowledge_type",
            ):
                assert field not in md


def test_promote_backfills_backlinks_to_targets():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")
            promote_note(c.id)
            assert c.id in load_note_by_id(target.id).backlinks


def test_promote_sets_forward_links():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")
            promote_note(c.id)
            assert target.id in load_note_by_id(c.id).links


def test_promote_rejects_non_candidate():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            p = create_note("永久", title="永久笔记", note_type=NoteType.PERMANENT)
            save_note(p, add_to_index=False)
            assert promote_note(p.id) is False


def test_promote_nonexistent_returns_false():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            assert promote_note("999999999999999") is False
