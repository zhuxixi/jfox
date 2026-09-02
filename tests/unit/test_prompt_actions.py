"""prompt 人工动作测试：promote/unresolved/resolve/ignore/retry 前置条件与记账。"""

import pytest

from jfox.prompts.store import PromptStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _finish(store, pid, classification, candidate=None):
    store.finish_judgment(
        "kb",
        pid,
        classification=classification,
        reason="test",
        confidence=0.8,
        matched_note_ids=[],
        matched_prompt_ids=[],
        matched_unresolved_prompt_ids=[],
        context_mode="prompt_only",
        runner_id="pi",
        model_id="m",
        candidate_note_id=candidate,
    )


def _store_with_new_judgment(tmp_path, classification="new", with_candidate=True):
    """构造一个 succeeded/pending 的 judgment（可带 candidate）。"""
    store = PromptStore(db_path=tmp_path / "fragments.db")
    store.insert_prompt(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "如何做原子写",
        },
        source_key="capture:c1",
    )
    store.claim_prompts("kb", [1], "tok", "2026-01-01T00:00:00Z")
    _finish(
        store,
        1,
        classification,
        candidate="20260902000000-000001" if with_candidate else None,
    )
    return store


# ---------------------------------------------------------------------------
# promote_prompt
# ---------------------------------------------------------------------------


def test_promote_prompt_happy_path(tmp_path):
    from jfox.prompts.actions import promote_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._promote_candidate", lambda nid: True)
        ok = promote_prompt("kb", 1, store=store)

    assert ok is True
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "promoted"


def test_promote_rejects_repeated_classification(tmp_path):
    from jfox.prompts.actions import promote_prompt

    store = _store_with_new_judgment(tmp_path, "repeated", with_candidate=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._promote_candidate", lambda nid: True)
        ok = promote_prompt("kb", 1, store=store)

    assert ok is False  # 只有 new 分类可 promote
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "pending"  # 不变


def test_promote_rejects_missing_candidate(tmp_path):
    from jfox.prompts.actions import promote_prompt

    store = _store_with_new_judgment(tmp_path, "new", with_candidate=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._promote_candidate", lambda nid: True)
        ok = promote_prompt("kb", 1, store=store)

    assert ok is False  # new 但没有 candidate → 拒绝


def test_promote_idempotent_second_call_fails(tmp_path):
    from jfox.prompts.actions import promote_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._promote_candidate", lambda nid: True)
        assert promote_prompt("kb", 1, store=store) is True
        # 第二次：disposition 已是 promoted → False
        assert promote_prompt("kb", 1, store=store) is False


def test_promote_promote_failure_leaves_pending(tmp_path):
    from jfox.prompts.actions import promote_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._promote_candidate", lambda nid: False)
        ok = promote_prompt("kb", 1, store=store)

    assert ok is False
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "pending"  # promote 失败不记账


# ---------------------------------------------------------------------------
# unresolved_prompt
# ---------------------------------------------------------------------------


def test_unresolved_happy_path_updates_store_and_note(tmp_path):
    from jfox.prompts.actions import unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "repeated", with_candidate=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._update_unresolved_note", lambda kb, pid, store: "note-1")
        ok = unresolved_prompt("kb", 1, store=store)

    assert ok is True
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "unresolved"
    items = store.list_unresolved("kb")
    assert len(items) == 1
    assert items[0]["prompt_id"] == 1


def test_unresolved_rejects_new_classification(tmp_path):
    from jfox.prompts.actions import unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "new")  # new 不能标 unresolved
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._update_unresolved_note", lambda kb, pid, store: "note-1")
        ok = unresolved_prompt("kb", 1, store=store)

    assert ok is False
    assert store.list_unresolved("kb") == []


def test_unresolved_note_update_failure_rolls_back(tmp_path):
    from jfox.prompts.actions import unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "repeated", with_candidate=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "jfox.prompts.actions._update_unresolved_note",
            lambda kb, pid, store: (_ for _ in ()).throw(RuntimeError("note write failed")),
        )
        ok = unresolved_prompt("kb", 1, store=store)

    assert ok is False
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "pending"  # 回滚
    assert store.list_unresolved("kb") == []


# ---------------------------------------------------------------------------
# resolve_unresolved_prompt
# ---------------------------------------------------------------------------


