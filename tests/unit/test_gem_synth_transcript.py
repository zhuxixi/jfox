"""transcript 一轮上下文提取测试（临时 jsonl）。"""

import json

from jfox.gem_synth.transcript import _iter_messages, extract_turn_around


def _write(path, messages):
    with open(path, "w") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def _user(text, ts):
    return {
        "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": ts,
        "uuid": f"u-{ts}",
    }


def _assistant(text, ts):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "思考"},
                {"type": "text", "text": text},
            ],
        },
        "timestamp": ts,
        "uuid": f"a-{ts}",
    }


def test_extract_turn_includes_anchor_and_response(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(
        p,
        [
            _user("第一条", "2026-06-21T06:25:00"),
            _assistant("回复1", "2026-06-21T06:25:10"),
            _user("锚点这条", "2026-06-21T06:26:00"),
            _assistant("回复锚点", "2026-06-21T06:26:10"),
            _user("下一条", "2026-06-21T06:27:00"),
        ],
    )
    turn = extract_turn_around(p, anchor_user_text="锚点这条")
    assert "锚点这条" in turn
    assert "回复锚点" in turn
    assert "下一条" not in turn
    assert "第一条" not in turn


def test_extract_turn_empty_if_anchor_not_found(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [_user("x", "2026-06-21T06:25:00")])
    assert extract_turn_around(p, anchor_user_text="不存在") == ""


def test_extract_turn_handles_missing_file(tmp_path):
    assert extract_turn_around(tmp_path / "nope.jsonl", anchor_user_text="x") == ""


def test_iter_messages_skips_non_conversation_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(
        p,
        [
            {"type": "ai-title", "aiTitle": "标题", "sessionId": "s"},
            _user("hi", "2026-06-21T06:25:00"),
        ],
    )
    msgs = list(_iter_messages(p))
    assert len(msgs) == 1  # 只 yield user/assistant
