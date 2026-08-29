"""
测试类型: 单元测试
目标模块: jfox.add_dedup
预估耗时: < 2秒

不依赖真实 embedding 模型 / daemon：
- embedding 通道用确定性 stub backend（同文本 → 同单位向量 → cosine=1.0）
- dedup store 用 set_store 注入临时路径
- 配置/daemon 探测用 monkeypatch，不写真实 ~/.zk_config.json
"""

import hashlib
from datetime import datetime

import numpy as np
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.add_dedup import (
    DuplicateNoteError,
    check_add_duplicate,
    record_added_permanent,
)
from jfox.config import ZKConfig
from jfox.gem_synth.dedup import DedupStore, set_store
from jfox.global_config import NoteAddConfig
from jfox.models import Note, NoteType

# 注意：必须真实超过 _EMBED_DEDUP_MIN_CHARS(50)，否则 embedding 通道被短文本闸门跳过
_EXISTING_CONTENT = "这是一段已经存在的永久笔记正文，用于验证 embedding 通道查重，正文长度需要超过五十个字符的硬性门槛才会进入余弦比较。"


def _deterministic_encode(text: str) -> np.ndarray:
    """同文本 → 同单位向量（cosine=1.0）；不同文本 → 近正交。"""
    parts = [hashlib.sha256(f"{i}:{text}".encode()).digest()[:8] for i in range(4)]
    vec = np.concatenate([np.frombuffer(p, dtype=np.uint8) for p in parts]).astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-12)


class _StubBackend:
    """替换 embedding_backend.get_backend 的确定性桩（duck-typing encode_single）。"""

    def encode_single(self, text: str):
        return _deterministic_encode(text)


@pytest.fixture
def kb_cfg(temp_kb):
    """含一条 permanent 笔记的临时知识库（返回 ZKConfig，标题中英文各一）。"""
    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()
    notes = [
        Note(
            id="20260829001",
            title="已有笔记",
            content=_EXISTING_CONTENT,
            type=NoteType.PERMANENT,
            created=datetime(2026, 8, 29, 0, 1),
            updated=datetime(2026, 8, 29, 0, 1),
        ),
        Note(
            id="20260829002",
            title="Zoloz K8s Namespaces",
            content="english titled note body",
            type=NoteType.PERMANENT,
            created=datetime(2026, 8, 29, 0, 2),
            updated=datetime(2026, 8, 29, 0, 2),
        ),
    ]
    for n in notes:
        note_dir = cfg.notes_dir / n.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{n.id}.md").write_text(n.to_markdown(), encoding="utf-8")
    return cfg


@pytest.fixture
def archived_kb(temp_kb):
    """同标题笔记只有一条且 frontmatter 标记 archived: true 的临时知识库。"""
    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()
    note_dir = cfg.notes_dir / "permanent"
    note_dir.mkdir(parents=True, exist_ok=True)
    md = (
        "---\n"
        "id: '20260829009'\n"
        "title: 归档旧笔记\n"
        "type: permanent\n"
        "created: '2026-08-29T00:09:00'\n"
        "updated: '2026-08-29T00:09:00'\n"
        "archived: true\n"
        "tags: []\n"
        "links: []\n"
        "backlinks: []\n"
        "---\n\n# 归档旧笔记\n\n正文。\n"
    )
    (note_dir / "20260829009.md").write_text(md, encoding="utf-8")
    return cfg


@pytest.fixture
def dedup_env(tmp_path, monkeypatch):
    """临时 dedup store + daemon 探测 True + stub backend + 默认配置。"""
    store = DedupStore(db_path=tmp_path / "synthesis_test.db")
    set_store(store)
    monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: True)
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _StubBackend())
    monkeypatch.setattr("jfox.add_dedup._load_note_add_config", lambda: NoteAddConfig())
    yield store
    set_store(None)
    store.close()


class TestTitleChannel:
    def test_same_title_blocked(self, kb_cfg, dedup_env):
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("已有笔记", "完全不同的新正文内容" * 3, cfg=kb_cfg)
        assert ei.value.matched_by == "title"
        assert ei.value.matched_id == "20260829001"
        assert ei.value.score is None

    def test_title_case_insensitive(self, kb_cfg, dedup_env):
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("ZOLOZ K8S NAMESPACES", "新正文" * 10, cfg=kb_cfg)
        assert ei.value.matched_id == "20260829002"

    def test_archived_title_not_blocked(self, archived_kb, dedup_env):
        check_add_duplicate("归档旧笔记", "全新正文" * 10, cfg=archived_kb)  # 不抛即通过

    def test_different_title_passes(self, kb_cfg, dedup_env):
        check_add_duplicate("全新标题", _EXISTING_CONTENT + "改写若干字避免逐字相同", cfg=kb_cfg)


class TestEmbeddingChannel:
    def test_same_content_different_title_blocked(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("全新标题", _EXISTING_CONTENT, cfg=kb_cfg)
        assert ei.value.matched_by == "embedding"
        assert ei.value.matched_id == "20260829001"
        assert ei.value.score >= 0.95

    def test_different_content_passes(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        check_add_duplicate("全新标题", "毫不相关的另一段长正文" * 5, cfg=kb_cfg)

    def test_short_content_skips_embedding(self, kb_cfg, dedup_env):
        short = "短内容"  # ≤50 字符，embedding 通道按设计跳过
        record_added_permanent("20260829001", short, cfg=kb_cfg)
        check_add_duplicate("全新标题", short, cfg=kb_cfg)  # 不抛即通过

    def test_daemon_down_skips_embedding(self, kb_cfg, dedup_env, monkeypatch):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: False)
        check_add_duplicate("全新标题", _EXISTING_CONTENT, cfg=kb_cfg)  # 降级放行

    def test_title_channel_disabled_uses_embedding_only(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr(
            "jfox.add_dedup._load_note_add_config",
            lambda: NoteAddConfig(title_dedup=False),
        )
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        # 同标题 + 同正文（已灌表）：标题通道关闭后由 embedding 通道兜住
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)
        assert ei.value.matched_by == "embedding"


class TestConfigSwitches:
    def test_dedup_disabled_passes_everything(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr(
            "jfox.add_dedup._load_note_add_config",
            lambda: NoteAddConfig(dedup_enabled=False),
        )
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)  # 不抛即通过


class TestGateNotRoadblock:
    def test_internal_error_passes(self, kb_cfg, dedup_env, monkeypatch):
        def _boom(cfg=None):
            raise RuntimeError("index exploded")

        monkeypatch.setattr("jfox.note_index.get_note_index", _boom)
        check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)  # 放行


class TestRecordAddedPermanent:
    def test_daemon_down_is_noop(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: False)
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        assert dedup_env.count() == 0

    def test_writes_to_store(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        assert dedup_env.count() == 1


def test_synthesis_db_env_override(tmp_path, monkeypatch):
    """JFOX_SYNTHESIS_DB 覆盖 synthesis db 路径（conftest 全局隔离的依据）。"""
    from jfox.gem_synth.paths import default_synthesis_db_path

    p = tmp_path / "s.db"
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(p))
    assert default_synthesis_db_path() == p.resolve()
