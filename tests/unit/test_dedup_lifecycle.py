"""dedup 生命周期同步测试（#399 退役迁移：接续旧 gem_synth/lifecycle 职责）。

验证：笔记 delete/archive/reject 清 dedup 行、promote 改 note_type、
非 candidate/permanent 类型早返回、register 幂等。
"""

import pytest

from jfox.dedup import DedupStore, set_store
from jfox.dedup_lifecycle import (
    _on_note_promoted,
    _on_note_removed,
    register_lifecycle,
)
from jfox.models import NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


import numpy as np


@pytest.fixture
def dedup_env(tmp_path, monkeypatch):
    """临时 dedup store（直接用 DedupStore 底层 upsert，绕过 embedding）。"""
    store = DedupStore(tmp_path / "dedup.db")
    set_store(store)
    # _resolve_kb_name(None) 走 config.base_dir.name（非 JFOX_KB），固定返回值隔离
    monkeypatch.setattr("jfox.dedup._resolve_kb_name", lambda kb: "test-kb")
    yield store
    set_store(None)


_EMB = np.array([0.5, 0.5], dtype=np.float32).tobytes()


def test_deleted_permanent_cleans_dedup_row(dedup_env):
    dedup_env.upsert("test-kb", "n1", "permanent", "hash1", _EMB)
    _on_note_removed("n1", NoteType.PERMANENT)
    assert dedup_env.get_hash("test-kb", "n1") is None


def test_archived_candidate_cleans_dedup_row(dedup_env):
    dedup_env.upsert("test-kb", "n2", "candidate", "hash2", _EMB)
    # archive 走同一回调（note_type 传字符串形态也应兼容）
    _on_note_removed("n2", "candidate")
    assert dedup_env.get_hash("test-kb", "n2") is None


def test_promoted_candidate_updates_type(dedup_env):
    dedup_env.upsert("test-kb", "n3", "candidate", "hash3", _EMB)
    _on_note_promoted("n3", NoteType.CANDIDATE)
    # 类型改 permanent：all_embeddings 过滤 candidate 不再命中
    cands = dedup_env.all_embeddings("test-kb", ("candidate",))
    perms = dedup_env.all_embeddings("test-kb", ("permanent",))
    assert all(nid != "n3" for nid, _, _ in cands)
    assert any(nid == "n3" for nid, _, _ in perms)


def test_fleeting_notes_skip_dedup(dedup_env):
    """fleeting/session 类型无 dedup 行，回调早返回不报错。"""
    _on_note_removed("n4", NoteType.FLEETING)  # 不抛错即可
    _on_note_promoted("n4", "session")


def test_register_idempotent():
    import jfox.note as note_mod

    before = list(note_mod._LIFECYCLE_HOOKS.get("post_delete", []))
    register_lifecycle()
    register_lifecycle()  # 二次注册去重
    after = list(note_mod._LIFECYCLE_HOOKS.get("post_delete", []))
    assert len(after) <= len(before) + 1


def test_register_lifecycle_wires_all_four_events():
    """register_lifecycle 覆盖 delete/archive/reject/promote 四事件（幂等）。"""
    import jfox.note as note_mod
    from jfox.dedup_lifecycle import _on_note_promoted, _on_note_removed

    register_lifecycle()
    for event in ("post_delete", "post_archive", "post_reject"):
        cbs = note_mod._LIFECYCLE_HOOKS.get(event, [])
        assert _on_note_removed in cbs, f"{event} 未接线"
    cbs = note_mod._LIFECYCLE_HOOKS.get("post_promote", [])
    assert _on_note_promoted in cbs, "post_promote 未接线"