def test_resolve_unresolved_happy_path(tmp_path):
    from jfox.prompts.actions import resolve_unresolved_prompt, unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "repeated", with_candidate=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._update_unresolved_note", lambda kb, pid, store: "note-1")
        unresolved_prompt("kb", 1, store=store)

        called = {}
        mp.setattr(
            "jfox.prompts.actions._remove_unresolved_marker",
            lambda kb, pid, reason, store: called.setdefault("x", True),
        )
        ok = resolve_unresolved_prompt("kb", 1, reason="已解决", store=store)

    assert ok is True
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "resolved"
    assert called.get("x") is True
    assert store.list_unresolved("kb") == []  # 无 active


def test_resolve_without_active_returns_false(tmp_path):
    from jfox.prompts.actions import resolve_unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "repeated", with_candidate=False)
    ok = resolve_unresolved_prompt("kb", 1, reason="r", store=store)
    assert ok is False  # 从未 unresolved → 拒绝


# ---------------------------------------------------------------------------
# ignore_prompt
# ---------------------------------------------------------------------------


def test_ignore_without_candidate(tmp_path):
    from jfox.prompts.actions import ignore_prompt

    store = _store_with_new_judgment(tmp_path, "recorded", with_candidate=False)
    ok = ignore_prompt("kb", 1, store=store)
    assert ok is True
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "ignored"


def test_ignore_with_reject_candidate(tmp_path):
    from jfox.prompts.actions import ignore_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    rejected = []

    def fake_reject(nid, reason=None):
        rejected.append(nid)
        return True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._reject_candidate", fake_reject)
        ok = ignore_prompt("kb", 1, reject_candidate=True, store=store)

    assert ok is True
    assert rejected == ["20260902000000-000001"]
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "ignored"


def test_ignore_with_candidate_but_no_flag_fails(tmp_path):
    """有 candidate 时不加 --reject-candidate 必须拒绝（防误丢 candidate）。"""
    from jfox.prompts.actions import ignore_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    ok = ignore_prompt("kb", 1, store=store)  # 没传 reject_candidate
    assert ok is False
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "pending"


# ---------------------------------------------------------------------------
# retry_prompt
# ---------------------------------------------------------------------------


def test_retry_failed_prompt(tmp_path):
    from jfox.prompts.actions import retry_prompt

    store = PromptStore(db_path=tmp_path / "fragments.db")
    store.insert_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "x"},
        source_key="capture:c1",
    )
    store.claim_prompts("kb", [1], "tok", "2026-01-01T00:00:00Z")
    store.fail_judgment("kb", 1, "boom")
    ok = retry_prompt("kb", 1, store=store)
    assert ok is True  # failed 可 retry
    assert store.get_judgment("kb", 1) is None  # judgment 行已删除，可重新 judge


def test_retry_succeeded_not_allowed(tmp_path):
    from jfox.prompts.actions import retry_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    ok = retry_prompt("kb", 1, store=store)
    assert ok is False  # succeeded 不能 retry（除非 needs_review）


def test_retry_needs_review_allowed(tmp_path):
    from jfox.prompts.actions import retry_prompt

    store = _store_with_new_judgment(tmp_path, "needs_review", with_candidate=False)
    ok = retry_prompt("kb", 1, store=store)
    assert ok is True  # needs_review 可 retry


# ---------------------------------------------------------------------------
# force override（D18）
# ---------------------------------------------------------------------------


def test_unresolved_force_override_new_classification(tmp_path):
    """--force --reason 允许对 new 分类标 unresolved，留痕 manual_override。"""
    from jfox.prompts.actions import unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions._update_unresolved_note", lambda kb, pid, store: "note-1")
        ok = unresolved_prompt("kb", 1, force=True, reason="人工判断", store=store)

    assert ok is True
    j = store.get_judgment("kb", 1)
    assert j["disposition"] == "unresolved"
    assert j["manual_override"] == 1
    assert j["manual_reason"] == "人工判断"


def test_force_without_reason_rejected(tmp_path):
    """--force 必须带 --reason。"""
    from jfox.prompts.actions import unresolved_prompt

    store = _store_with_new_judgment(tmp_path, "new")
    ok = unresolved_prompt("kb", 1, force=True, reason=None, store=store)
    assert ok is False


