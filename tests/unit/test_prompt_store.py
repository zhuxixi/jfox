"""PromptStore SQLite 测试（临时文件，无 daemon/模型依赖）。

覆盖 user_prompts / prompt_judgments / unresolved_items 三张表的
schema、幂等键、claim 状态机和历史索引。
"""

import pytest

from jfox.prompts.store import PromptStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _store(tmp_path):
    return PromptStore(db_path=tmp_path / "fragments.db")


def _event(session_id="s1", prompt="你好", transcript_path=None, user_index=None):
    ev = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "prompt": prompt,
    }
    if transcript_path is not None:
        ev["transcript_path"] = transcript_path
    if user_index is not None:
        # 模拟 ingestion 时写入的定位信息（不在 CC 原始事件里，由 store 计算/回填）
        pass
    return ev


# ---------------------------------------------------------------------------
# insert_prompt / get_prompt：字段完整性与长文本 round-trip
# ---------------------------------------------------------------------------


def test_insert_prompt_preserves_long_unicode_text(tmp_path):
    store = _store(tmp_path)
    prompt = "中文长文本" * 400 + "\n```python\nprint('x')\n```"
    result = store.insert_prompt(_event(prompt=prompt), source_key="capture:c1", capture_id="c1")
    assert result["status"] == "stored"
    assert result["prompt"] == prompt
    row = store.get_prompt(result["prompt_id"])
    assert row["prompt"] == prompt
    assert len(row["prompt"]) == len(prompt)


def test_insert_prompt_rejects_non_user_prompt_submit(tmp_path):
    store = _store(tmp_path)
    result = store.insert_prompt(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "prompt": "x"},
        source_key="capture:c1",
    )
    assert result["status"] == "error"


def test_insert_prompt_rejects_empty_session_id(tmp_path):
    store = _store(tmp_path)
    result = store.insert_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "", "prompt": "x"},
        source_key="capture:c1",
    )
    assert result["status"] == "error"


def test_insert_prompt_rejects_empty_prompt(tmp_path):
    store = _store(tmp_path)
    result = store.insert_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": ""},
        source_key="capture:c1",
    )
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# 幂等键：capture_id / source_key
# ---------------------------------------------------------------------------


def test_duplicate_capture_returns_existing_row(tmp_path):
    store = _store(tmp_path)
    r1 = store.insert_prompt(_event(prompt="问题A"), source_key="capture:c1", capture_id="c1")
    r2 = store.insert_prompt(_event(prompt="问题A"), source_key="capture:c1", capture_id="c1")
    assert r1["status"] == "stored"
    assert r2["status"] == "duplicate"
    assert r2["prompt_id"] == r1["prompt_id"]
    assert store.count_prompts() == 1


def test_identical_prompts_from_different_captures_are_separate_rows(tmp_path):
    """合法的重复提问必须保留为多行，不按正文 hash 合并。"""
    store = _store(tmp_path)
    r1 = store.insert_prompt(_event(prompt="同样的问题"), source_key="capture:c1", capture_id="c1")
    r2 = store.insert_prompt(_event(prompt="同样的问题"), source_key="capture:c2", capture_id="c2")
    assert r1["status"] == "stored"
    assert r2["status"] == "stored"
    assert r1["prompt_id"] != r2["prompt_id"]
    assert store.count_prompts() == 2


def test_duplicate_source_key_without_capture_returns_duplicate(tmp_path):
    """backfill 重跑（source_key=fragment:N）不重复插入。"""
    store = _store(tmp_path)
    r1 = store.insert_prompt(_event(prompt="历史"), source_key="fragment:42")
    r2 = store.insert_prompt(_event(prompt="历史"), source_key="fragment:42")
    assert r1["status"] == "stored"
    assert r2["status"] == "duplicate"
    assert store.count_prompts() == 1


# ---------------------------------------------------------------------------
# prompt_hash 规范化
# ---------------------------------------------------------------------------


