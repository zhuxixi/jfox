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
    dedup.delete_dedup("default", "c1")
    assert setup.count("default") == 0


def test_delete_kb_scoped(setup):
    """delete 必须带 kb：同一 note_id 在不同 KB 各有一行，删一个不影响另一个。"""
    dedup.upsert_dedup("kbA", "shared-id", "candidate", "内容A")
    dedup.upsert_dedup("kbB", "shared-id", "candidate", "内容B")
    assert setup.count() == 2
    dedup.delete_dedup("kbA", "shared-id")
    assert setup.count("kbA") == 0
    assert setup.count("kbB") == 1  # kbB 的行不受影响


def test_dedup_check_zero_vector_no_nan(setup):
    """存储一个零向量行（腐败数据），dedup_check 不应因 NaN 崩溃或误判。"""
    store = dedup._get_store()
    zero_emb = np.zeros(64, dtype=np.float32)
    store.upsert("default", "zero-note", "candidate", "h", zero_emb.tobytes())
    # 零向量不应触发 NaN 毒化 argmax → 返回 None（无有效相似度 >= threshold）
    result = dedup.dedup_check("default", "任意内容", threshold=0.5)
    assert result is None


def test_upsert_dedup_returns_bool(setup):
    """upsert_dedup 返回 True 表示实际写入，False 表示跳过。"""
    assert dedup.upsert_dedup("default", "c1", "candidate", "内容") is True
    # 同内容再灌 → hash 命中 → 跳过 → False
    assert dedup.upsert_dedup("default", "c1", "candidate", "内容") is False
    # 空内容 → False
    assert dedup.upsert_dedup("default", "c2", "candidate", "") is False


def test_dedup_check_degrades_when_backend_unavailable(setup, monkeypatch):
    setup.upsert("default", "c1", "candidate", "h", FakeBackend().encode_single("x").tobytes())

    def boom():
        raise RuntimeError("daemon down")

    monkeypatch.setattr("jfox.embedding_backend.get_backend", boom)
    # daemon 挂了 → 降级返回 None，不抛
    assert dedup.dedup_check("default", "任意内容") is None


def test_upsert_permanent_keeps_full_content(setup):
    """Fix C: permanent 嵌完整正文，不剥元段落。若正文里恰好有 ## 来源 标题，不应被截断。"""
    body = "核心知识结论\n\n## 来源\n- 某论文 p.42\n"
    dedup.upsert_dedup("default", "perm-1", "permanent", body)
    # 同正文（含 ## 来源）再 dedup_check：permanent 的 hash 应基于完整正文，
    # 若被 _clean_candidate_content 剥掉 ## 来源，hash 会不一致 → upsert 返回 True（误判写入）
    assert dedup.upsert_dedup("default", "perm-1", "permanent", body) is False


def test_upsert_candidate_still_strips_meta(setup):
    """Fix C: candidate 仍剥元段落（有 ## 来源 等追加 meta）。"""
    body = "知识本体\n\n## 来源\n- 碎片 #1\n"
    dedup.upsert_dedup("default", "cand-1", "candidate", body)
    # 再灌只含"知识本体"（剥 meta 后相同）→ hash 命中 → 跳过
    assert dedup.upsert_dedup("default", "cand-1", "candidate", "知识本体") is False
