"""Prompt 采集配置 + ingest_prompt + 内部来源过滤测试。"""

import json

import pytest

from jfox.prompts.service import ingest_prompt
from jfox.prompts.store import PromptStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _store(tmp_path):
    return PromptStore(db_path=tmp_path / "fragments.db")


# ---------------------------------------------------------------------------
# ingest_prompt
# ---------------------------------------------------------------------------


def test_ingest_prompt_stores_full_text(tmp_path):
    store = _store(tmp_path)
    long_prompt = "很长的中文prompt" * 200
    result = ingest_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": long_prompt},
        store=store,
        capture_id="cap-1",
    )
    assert result["status"] == "stored"
    row = store.get_prompt(result["prompt_id"])
    assert row["prompt"] == long_prompt


def test_ingest_prompt_duplicate_capture(tmp_path):
    store = _store(tmp_path)
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "重复"}
    r1 = ingest_prompt(ev, store=store, capture_id="cap-1")
    r2 = ingest_prompt(ev, store=store, capture_id="cap-1")
    assert r1["status"] == "stored"
    assert r2["status"] == "duplicate"


def test_ingest_prompt_rejects_post_tool_use(tmp_path):
    store = _store(tmp_path)
    result = ingest_prompt(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "prompt": "x"},
        store=store,
    )
    assert result["status"] == "error"


def test_ingest_prompt_rejects_missing_session(tmp_path):
    store = _store(tmp_path)
    result = ingest_prompt(
        {"hook_event_name": "UserPromptSubmit", "prompt": "x"},
        store=store,
    )
    assert result["status"] == "error"


@pytest.mark.parametrize("source", ["auto-summary", "gem-synth", "prompt-judge"])
def test_ingest_prompt_skips_internal_sources(tmp_path, source):
    """JFox 内部 session 不进 prompt 链路（#297 反馈循环教训）。"""
    store = _store(tmp_path)
    result = ingest_prompt(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "内部",
            "source": source,
        },
        store=store,
    )
    assert result["status"] == "skipped"
    assert store.count_prompts() == 0


def test_ingest_prompt_preserves_transcript_path(tmp_path):
    store = _store(tmp_path)
    result = ingest_prompt(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "带transcript",
            "transcript_path": "/home/u/.claude/projects/x/abc.jsonl",
        },
        store=store,
        capture_id="cap-1",
    )
    row = store.get_prompt(result["prompt_id"])
    assert row["transcript_path"] == "/home/u/.claude/projects/x/abc.jsonl"
    # metadata_json 保留完整原始 event
    md = json.loads(row["metadata_json"])
    assert md["transcript_path"] == "/home/u/.claude/projects/x/abc.jsonl"


def test_ingest_prompt_disabled_config_skips(tmp_path):
    from jfox.global_config import PromptCaptureConfig

    store = _store(tmp_path)
    result = ingest_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "x"},
        store=store,
        config=PromptCaptureConfig(enabled=False),
    )
    assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# PromptCaptureConfig
# ---------------------------------------------------------------------------


def test_prompt_capture_config_defaults():
    from jfox.global_config import PromptCaptureConfig

    cfg = PromptCaptureConfig()
    assert cfg.enabled is True
    assert cfg.spool_dir is None  # None → 默认路径
    assert cfg.endpoint_timeout_seconds == 1
    assert cfg.max_payload_bytes == 16 * 1024 * 1024
    assert cfg.max_spool_bytes == 1024 * 1024 * 1024
    assert cfg.retain_raw_event is True
    assert "~/.claude/projects" in cfg.transcript_roots


def test_prompt_capture_config_from_dict():
    from jfox.global_config import PromptCaptureConfig

    cfg = PromptCaptureConfig.from_dict(
        {"enabled": False, "max_payload_bytes": 1024, "transcript_roots": ["/custom"]}
    )
    assert cfg.enabled is False
    assert cfg.max_payload_bytes == 1024
    assert cfg.transcript_roots == ["/custom"]


def test_prompt_capture_config_from_empty():
    from jfox.global_config import PromptCaptureConfig

    cfg = PromptCaptureConfig.from_dict(None)
    assert cfg.enabled is True


def test_global_config_includes_prompt_capture():
    from jfox.global_config import GlobalConfig

    gc = GlobalConfig()
    assert hasattr(gc, "prompt_capture")
    d = gc.to_dict()
    assert "prompt_capture" in d


def test_global_config_from_dict_inherits_legacy_enabled():
    """没有 prompt_capture 时从旧 fragment_capture.enabled 继承。"""
    from jfox.global_config import GlobalConfig

    gc = GlobalConfig.from_dict({"fragment_capture": {"enabled": False}, "knowledge_bases": {}})
    assert gc.prompt_capture.enabled is False


def test_global_config_from_dict_keeps_prompt_capture():
    from jfox.global_config import GlobalConfig

    gc = GlobalConfig.from_dict({"prompt_capture": {"enabled": False}, "knowledge_bases": {}})
    assert gc.prompt_capture.enabled is False