# ---------------------------------------------------------------------------
# unresolved 聚合笔记（真实 KB 读写）
# ---------------------------------------------------------------------------


class TestUnresolvedNote:
    def _setup_kb(self, temp_kb):
        from jfox.config import ZKConfig

        cfg = ZKConfig.load(temp_kb)
        return cfg

    def test_creates_note_if_missing(self, temp_kb):
        from jfox.prompts.actions import _update_unresolved_note
        from jfox.prompts.store import PromptStore

        store = PromptStore(db_path=temp_kb / "fragments.db")
        note_id = _update_unresolved_note("kb", 42, store)
        assert note_id

        from jfox.note import load_note_by_id

        n = load_note_by_id(note_id)
        assert n is not None
        assert n.title == "JFox 待解决问题清单"
        assert "unresolved-problems" in (n.tags or [])
        assert n.type.value == "permanent"

    def test_marker_contains_prompt_id(self, temp_kb):
        from jfox.prompts.actions import _update_unresolved_note

        note_id = _update_unresolved_note("kb", 42, None)
        from jfox.note import load_note_by_id

        n = load_note_by_id(note_id)
        assert "42" in n.content  # 机器标记含 prompt ID

    def test_second_call_same_note_no_duplicate(self, temp_kb):
        from jfox.prompts.actions import _update_unresolved_note

        id1 = _update_unresolved_note("kb", 42, None)
        id2 = _update_unresolved_note("kb", 43, None)
        id3 = _update_unresolved_note("kb", 42, None)  # 重复
        assert id1 == id2 == id3  # 始终同一张清单

        from jfox.note import load_note_by_id

        n = load_note_by_id(id1)
        assert n.content.count("jfox:unresolved:42") <= 2  # start+end 标记

    def test_remove_marker(self, temp_kb):
        from jfox.prompts.actions import _remove_unresolved_marker, _update_unresolved_note

        note_id = _update_unresolved_note("kb", 42, None)
        _remove_unresolved_marker("kb", 42, "done", None)
        from jfox.note import load_note_by_id

        n = load_note_by_id(note_id)
        assert "jfox:unresolved:42" not in n.content


# ---------------------------------------------------------------------------
# candidate 直接 promote/reject 同步 judgment（Step 6）
# ---------------------------------------------------------------------------


class TestCandidateLifecycleSync:
    def test_post_promote_updates_judgment(self, temp_kb, monkeypatch):
        """candidate 直接 promote_note 后，对应 judgment disposition 同步 promoted。"""
        from jfox.prompts import lifecycle as pl
        from jfox.prompts.store import PromptStore

        store = PromptStore(db_path=temp_kb / "fragments.db")
        store.insert_prompt(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "q"},
            source_key="capture:c1",
        )
        store.claim_prompts("kb", [1], "t", "2026-01-01T00:00:00Z")
        _finish(store, 1, "new", candidate="n1")

        pl.on_post_promote(
            note_id="n1",
            note_type="candidate",
            source_prompts=[1],
            kb_name="kb",
            store=store,
        )
        j = store.get_judgment("kb", 1)
        assert j["disposition"] == "promoted"

    def test_post_reject_updates_judgment(self, temp_kb):
        from jfox.prompts import lifecycle as pl
        from jfox.prompts.store import PromptStore

        store = PromptStore(db_path=temp_kb / "fragments.db")
        store.insert_prompt(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "q"},
            source_key="capture:c1",
        )
        store.claim_prompts("kb", [1], "t", "2026-01-01T00:00:00Z")
        _finish(store, 1, "new", candidate="n1")

        pl.on_post_reject(
            note_id="n1",
            note_type="candidate",
            source_prompts=[1],
            kb_name="kb",
            store=store,
        )
        j = store.get_judgment("kb", 1)
        assert j["disposition"] == "rejected"

    def test_no_source_prompts_noop(self, temp_kb):
        """旧 candidate（无 source_prompts）不受影响。"""
        from jfox.prompts import lifecycle as pl
        from jfox.prompts.store import PromptStore

        store = PromptStore(db_path=temp_kb / "fragments.db")
        pl.on_post_promote(
            note_id="old-note",
            note_type="candidate",
            source_prompts=[],
            kb_name="kb",
            store=store,
        )
        # 不报错、无副作用