def test_prompt_hash_normalizes_whitespace_and_nfkc(tmp_path):
    """NFKC + 首尾空白 + 连续空白折叠后相同文本 → 相同 hash。"""
    store = _store(tmp_path)
    r1 = store.insert_prompt(
        _event(prompt="  hello   world  "), source_key="capture:c1", capture_id="c1"
    )
    r2 = store.insert_prompt(_event(prompt="hello world"), source_key="capture:c2", capture_id="c2")
    h1 = store.get_prompt(r1["prompt_id"])["prompt_hash"]
    h2 = store.get_prompt(r2["prompt_id"])["prompt_hash"]
    assert h1 == h2


def test_prompt_hash_nfkc_fullwidth_equals_halfwidth(tmp_path):
    store = _store(tmp_path)
    r1 = store.insert_prompt(
        _event(prompt="ＡＢＣ １２３"), source_key="capture:c1", capture_id="c1"
    )
    r2 = store.insert_prompt(_event(prompt="ABC 123"), source_key="capture:c2", capture_id="c2")
    h1 = store.get_prompt(r1["prompt_id"])["prompt_hash"]
    h2 = store.get_prompt(r2["prompt_id"])["prompt_hash"]
    # NFKC 把全角折叠成半角；内部单空格保留
    assert h1 == h2


# ---------------------------------------------------------------------------
# session_seq 分配
# ---------------------------------------------------------------------------


def test_session_seq_increments_per_source_session(tmp_path):
    store = _store(tmp_path)
    r1 = store.insert_prompt(_event(session_id="s1", prompt="a"), source_key="capture:c1")
    r2 = store.insert_prompt(_event(session_id="s1", prompt="b"), source_key="capture:c2")
    r3 = store.insert_prompt(_event(session_id="s2", prompt="c"), source_key="capture:c3")
    assert store.get_prompt(r1["prompt_id"])["session_seq"] == 1
    assert store.get_prompt(r2["prompt_id"])["session_seq"] == 2
    # 不同 session 独立计数
    assert store.get_prompt(r3["prompt_id"])["session_seq"] == 1


# ---------------------------------------------------------------------------
# transcript occurrence 唯一性
# ---------------------------------------------------------------------------


def test_transcript_occurrence_uniqueness(tmp_path):
    """同一 transcript 的同一 user occurrence 只保留一行（backfill/live 合并）。"""
    store = _store(tmp_path)
    ev1 = _event(prompt="定位消息", transcript_path="/tmp/t.jsonl")
    r1 = store.insert_prompt(
        ev1,
        source_key="capture:c1",
        capture_id="c1",
        transcript_path="/tmp/t.jsonl",
        transcript_user_index=3,
    )
    ev2 = _event(prompt="定位消息", transcript_path="/tmp/t.jsonl")
    r2 = store.insert_prompt(
        ev2, source_key="fragment:99", transcript_path="/tmp/t.jsonl", transcript_user_index=3
    )
    assert r1["status"] == "stored"
    assert r2["status"] == "duplicate"
    assert r2["prompt_id"] == r1["prompt_id"]
    assert store.count_prompts() == 1


def test_transcript_same_path_different_index_are_separate(tmp_path):
    store = _store(tmp_path)
    r1 = store.insert_prompt(
        _event(prompt="第一问"),
        source_key="capture:c1",
        capture_id="c1",
        transcript_path="/tmp/t.jsonl",
        transcript_user_index=1,
    )
    r2 = store.insert_prompt(
        _event(prompt="第二问"),
        source_key="capture:c2",
        capture_id="c2",
        transcript_path="/tmp/t.jsonl",
        transcript_user_index=2,
    )
    assert r1["status"] == "stored"
    assert r2["status"] == "stored"
    assert store.count_prompts() == 2


# ---------------------------------------------------------------------------
# list_prompts / count_prompts
# ---------------------------------------------------------------------------


