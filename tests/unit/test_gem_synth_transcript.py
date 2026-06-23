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


def test_iter_messages_skips_non_dict_lines(tmp_path):
    """非 dict 的 JSON 行（裸数字/数组）不应导致崩溃"""
    p = tmp_path / "t.jsonl"
    p.write_text(
        "12345\n"  # 裸数字
        '["array", "line"]\n'  # 数组
        '"string line"\n'  # 字符串
        + json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "ok"},
                "timestamp": "t",
                "uuid": "u",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    msgs = list(_iter_messages(p))
    assert len(msgs) == 1  # 只有那条 user dict 被 yield，非 dict 行跳过不崩


def test_extract_prefers_exact_substring_over_earlier_prefix(tmp_path):
    """早先消息仅共享前缀（不含完整锚点子串）时，精确子串匹配优先。

    锚点 >40 字符：早先消息以锚点前 40 字符开头但随后分歧——既满足前缀匹配、
    又因只共享前 40 字符而不含完整锚点子串；旧实现（`anchor in full or
    full.startswith(prefix)` + break）会因前缀短路而误取早先消息，新实现
    两轮先精确后前缀，命中后面那条。
    """
    p = tmp_path / "t.jsonl"
    # 长锚点（>40 字符），保证 anchor[:40] 是真前缀、非完整锚点
    anchor = "这是一个需要超过四十个字符长度的锚点文本用来区分精确子串匹配与前缀匹配两种策略的场景XYZ结束"
    assert len(anchor) > 40
    prefix_only = anchor[:40] + "AAA早先独有后缀"
    exact_msg = "用户提问：" + anchor + "，请问怎么办？"
    _write(
        p,
        [
            _user(prefix_only, "2026-06-21T06:24:00"),
            _assistant("r0", "2026-06-21T06:24:10"),
            _user(exact_msg, "2026-06-21T06:26:00"),
            _assistant("最终回复", "2026-06-21T06:26:10"),
        ],
    )
    turn = extract_turn_around(p, anchor_user_text=anchor)
    assert "最终回复" in turn
    assert "AAA早先独有后缀" not in turn
