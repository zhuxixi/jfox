"""Spool drain + 历史 backfill 测试。"""

import json

import pytest

from jfox.fragment.store import FragmentStore
from jfox.prompts.service import backfill_from_fragments, drain_spool
from jfox.prompts.store import PromptStore

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _prompt_store(tmp_path):
    return PromptStore(db_path=tmp_path / "fragments.db")


def _fragment_store(tmp_path):
    return FragmentStore(db_path=tmp_path / "fragments.db")


def _write_spool(spool_dir, capture_id, prompt="spool消息", session_id="s1"):
    """模拟 hook 写入的 spool 文件（已 atomic rename 完成）。"""
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "prompt": prompt,
        "jfox_capture_id": capture_id,
    }
    path = spool_dir / f"{capture_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# drain_spool
# ---------------------------------------------------------------------------


def test_drain_spool_imports_and_deletes(tmp_path):
    store = _prompt_store(tmp_path)
    spool_dir = tmp_path / "prompt-spool"
    spool_dir.mkdir()
    p = _write_spool(spool_dir, "cap-1", prompt="要恢复的消息")
    result = drain_spool(spool_dir, store)
    assert result["imported"] == 1
    assert result["failed"] == 0
    assert not p.exists()  # 导入成功后删除
    assert store.count_prompts() == 1
    assert store.get_prompt(1)["prompt"] == "要恢复的消息"


def test_drain_spool_idempotent(tmp_path):
    """重复 drain 不产生重复行（spool 已删，再跑是 no-op）。"""
    store = _prompt_store(tmp_path)
    spool_dir = tmp_path / "prompt-spool"
    spool_dir.mkdir()
    _write_spool(spool_dir, "cap-1")
    drain_spool(spool_dir, store)
    result2 = drain_spool(spool_dir, store)
    assert result2["imported"] == 0
    assert store.count_prompts() == 1


def test_drain_spool_preserves_long_text(tmp_path):
    store = _prompt_store(tmp_path)
    spool_dir = tmp_path / "prompt-spool"
    spool_dir.mkdir()
    long_text = "中文长文本" * 300
    _write_spool(spool_dir, "cap-1", prompt=long_text)
    drain_spool(spool_dir, store)
    assert store.get_prompt(1)["prompt"] == long_text


def test_drain_spool_keeps_invalid_file(tmp_path):
    """非法 JSON 文件保留（报告 failed），不静默删除。"""
    store = _prompt_store(tmp_path)
    spool_dir = tmp_path / "prompt-spool"
    spool_dir.mkdir()
    bad = spool_dir / "cap-bad.json"
    bad.write_text("not-json{", encoding="utf-8")
    result = drain_spool(spool_dir, store)
    assert result["failed"] == 1
    assert bad.exists()  # 保留供诊断


def test_drain_spool_multiple_files(tmp_path):
    store = _prompt_store(tmp_path)
    spool_dir = tmp_path / "prompt-spool"
    spool_dir.mkdir()
    _write_spool(spool_dir, "cap-1", prompt="第一条")
    _write_spool(spool_dir, "cap-2", prompt="第二条")
    _write_spool(spool_dir, "cap-3", prompt="第三条", session_id="s2")
    result = drain_spool(spool_dir, store)
    assert result["imported"] == 3
    assert store.count_prompts() == 3
    assert store.count_prompts(session_id="s1") == 2


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------