def test_list_prompts_filters_by_session(tmp_path):
    store = _store(tmp_path)
    store.insert_prompt(_event(session_id="s1", prompt="a"), source_key="capture:c1")
    store.insert_prompt(_event(session_id="s1", prompt="b"), source_key="capture:c2")
    store.insert_prompt(_event(session_id="s2", prompt="c"), source_key="capture:c3")
    rows = store.list_prompts(session_id="s1")
    assert len(rows) == 2
    assert all(r["session_id"] == "s1" for r in rows)


def test_list_prompts_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.insert_prompt(_event(prompt=f"m{i}"), source_key=f"capture:c{i}")
    assert len(store.list_prompts(limit=2)) == 2


# ---------------------------------------------------------------------------
# judgment claim 状态机
# ---------------------------------------------------------------------------


def _claim_one(store, kb="default", pid=1, token="tok1", now="2026-09-02T00:00:00Z"):
    return store.claim_prompts(kb, [pid], token, now)


def test_claim_prompts_creates_processing_row(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="待判断"), source_key="capture:c1")
    pid = r["prompt_id"]
    claimed = _claim_one(store, pid=pid)
    assert claimed == [pid]
    j = store.get_judgment("default", pid)
    assert j["judgment_state"] == "processing"
    assert j["claim_token"] == "tok1"
    assert j["attempt_count"] == 1


def test_claim_skips_active_claim(tmp_path):
    """另一个 judge 持有未过期 claim 时不重复 claim。"""
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="并发"), source_key="capture:c1")
    pid = r["prompt_id"]
    assert _claim_one(store, pid=pid, token="tokA", now="2026-09-02T00:00:00Z") == [pid]
    # 30 秒后另一个 judge 尝试 claim（lease 未过期）
    assert _claim_one(store, pid=pid, token="tokB", now="2026-09-02T00:00:30Z") == []
    assert store.get_judgment("default", pid)["claim_token"] == "tokA"


def test_claim_recovers_stale_claim(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="过期"), source_key="capture:c1")
    pid = r["prompt_id"]
    _claim_one(store, pid=pid, token="tokA", now="2026-09-02T00:00:00Z")
    # 超过 lease（默认 420s）后可回收
    claimed = _claim_one(store, pid=pid, token="tokB", now="2026-09-02T00:10:00Z")
    assert claimed == [pid]
    j = store.get_judgment("default", pid)
    assert j["claim_token"] == "tokB"
    assert j["attempt_count"] == 2


def test_finish_judgment_success_clears_claim(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="成功"), source_key="capture:c1")
    pid = r["prompt_id"]
    _claim_one(store, pid=pid)
    store.finish_judgment(
        "default",
        pid,
        classification="new",
        reason="KB 无覆盖",
        confidence=0.8,
        matched_note_ids=["n1"],
        matched_prompt_ids=[],
        matched_unresolved_prompt_ids=[],
        context_mode="full",
        runner_id="pi",
        model_id="deepseek",
        candidate_note_id="20260902-000001",
    )
    j = store.get_judgment("default", pid)
    assert j["judgment_state"] == "succeeded"
    assert j["classification"] == "new"
    assert j["disposition"] == "pending"
    assert j["claim_token"] is None
    assert j["candidate_note_id"] == "20260902-000001"
    assert j["confidence"] == 0.8


def test_fail_judgment_clears_claim_and_sets_error(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="失败"), source_key="capture:c1")
    pid = r["prompt_id"]
    _claim_one(store, pid=pid)
    store.fail_judgment("default", pid, "runner timeout")
    j = store.get_judgment("default", pid)
    assert j["judgment_state"] == "failed"
    assert j["classification"] is None
    assert j["disposition"] is None
    assert j["last_error"] == "runner timeout"
    assert j["claim_token"] is None


def test_succeeded_not_reclaimed_by_plain_claim(tmp_path):
    """成功的 judgment 不被普通 claim 重复处理。"""
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="已完成"), source_key="capture:c1")
    pid = r["prompt_id"]
    _claim_one(store, pid=pid)
    store.finish_judgment(
        "default",
        pid,
        classification="recorded",
        reason="已有",
        confidence=0.9,
        matched_note_ids=[],
        matched_prompt_ids=[],
        matched_unresolved_prompt_ids=[],
        context_mode="full",
        runner_id="pi",
        model_id="m",
    )
    # 成功后再次普通 claim → 不应选中
    assert _claim_one(store, pid=pid, token="tok2", now="2026-09-02T01:00:00Z") == []


