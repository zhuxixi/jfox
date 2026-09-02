"""fragment service 退役行为测试（#399：旧分类采集已退役）。

ingest_event 保留签名兼容历史调用点，但一律返回 retired，不写库。
store 单例管理（set_default_store/get_default_store）仍为 daemon 服务。
"""

import pytest

from jfox.fragment.service import (
    get_default_store,
    ingest_event,
    set_default_store,
)
from jfox.fragment.store import FragmentStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _reset_default_store():
    yield
    set_default_store(None)


def test_ingest_returns_retired(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "不对"},
        store=store,
    )
    assert result["status"] == "retired"
    assert "retired" in result["reason"]


def test_ingest_posttooluse_retired(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash"},
        store=store,
    )
    assert result["status"] == "retired"
    assert store.query(session_id="s1") == []  # 不写任何行


def test_ingest_stop_retired(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event({"hook_event_name": "Stop", "session_id": "s1"}, store=store)
    assert result["status"] == "retired"
    # 无 session_summary 生成
    assert store.query(session_id="s1", fragment_type="session_summary") == []


def test_ingest_non_dict_event_retired():
    result = ingest_event(None)
    assert result["status"] == "retired"
    result = ingest_event("garbage")
    assert result["status"] == "retired"


def test_default_store_singleton(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    set_default_store(store)
    assert get_default_store() is store
    set_default_store(None)
    assert get_default_store() is None