def _seed_legacy_fragments(fstore):
    """在 session_fragments 里种 UserPromptSubmit 历史（content 被截断）。"""
    long_prompt = "完整的历史prompt" * 100
    # metadata_json 保存完整原文；content 只有前 500 字符
    fid1 = fstore.insert(
        "legacy-s1",
        "correction",
        "UserPromptSubmit",
        content=long_prompt[:500],
        metadata={
            "hook_event_name": "UserPromptSubmit",
            "session_id": "legacy-s1",
            "prompt": long_prompt,
            "transcript_path": "/tmp/legacy.jsonl",
        },
    )
    fid2 = fstore.insert(
        "legacy-s1",
        "user_input",
        "UserPromptSubmit",
        content="普通历史",
        metadata={
            "hook_event_name": "UserPromptSubmit",
            "session_id": "legacy-s1",
            "prompt": "普通历史",
        },
    )
    # 非 UserPromptSubmit 行：不应被回填
    fstore.insert(
        "legacy-s1",
        "tool_call",
        "PostToolUse",
        content="tool output",
        metadata={"hook_event_name": "PostToolUse", "tool_response": "x"},
    )
    return fid1, fid2, long_prompt


def test_backfill_uses_full_metadata_prompt(tmp_path):
    fstore = _fragment_store(tmp_path)
    pstore = _prompt_store(tmp_path)
    fid1, _, long_prompt = _seed_legacy_fragments(fstore)

    result = backfill_from_fragments(pstore)
    assert result["imported"] == 2  # 2 条 UserPromptSubmit
    # 验证完整 prompt 被保存（不是截断 content）
    row = pstore.get_prompt(1)
    assert row["prompt"] == long_prompt
    assert len(row["prompt"]) == len(long_prompt)


def test_backfill_idempotent(tmp_path):
    fstore = _fragment_store(tmp_path)
    pstore = _prompt_store(tmp_path)
    _seed_legacy_fragments(fstore)
    r1 = backfill_from_fragments(pstore)
    r2 = backfill_from_fragments(pstore)
    assert r1["imported"] == 2
    assert r2["imported"] == 0
    assert r2["duplicates"] == 2
    assert pstore.count_prompts() == 2


def test_backfill_preserves_source_fragment_id(tmp_path):
    fstore = _fragment_store(tmp_path)
    pstore = _prompt_store(tmp_path)
    fid1, _, _ = _seed_legacy_fragments(fstore)
    backfill_from_fragments(pstore)
    row = pstore.get_prompt(1)
    assert row["source_fragment_id"] == fid1
    assert row["source"] == "backfill"


def test_backfill_preserves_transcript_path(tmp_path):
    fstore = _fragment_store(tmp_path)
    pstore = _prompt_store(tmp_path)
    _, _, _ = _seed_legacy_fragments(fstore)
    backfill_from_fragments(pstore)
    row = pstore.get_prompt(1)
    assert row["transcript_path"] == "/tmp/legacy.jsonl"


def test_backfill_skips_invalid_metadata(tmp_path):
    """非法 metadata_json / 缺 prompt 的行跳过并报告。"""
    import sqlite3

    _fragment_store(tmp_path)  # 确保表存在
    pstore = _prompt_store(tmp_path)
    # 直接写一条坏行
    conn = sqlite3.connect(str(tmp_path / "fragments.db"))
    conn.execute(
        "INSERT INTO session_fragments "
        "(session_id, fragment_type, source_event, content, metadata_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("bad-s", "user_input", "UserPromptSubmit", "x", "not-json{"),
    )
    conn.commit()
    conn.close()

    result = backfill_from_fragments(pstore)
    assert result["imported"] == 0
    assert result["invalid"] == 1


def test_backfill_empty_prompt_skipped(tmp_path):
    import sqlite3

    _fragment_store(tmp_path)  # 确保表存在
    pstore = _prompt_store(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "fragments.db"))
    conn.execute(
        "INSERT INTO session_fragments "
        "(session_id, fragment_type, source_event, content, metadata_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "empty-s",
            "user_input",
            "UserPromptSubmit",
            "",
            json.dumps(
                {"hook_event_name": "UserPromptSubmit", "session_id": "empty-s", "prompt": ""}
            ),
        ),
    )
    conn.commit()
    conn.close()

    result = backfill_from_fragments(pstore)
    assert result["imported"] == 0
    assert result["empty"] == 1
