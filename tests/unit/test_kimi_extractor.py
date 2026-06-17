import json

from jfox.auto_summary.kimi_source import KimiCodeSource
from jfox.auto_summary.scanner import SessionFile


def _session_file(tmp_path) -> SessionFile:
    wire = tmp_path / "wd_jfox_abc" / "session_s1" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    sess_dir = wire.parent.parent.parent  # session_s1
    state = {
        "createdAt": "2026-06-15T14:13:57.138Z",
        "updatedAt": "2026-06-15T14:42:02.478Z",
        "title": "demo",
    }
    (sess_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    rows = [
        {"type": "metadata", "created_at": 1781532837205, "app_version": "0.14.3"},
        {
            "type": "turn.prompt",
            "input": [{"type": "text", "text": "list open issues"}],
            "time": 1781532844222,
        },
        {
            "type": "context.append_message",
            "message": {"role": "user", "content": [{"type": "text", "text": "list open issues"}]},
            "time": 1781532844226,
        },
        {
            "type": "context.append_loop_event",
            "event": {"cwd": "/home/elling/git-repo/github/jfox"},
            "time": 1781532844230,
        },
        {
            "type": "context.append_message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "here are the issues"}],
            },
            "time": 1781532845000,
        },
        {"type": "usage.record", "tokens": 123, "time": 1781532845100},
    ]
    wire.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return SessionFile(
        session_id="s1",
        project_dir_name="wd_jfox_abc",
        path=wire,
        mtime=0.0,
        size_bytes=600,
        source="kimi",
    )


def test_extract_dialog_pulls_messages_and_skips_noise(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert "list open issues" in d.dialog_text
    assert "here are the issues" in d.dialog_text
    assert "usage.record" not in d.dialog_text  # 噪音过滤
    assert d.user_turn_count >= 1
    assert d.assistant_turn_count == 1


def test_extract_dialog_cwd_from_loop_event(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.cwd == "/home/elling/git-repo/github/jfox"


def test_extract_dialog_timestamps_from_state_json(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.started_at == "2026-06-15T14:13:57.138Z"
    assert d.ended_at == "2026-06-15T14:42:02.478Z"


def test_extract_dialog_state_missing_falls_back_to_wire_time(tmp_path):
    sf = _session_file(tmp_path)
    (sf.path.parent.parent.parent / "state.json").unlink()  # 删 state
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.started_at is not None  # 从首行 time(毫秒) 推导
    assert d.ended_at is not None


def test_extract_dialog_ignores_turn_prompt_uses_append_message(tmp_path):
    """issue-1/6: turn.prompt 不单独处理（依赖 append_message 独占 user），不重复计数。
    fixture 有 turn.prompt + append_message(user) 同文本 "list open issues"，
    只 append_message 记录一次 → user_turn_count=1，dialog 中该文本只出现一次。"""
    sf = _session_file(tmp_path)
    d = KimiCodeSource(tmp_path).extract_dialog(sf)
    assert d.user_turn_count == 1
    assert d.dialog_text.count("list open issues") == 1


def test_extract_dialog_keeps_repeated_short_user_text_across_turns(tmp_path):
    """issue-6: 不同轮次合法的相同短文本（如"继续"）不被误杀，各自保留"""
    wire = tmp_path / "wd_jfox_abc" / "session_s3" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    sess_dir = wire.parent.parent.parent
    (sess_dir / "state.json").write_text(
        json.dumps({"createdAt": "2026-06-15T14:00:00Z", "updatedAt": "2026-06-15T14:30:00Z"}),
        encoding="utf-8",
    )
    rows = []
    for ts in (1781532844226, 1781532900000, 1781532960000):
        rows.append(
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "继续"}],
                },
                "time": ts,
            }
        )
    wire.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sf = SessionFile(
        session_id="s3",
        project_dir_name="wd_jfox_abc",
        path=wire,
        mtime=0.0,
        size_bytes=600,
        source="kimi",
    )
    d = KimiCodeSource(tmp_path).extract_dialog(sf)
    # 三轮"继续"都应保留（不误杀）
    assert d.user_turn_count == 3
    assert d.dialog_text.count("继续") == 3


def test_extract_dialog_keeps_whitespace_only_text(tmp_path):
    """issue-8: 空白文本块也应保留，不被当无内容丢弃"""
    wire = tmp_path / "wd_jfox_abc" / "session_s4" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    sess_dir = wire.parent.parent.parent
    (sess_dir / "state.json").write_text(
        json.dumps({"createdAt": "2026-06-15T14:00:00Z", "updatedAt": "2026-06-15T14:30:00Z"}),
        encoding="utf-8",
    )
    rows = [
        {
            "type": "context.append_message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "   "}, {"type": "text", "text": "ok"}],
            },
            "time": 1781532844226,
        }
    ]
    wire.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sf = SessionFile(
        session_id="s4",
        project_dir_name="wd_jfox_abc",
        path=wire,
        mtime=0.0,
        size_bytes=600,
        source="kimi",
    )
    d = KimiCodeSource(tmp_path).extract_dialog(sf)
    assert "   " in d.dialog_text
    assert "ok" in d.dialog_text


def test_find_cwd_uses_real_nesting_depth_not_siblings():
    """issue-7: 宽顶层记录不应因兄弟节点多而误触深度上限"""
    from jfox.auto_summary.kimi_source import _find_cwd

    # 顶层有 30 个兄弟 dict，cwd 嵌在第 19 层
    record = {f"k{i}": {"v": i} for i in range(30)}
    nested = record
    for i in range(18):
        nested = {f"level_{i}": nested}
    # 把深层 cwd 放进 record 内部，而不是覆盖外部变量
    record["deep_root"] = nested
    record["deep_root"]["deep"] = {"cwd": "/deep/path"}
    assert _find_cwd(record) == "/deep/path"


def test_extract_dialog_truncates_long_dialog(tmp_path):
    """issue-2: 超长对话截断到 DEFAULT_MAX_DIALOG_CHARS，置 truncated 标记"""
    from jfox.auto_summary.extractor import DEFAULT_MAX_DIALOG_CHARS

    wire = tmp_path / "wd_jfox_abc" / "session_s2" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    sess_dir = wire.parent.parent.parent
    (sess_dir / "state.json").write_text(
        json.dumps({"createdAt": "2026-06-15T14:00:00Z", "updatedAt": "2026-06-15T14:30:00Z"}),
        encoding="utf-8",
    )
    big = "x" * (DEFAULT_MAX_DIALOG_CHARS + 5000)
    rows = [
        {
            "type": "context.append_message",
            "message": {"role": "user", "content": [{"type": "text", "text": big}]},
            "time": 1781532844226,
        }
    ]
    wire.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sf = SessionFile(
        session_id="s2",
        project_dir_name="wd_jfox_abc",
        path=wire,
        mtime=0.0,
        size_bytes=600,
        source="kimi",
    )
    d = KimiCodeSource(tmp_path).extract_dialog(sf)
    assert d.truncated is True
    assert len(d.dialog_text) <= DEFAULT_MAX_DIALOG_CHARS + 200
