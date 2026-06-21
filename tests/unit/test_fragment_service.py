"""service.ingest_event 编排测试（临时 store，无 daemon/模型）。"""

from jfox.fragment.service import ingest_event
from jfox.fragment.store import FragmentStore
from jfox.global_config import FragmentCaptureConfig


def test_userprompt_correction_inserted(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "不对，应该改"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "correction"
    assert isinstance(result["fragment_id"], int)
    assert store.get(result["fragment_id"])["fragment_type"] == "correction"


def test_posttooluse_inserted(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_response": {"stdout": "ok"},
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "tool_call"


def test_stop_writes_summary_and_message(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    # 先攒两条碎片
    ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "不对"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    ingest_event(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_response": "x"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    # 触发 Stop
    result = ingest_event(
        {"hook_event_name": "Stop", "session_id": "s1"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "session_summary"
    assert "纠正" in result["message"]
    assert "工具" in result["message"]
    # session_summary 行也入库
    summaries = store.query(session_id="s1", fragment_type="session_summary")
    assert len(summaries) == 1


def test_disabled_config_returns_skip(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"},
        store=store,
        config=FragmentCaptureConfig(enabled=False),
    )
    assert result["status"] == "skipped"
    assert store.query(session_id="s1") == []


def test_missing_session_id(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "prompt": "hi"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "error"
    assert "session_id" in result["message"]
