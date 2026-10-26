"""pi session 解析纯函数。"""

import json

import pytest

from jfox.auto_summary.pi_extractor import (
    active_branch,
    dialog_from_branch,
    extract_pi_dialog,
    model_from_branch,
    parse_pi_header,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

HEADER = {
    "type": "session",
    "version": 3,
    "id": "sess-1",
    "timestamp": "2026-10-19T00:00:00.000Z",
    "cwd": "/repo/proj",
}


def _msg(mid, parent, role, text, ts="2026-10-19T00:01:00.000Z", model=None):
    msg = {"role": role, "content": [{"type": "text", "text": text}]}
    if model:
        msg["model"] = model
    return {"type": "message", "id": mid, "parentId": parent, "timestamp": ts, "message": msg}


def test_header_requires_session_type_and_id():
    assert parse_pi_header(json.dumps(HEADER))["id"] == "sess-1"
    assert parse_pi_header(json.dumps({"type": "message", "id": "x"})) is None
    assert parse_pi_header("not json") is None


def test_active_branch_follows_parent_chain():
    entries = [
        HEADER,
        _msg("a", None, "user", "hello"),
        _msg("b", "a", "assistant", "hi"),
        _msg("c", "a", "assistant", "abandoned"),
        _msg("d", "b", "user", "next"),
    ]
    assert [e["id"] for e in active_branch(entries)] == ["a", "b", "d"]


def test_active_branch_falls_back_on_broken_chain():
    entries = [HEADER, _msg("a", None, "user", "hello"), _msg("b", "missing", "assistant", "x")]
    assert active_branch(entries) == entries


def test_dialog_reads_nested_message_and_drops_thinking():
    branch = [
        HEADER,
        _msg("a", None, "user", "hello"),
        {
            "type": "message",
            "id": "b",
            "parentId": "a",
            "timestamp": "2026-10-19T00:02:00.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret"},
                    {"type": "text", "text": "answer"},
                    {"type": "toolCall", "name": "bash"},
                ],
            },
        },
        {
            "type": "message",
            "id": "c",
            "parentId": "b",
            "message": {"role": "toolResult", "content": "x"},
        },
    ]
    text, users, assistants, ended, truncated = dialog_from_branch(branch)
    assert "hello" in text and "answer" in text and "secret" not in text
    assert (users, assistants) == (1, 1)
    assert ended == "2026-10-19T00:02:00.000Z"
    assert truncated is False


def test_model_takes_last_model_change():
    branch = [
        HEADER,
        {"type": "model_change", "provider": "a", "modelId": "m1"},
        {"type": "model_change", "provider": "b", "modelId": "m2"},
    ]
    assert model_from_branch(branch) == "b/m2"


def test_extract_dialog_from_file(tmp_path):
    p = tmp_path / "view_abc.jsonl"
    rows = [
        HEADER,
        {"type": "model_change", "provider": "x", "modelId": "y"},
        _msg("a", None, "user", "hello"),
        _msg("b", "a", "assistant", "hi"),
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    result = extract_pi_dialog(p)
    assert result.cwd == "/repo/proj"
    assert result.project_dir_name == "proj"
    assert result.user_turn_count == 1 and result.assistant_turn_count == 1
    assert result.started_at == HEADER["timestamp"]
    assert result.ended_at == "2026-10-19T00:01:00.000Z"
    assert result.agent_model == "x/y"


def test_model_ignores_abandoned_branch():
    """分支会话中放弃分支的 model_change 不应被当作会话模型。"""
    entries = [
        HEADER,
        {
            "type": "model_change",
            "id": "mc1",
            "parentId": None,
            "provider": "keep",
            "modelId": "kept",
        },
        _msg("a", "mc1", "user", "hello"),
        _msg("b", "a", "assistant", "hi"),
        {
            "type": "model_change",
            "id": "mc2",
            "parentId": "a",
            "provider": "abandoned",
            "modelId": "stale",
        },
        _msg("c", "b", "user", "next"),
    ]
    # 文件顺序取最后一条会拿到放弃分支的模型（错误答案）
    assert model_from_branch(entries) == "abandoned/stale"
    # 活跃分支只含 mc1 / a / b / c
    assert model_from_branch(active_branch(entries)) == "keep/kept"


def test_extract_prefers_active_branch_model(tmp_path):
    p = tmp_path / "view_branch.jsonl"
    rows = [
        HEADER,
        {
            "type": "model_change",
            "id": "mc1",
            "parentId": None,
            "provider": "keep",
            "modelId": "kept",
        },
        _msg("a", "mc1", "user", "hello"),
        _msg("b", "a", "assistant", "hi"),
        {
            "type": "model_change",
            "id": "mc2",
            "parentId": "a",
            "provider": "abandoned",
            "modelId": "stale",
        },
        _msg("c", "b", "user", "next"),
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert extract_pi_dialog(p).agent_model == "keep/kept"


def test_extract_falls_back_when_branch_has_no_model_change(tmp_path):
    p = tmp_path / "view_nomc.jsonl"
    rows = [HEADER, _msg("a", None, "user", "hello"), _msg("b", "a", "assistant", "hi")]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert extract_pi_dialog(p).agent_model is None
