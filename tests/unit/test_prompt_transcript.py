"""transcript context 测试：full/targeted/prompt_only 三种模式与 occurrence 定位。"""

import json

import pytest

from jfox.prompts.transcript import (
    read_transcript,
    select_context,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# 允许的 transcript 根目录（测试内虚拟）
ALLOWED_ROOT = "/allowed"


def _write_transcript(tmp_path, messages, name="t.jsonl"):
    """写一个 CC transcript JSONL 文件，返回路径。"""
    path = tmp_path / name
    lines = []
    for msg in messages:
        lines.append(json.dumps(msg, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _user_msg(text, uuid="u1"):
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "uuid": uuid,
    }


def _assistant_msg(text):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _simple_session():
    return [
        _user_msg("第一条消息", uuid="u1"),
        _assistant_msg("回复一"),
        _user_msg("第二条消息", uuid="u2"),
        _assistant_msg("回复二"),
        _user_msg("第三条消息", uuid="u3"),
        _assistant_msg("回复三"),
    ]


# ---------------------------------------------------------------------------
# read_transcript
# ---------------------------------------------------------------------------


def test_read_transcript_parses_user_assistant(tmp_path):
    path = _write_transcript(tmp_path, _simple_session())
    doc = read_transcript(path)
    assert doc.total_messages == 6
    assert doc.user_count == 3
    # user 消息有序号
    assert doc.user_texts == ["第一条消息", "第二条消息", "第三条消息"]


def test_read_transcript_skips_metadata_lines(tmp_path):
    """非 user/assistant 行（summary/ai-title 等）跳过。"""
    msgs = [
        {"type": "summary", "summary": "AI title"},
        _user_msg("实际消息"),
        {"type": "system", "content": "sys"},
    ]
    path = _write_transcript(tmp_path, msgs)
    doc = read_transcript(path)
    assert doc.user_count == 1


def test_read_transcript_missing_file_returns_empty(tmp_path):
    doc = read_transcript(tmp_path / "nonexistent.jsonl")
    assert doc.total_messages == 0


# ---------------------------------------------------------------------------
# select_context：full mode
# ---------------------------------------------------------------------------


def test_select_context_full_when_under_limit(tmp_path):
    path = _write_transcript(tmp_path, _simple_session())
    doc = read_transcript(path)
    targets = [
        {"prompt_id": 1, "prompt": "第二条消息", "transcript_user_index": 2},
    ]
    result = select_context(doc, targets, max_transcript_chars=100000)
    assert result.mode == "full"
    assert "第一条消息" in result.text  # 完整 session 在上下文里
    assert "第三条消息" in result.text


# ---------------------------------------------------------------------------
# select_context：targeted mode（超预算时降级）
# ---------------------------------------------------------------------------


def test_select_context_targeted_when_over_limit(tmp_path):
    path = _write_transcript(tmp_path, _simple_session())
    doc = read_transcript(path)
    targets = [
        {"prompt_id": 1, "prompt": "第二条消息", "transcript_user_index": 2},
    ]
    # 很小的预算 → 降级为 targeted（目标 prompt 周围的 bounded turns）
    result = select_context(doc, targets, max_transcript_chars=50)
    assert result.mode == "targeted"
    # 目标 prompt 上下文保留
    assert "第二条消息" in result.text


def test_select_context_targeted_includes_nearby_turns(tmp_path):
    path = _write_transcript(tmp_path, _simple_session())
    doc = read_transcript(path)
    targets = [
        {"prompt_id": 1, "prompt": "第二条消息", "transcript_user_index": 2},
    ]
    result = select_context(doc, targets, max_transcript_chars=50, turns_before=1, turns_after=1)
    assert result.mode == "targeted"
    # 前后各 1 个 turn：第一条消息（前）+ 回复二（后）应该在
    assert "第一条消息" in result.text
    assert "回复二" in result.text
    # 但第三条消息（超出 ±1 turn）不该在
    assert "第三条消息" not in result.text


# ---------------------------------------------------------------------------
# select_context：prompt_only mode
# ---------------------------------------------------------------------------


def test_select_context_prompt_only_when_doc_empty(tmp_path):
    from jfox.prompts.transcript import TranscriptDocument

    empty_doc = TranscriptDocument(messages=[], user_texts=[], user_indices=[])
    targets = [{"prompt_id": 1, "prompt": "只有prompt"}]
    result = select_context(empty_doc, targets, max_transcript_chars=100000)
    assert result.mode == "prompt_only"
    assert "只有prompt" in result.text


def test_select_context_prompt_only_when_occurrence_not_found(tmp_path):
    path = _write_transcript(tmp_path, _simple_session())
    doc = read_transcript(path)
    targets = [
        {"prompt_id": 1, "prompt": "不存在的消息", "transcript_user_index": None},
    ]
    result = select_context(doc, targets, max_transcript_chars=100000)
    assert result.mode == "prompt_only"


# ---------------------------------------------------------------------------
# occurrence 定位：重复文本不能永远命中第一条
# ---------------------------------------------------------------------------


def test_repeated_identical_prompts_consume_different_occurrences(tmp_path):
    """同一文本出现 3 次，3 个 target 应各自定位到不同 occurrence。"""
    msgs = [
        _user_msg("重复的问题", uuid="u1"),
        _assistant_msg("回答一"),
        _user_msg("重复的问题", uuid="u2"),
        _assistant_msg("回答二"),
        _user_msg("重复的问题", uuid="u3"),
        _assistant_msg("回答三"),
    ]
    path = _write_transcript(tmp_path, msgs)
    doc = read_transcript(path)
    # 三个 target 都指向相同文本但不同 index
    targets = [
        {"prompt_id": 1, "prompt": "重复的问题", "transcript_user_index": 1},
        {"prompt_id": 2, "prompt": "重复的问题", "transcript_user_index": 2},
        {"prompt_id": 3, "prompt": "重复的问题", "transcript_user_index": 3},
    ]
    result = select_context(doc, targets, max_transcript_chars=100000)
    assert result.mode == "full"
    # 三个都找到了各自的 occurrence
    assert len(result.found_occurrences) == 3
    assert result.found_occurrences[1] == 1  # prompt 1 → user index 1
    assert result.found_occurrences[2] == 2
    assert result.found_occurrences[3] == 3


# ---------------------------------------------------------------------------
# transcript root 安全校验
# ---------------------------------------------------------------------------


def test_path_outside_allowed_root_rejected(tmp_path):
    """transcript path 不在允许的根目录内 → 返回空文档（prompt-only 降级）。"""
    from jfox.prompts.transcript import read_transcript_safe

    outside = tmp_path / "outside" / "t.jsonl"
    outside.parent.mkdir()
    _write_transcript(tmp_path / "outside", _simple_session())
    doc = read_transcript_safe(outside, allowed_roots=[str(tmp_path / "allowed")])
    assert doc.total_messages == 0


def test_path_inside_allowed_root_accepted(tmp_path):
    from jfox.prompts.transcript import read_transcript_safe

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    path = _write_transcript(allowed, _simple_session())
    doc = read_transcript_safe(path, allowed_roots=[str(allowed)])
    assert doc.user_count == 3
