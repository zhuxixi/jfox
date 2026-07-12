"""gem_synth dedup 单测：mock embedding backend，不加载真模型。"""

import numpy as np
import pytest

from jfox.gem_synth import dedup
from jfox.gem_synth.dedup import DedupStore


class FakeBackend:
    """确定性 fake：把文本 sha1 哈希前 N 字节映成向量，相同/相近文本向量接近。"""

    def __init__(self, dim=64):
        self.dim = dim

    def encode_single(self, text):
        import hashlib

        h = hashlib.sha1(text.encode("utf-8")).digest()
        vec = np.frombuffer((h * (self.dim // len(h) + 1))[: self.dim * 4], dtype=np.uint8)
        return (vec.astype(np.float32) % 16) / 16.0


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """临时 db + fake backend 注入。"""
    store = DedupStore(db_path=tmp_path / "dedup.db")
    dedup.set_store(store)
    fake = FakeBackend()
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: fake)
    yield store
    dedup.set_store(None)


def test_clean_strips_meta_sections():
    raw = "正文知识\n\n## 来源\n- 碎片 #1\n\n## 置信度\n0.9\n"
    assert dedup._clean_candidate_content(raw) == "正文知识"


def test_dedup_check_returns_none_when_empty(setup):
    assert dedup.dedup_check("default", "全新知识", threshold=0.88) is None


def test_dedup_check_hits_existing_dup(setup):
    # 灌一个 candidate，再用同文本 dedup_check 应命中自己（验证余弦路径）
    dedup.upsert_dedup("default", "cand-1", "candidate", "Zima 双 Bot babysit 标签循环")
    hit = dedup.dedup_check("default", "Zima 双 Bot babysit 标签循环", threshold=0.5)
    assert hit == "cand-1"


def test_dedup_check_kb_isolation(setup):
    dedup.upsert_dedup("kbA", "cand-1", "candidate", "同一事实文本")
    # kbB 不应被 kbA 的 candidate 命中
    assert dedup.dedup_check("kbB", "同一事实文本", threshold=0.5) is None


def test_upsert_idempotent_on_same_content(setup):
    dedup.upsert_dedup("default", "c1", "candidate", "稳定内容")
    h1 = setup.get_hash("default", "c1")
    dedup.upsert_dedup("default", "c1", "candidate", "稳定内容")  # 同内容，hash 不变
    assert setup.get_hash("default", "c1") == h1


def test_delete_removes(setup):
    dedup.upsert_dedup("default", "c1", "candidate", "内容")
    assert setup.count("default") == 1
    dedup.delete_dedup("c1")
    assert setup.count("default") == 0


def test_dedup_check_degrades_when_backend_unavailable(setup, monkeypatch):
    setup.upsert("default", "c1", "candidate", "h", FakeBackend().encode_single("x").tobytes())

    def boom():
        raise RuntimeError("daemon down")

    monkeypatch.setattr("jfox.embedding_backend.get_backend", boom)
    # daemon 挂了 → 降级返回 None，不抛
    assert dedup.dedup_check("default", "任意内容") is None
