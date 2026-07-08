"""candidate promote/reject 单元测试。目标模块: jfox.note"""

import pytest
from utils.temp_kb import temp_kb_registered

from jfox.config import use_kb
from jfox.models import Note, NoteType
from jfox.note import create_note, load_note_by_id, promote_note, reject_note, save_note

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _mock_embedding_backend(monkeypatch):
    """避免 promote_note/reject_note → update_note → vector_store 加载真实 sentence-transformers
    模型（kimi round-2 issue-3）：本文件标 @pytest.mark.fast，必须秒级完成，不加载真实模型。"""
    import numpy as np

    from jfox import embedding_backend

    class _Mock:
        model_name = "mock"
        device = "cpu"
        _resolved_device = "cpu"
        _resolved_model_name = "mock"
        dimension = 384

        def encode(self, texts, **kwargs):
            if isinstance(texts, str):
                texts = [texts]
            return np.random.rand(len(texts), self.dimension).astype("float32")

        def encode_batch(self, texts, batch_size=32):
            return self.encode(texts)

        def _resolve_device(self):
            return "cpu"

        def _resolve_model_name(self, resolved_device):
            return "mock"

    monkeypatch.setattr(embedding_backend, "get_backend", lambda: _Mock())


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


def test_promote_clears_candidate_lifecycle_fields():
    """清 candidate 生命周期字段（gem_level/confidence/status/knowledge_type）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容")
            promote_note(c.id)
            md = load_note_by_id(c.id).filepath.read_text(encoding="utf-8")
            for field in ("gem_level", "confidence", "status", "knowledge_type"):
                assert field not in md


def test_promote_preserves_provenance_fields():
    """c1：promote 保留 source_fragments/grounded_by 溯源（promoted permanent 可追溯到来源碎片）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容", grounded_by=["某参考笔记"])
            promote_note(c.id)
            md = load_note_by_id(c.id).filepath.read_text(encoding="utf-8")
            assert "source_fragments" in md  # [1, 2] 保留
            assert "grounded_by" in md  # ["某参考笔记"] 保留


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


def test_reject_archives_and_records_reason():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("要拒的", "内容")
            assert reject_note(c.id, reason="不准确") is True
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准确"
            assert r.status == "rejected"


def test_reject_without_reason_still_archives():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("要拒的", "内容")
            assert reject_note(c.id) is True
            assert load_note_by_id(c.id).archived is True
            assert load_note_by_id(c.id).reject_reason is None


def test_reject_nonexistent_returns_false():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            assert reject_note("999999999999999") is False


def test_reject_non_candidate_returns_false():
    """c8：reject 非 candidate 返回 False（类型守卫，与 promote 对称）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            p = create_note("永久", title="永久笔记", note_type=NoteType.PERMANENT)
            save_note(p, add_to_index=False)
            assert reject_note(p.id) is False


def test_unarchive_clears_reject_reason():
    """c9：reject→unarchive 后 reject_reason 清空（不残留拒绝语义）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            from jfox.note import unarchive_note

            c = _make_candidate("要拒的", "内容")
            reject_note(c.id, reason="不准")
            assert load_note_by_id(c.id).reject_reason == "不准"
            unarchive_note(c.id)
            r = load_note_by_id(c.id)
            assert r.reject_reason is None
            assert (
                r.status == "pending"
            )  # issue-12：candidate reject→unarchive 回 pending，不残留 rejected 僵尸态


def test_promote_clears_reject_reason_after_reject_unarchive():
    """c6：reject→unarchive→promote 后 permanent 不残留 reject_reason"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            from jfox.note import unarchive_note

            c = _make_candidate("先拒后升", "内容")
            reject_note(c.id, reason="误判")
            unarchive_note(c.id)
            promote_note(c.id)
            md = load_note_by_id(c.id).filepath.read_text(encoding="utf-8")
            assert "reject_reason" not in md


def test_promote_ignores_wiki_links_in_code_block():
    """c2：正文 fenced code block 里的 [[标题]] 不被误当链接回填 backlinks"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            # 正文仅含 code block 里的字面量 [[目标笔记]]，不应被当真实链接
            c = _make_candidate("代码块测试", "示例\n```\n[[目标笔记]] 是代码\n```\n")
            promote_note(c.id)
            assert c.id not in load_note_by_id(target.id).backlinks


def test_promote_clears_archived_after_reject():
    """issue-13：reject→直接 promote（跳 unarchive）后 archived=False（不产出被软删除的 permanent）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("先拒后升", "内容")
            reject_note(c.id)  # archived=True, status=rejected
            assert load_note_by_id(c.id).archived is True
            promote_note(c.id)  # 跳 unarchive 直接 promote
            p = load_note_by_id(c.id)
            assert p.type == NoteType.PERMANENT
            assert p.archived is False  # issue-13：promote 是激活，取消软删除标记


def test_promote_includes_grounded_by_in_links():
    """issue-4：grounded_by 参考笔记也并入 links（spec §2.1：links = 正文 wiki link + grounded_by）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="参考笔记X", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            # 正文不含 [[参考笔记X]]，仅 grounded_by 指向它
            c = _make_candidate("候选", "内容不含任何链接", grounded_by=["参考笔记X"])
            promote_note(c.id)
            assert target.id in load_note_by_id(c.id).links  # grounded_by → links


def test_promote_handles_none_in_grounded_by():
    """cc round-4：grounded_by 含 None/空串（YAML null / LLM 脏数据）不应崩 find_by_title"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("候选", "内容", grounded_by=["有效但不存在", None, ""])
            promote_note(c.id)  # None/空被过滤；"有效但不存在" 警告跳过；不崩
            assert load_note_by_id(c.id).type == NoteType.PERMANENT
