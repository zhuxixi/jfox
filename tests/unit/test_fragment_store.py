"""FragmentStore SQLite 测试（用临时文件，无 daemon/模型依赖）。"""

import json

from jfox.fragment.store import FragmentStore


def _store(tmp_path):
    return FragmentStore(db_path=tmp_path / "fragments.db")


def test_insert_and_get(tmp_path):
    store = _store(tmp_path)
    fid = store.insert(
        session_id="s1",
        fragment_type="correction",
        source_event="UserPromptSubmit",
        content="不对",
        metadata={"hook_event_name": "UserPromptSubmit", "prompt": "不对"},
    )
    assert isinstance(fid, int) and fid >= 1
    row = store.get(fid)
    assert row["session_id"] == "s1"
    assert row["fragment_type"] == "correction"
    assert json.loads(row["metadata_json"])["prompt"] == "不对"


def test_query_by_session_and_type(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.insert("s2", "correction", "UserPromptSubmit", "错了", {})

    rows = store.query(session_id="s1")
    assert len(rows) == 2

    rows = store.query(session_id="s1", fragment_type="tool_call")
    assert len(rows) == 1 and rows[0]["fragment_type"] == "tool_call"


def test_query_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.insert("s1", "user_input", "UserPromptSubmit", f"m{i}", {})
    rows = store.query(session_id="s1", limit=2)
    assert len(rows) == 2


def test_counts_by_type(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "correction", "UserPromptSubmit", "错了", {})
    store.insert("s1", "tool_call", "PostToolUse", "x", {})
    counts = store.counts_by_type("s1")
    assert counts == {"correction": 2, "tool_call": 1}


def test_counts_excludes_other_session(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s2", "correction", "UserPromptSubmit", "错了", {})
    assert store.counts_by_type("s1") == {"correction": 1}


def test_default_db_path_respects_env(tmp_path, monkeypatch):
    """默认路径读 JFOX_FRAGMENTS_DB 环境变量（CLI 集成测试用）"""
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "env.db"))
    store = FragmentStore()
    store.insert("s1", "user_input", "UserPromptSubmit", "hi", {})
    assert (tmp_path / "env.db").exists()


def test_close_is_idempotent(tmp_path):
    """close() 可被重复调用而不抛异常（daemon lifespan 关闭路径需要）"""
    store = _store(tmp_path)
    store.close()
    store.close()  # 不应抛 ProgrammingError