def test_failed_can_be_reclaimed(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="重试"), source_key="capture:c1")
    pid = r["prompt_id"]
    _claim_one(store, pid=pid)
    store.fail_judgment("default", pid, "timeout")
    # retry-failed 场景：failed 行可重新 claim
    assert _claim_one(store, pid=pid, token="tok2", now="2026-09-02T01:00:00Z") == [pid]


def test_judgments_scoped_by_kb(tmp_path):
    """同一 prompt 在不同 KB 各有一条 judgment，互不污染。"""
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="跨库"), source_key="capture:c1")
    pid = r["prompt_id"]
    store.claim_prompts("kb-a", [pid], "tokA", "2026-09-02T00:00:00Z")
    store.claim_prompts("kb-b", [pid], "tokB", "2026-09-02T00:00:00Z")
    store.finish_judgment(
        "kb-a",
        pid,
        classification="new",
        reason="a",
        confidence=0.5,
        matched_note_ids=[],
        matched_prompt_ids=[],
        matched_unresolved_prompt_ids=[],
        context_mode="full",
        runner_id="pi",
        model_id="m",
    )
    ja = store.get_judgment("kb-a", pid)
    jb = store.get_judgment("kb-b", pid)
    assert ja["judgment_state"] == "succeeded"
    assert jb["judgment_state"] == "processing"


# ---------------------------------------------------------------------------
# unresolved_items 索引
# ---------------------------------------------------------------------------


def test_upsert_unresolved_active(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="未解决"), source_key="capture:c1")
    pid = r["prompt_id"]
    item = store.upsert_unresolved("default", pid, note_id="note-1", now="2026-09-02T00:00:00Z")
    assert item["state"] == "active"
    active = store.list_unresolved("default", state="active")
    assert len(active) == 1 and active[0]["prompt_id"] == pid


def test_upsert_unresolved_idempotent(tmp_path):
    """重复 upsert 同一 prompt 不产生重复条目。"""
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="幂等"), source_key="capture:c1")
    pid = r["prompt_id"]
    store.upsert_unresolved("default", pid, note_id="note-1", now="2026-09-02T00:00:00Z")
    store.upsert_unresolved("default", pid, note_id="note-1", now="2026-09-02T01:00:00Z")
    assert len(store.list_unresolved("default", state="active")) == 1


def test_resolve_unresolved_moves_state(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="解决"), source_key="capture:c1")
    pid = r["prompt_id"]
    store.upsert_unresolved("default", pid, note_id="note-1", now="2026-09-02T00:00:00Z")
    store.resolve_unresolved("default", pid, reason="已修复", now="2026-09-03T00:00:00Z")
    assert store.list_unresolved("default", state="active") == []
    resolved = store.list_unresolved("default", state="resolved")
    assert len(resolved) == 1
    assert resolved[0]["resolution_reason"] == "已修复"


def test_unresolved_scoped_by_kb(tmp_path):
    store = _store(tmp_path)
    r = store.insert_prompt(_event(prompt="库A"), source_key="capture:c1")
    pid = r["prompt_id"]
    store.upsert_unresolved("kb-a", pid, note_id="note-a", now="2026-09-02T00:00:00Z")
    assert store.list_unresolved("kb-b", state="active") == []
    assert len(store.list_unresolved("kb-a", state="active")) == 1


# ---------------------------------------------------------------------------
# 连接与关闭
# ---------------------------------------------------------------------------


def test_close_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.close()
    store.close()  # 不抛异常


def test_default_path_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "env.db"))
    store = PromptStore()
    r = store.insert_prompt(_event(prompt="env"), source_key="capture:c1")
    assert r["status"] == "stored"
    assert (tmp_path / "env.db").exists()
    store.close()
