"""service.ingest_event 编排测试（临时 store，无 daemon/模型）。"""

import pytest

from jfox.fragment.service import ingest_event, set_default_store
from jfox.fragment.store import FragmentStore
from jfox.global_config import FragmentCaptureConfig


@pytest.fixture(autouse=True)
def _reset_default_store():
    """每个测试后清空 service 模块的全局 store 单例，避免污染其它测试/真实磁盘。"""
    yield
    set_default_store(None)


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


def test_store_unavailable_returns_structured_error():
    """无 store 注入且 daemon 未初始化时，不懒创建，返回结构化 error"""
    from jfox.fragment import service

    service.set_default_store(None)
    result = service.ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"},
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "error"
    assert "unavailable" in result["message"]


def test_store_exception_is_structured(tmp_path):
    """store.insert 抛异常时返回结构化 error 而非冒泡到路由"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    store.close()  # 关连接，后续 insert 抛 ProgrammingError
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "error"


@pytest.mark.parametrize("source", ["auto-summary", "gem-synth"])
def test_internal_source_skipped(tmp_path, source):
    """Issue #297：JFox 内部系统产生的 session 不应进入碎片采集链路"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "不对，应该改",
            "source": source,
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "skipped"
    assert source in result["reason"]
    assert store.query(session_id="s1") == []


def test_internal_source_in_metadata_skipped(tmp_path):
    """source 也可以放在 metadata 对象中传递"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "不要这样",
            "metadata": {"source": "gem-synth"},
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "skipped"
    assert store.query(session_id="s1") == []


@pytest.mark.parametrize("bad_metadata", [None, "not-a-dict", ["list"], 123])
def test_malformed_metadata_does_not_raise(tmp_path, bad_metadata):
    """metadata 非字典时不抛异常，按普通事件处理"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hi",
            "metadata": bad_metadata,
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "user_input"


@pytest.mark.parametrize("bad_source", [None, 123, ["list"], ""])
def test_non_string_source_ignored(tmp_path, bad_source):
    """source 字段非字符串时视为未声明，正常入库"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hi",
            "source": bad_source,
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "user_input"


def test_internal_source_from_env_var_skipped(tmp_path, monkeypatch):
    """事件未声明 source 时，用 JFOX_INTERNAL_SESSION 环境变量兜底跳过"""
    monkeypatch.setenv("JFOX_INTERNAL_SESSION", "auto-summary")
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "不对，应该改",
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "skipped"
    assert "auto-summary" in result["reason"]
    assert store.query(session_id="s1") == []


def test_env_var_non_internal_source_allowed(tmp_path, monkeypatch):
    """环境变量不是内部来源时正常采集"""
    monkeypatch.setenv("JFOX_INTERNAL_SESSION", "some-other-tool")
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "hi",
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "user_input"
