"""
测试类型: 单元测试
目标模块: jfox.auto_summary.extractor
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import json

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.extractor import (
    DEFAULT_MAX_DIALOG_CHARS,
    extract_dialog,
)


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestExtractDialog:
    def test_strips_tool_use_and_attachments(self, tmp_path):
        path = tmp_path / "session.jsonl"
        _write_jsonl(
            path,
            [
                {"type": "last-prompt", "leafUuid": "x"},
                {"type": "permission-mode", "permissionMode": "bypassPermissions"},
                {
                    "type": "attachment",
                    "attachment": {"foo": "bar"},
                    "cwd": "C:/work",
                    "gitBranch": "main",
                },
                {
                    "type": "user",
                    "timestamp": "2026-05-19T13:47:35Z",
                    "message": {"role": "user", "content": "你好，帮我看下代码"},
                },
                {
                    "type": "assistant",
                    "timestamp": "2026-05-19T13:47:40Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "好的，我看一下。"},
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}},
                        ],
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-05-19T13:47:50Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "content": "..."},
                            {"type": "text", "text": "继续"},
                        ],
                    },
                },
            ],
        )

        result = extract_dialog(path)

        assert result.cwd == "C:/work"
        assert result.git_branch == "main"
        assert result.user_turn_count == 2
        assert result.assistant_turn_count == 1
        assert "你好，帮我看下代码" in result.dialog_text
        assert "好的，我看一下。" in result.dialog_text
        assert "继续" in result.dialog_text
        # tool_use / tool_result / attachment should not leak through
        assert "tool_use" not in result.dialog_text
        assert "tool_result" not in result.dialog_text
        assert "attachment" not in result.dialog_text
        assert result.started_at is not None
        assert result.ended_at is not None
        assert not result.truncated

    def test_drops_system_reminder_only_messages(self, tmp_path):
        path = tmp_path / "session.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "type": "user",
                    "timestamp": "2026-05-19T10:00:00Z",
                    "message": {
                        "role": "user",
                        "content": "<system-reminder>noise</system-reminder>",
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": "2026-05-19T10:00:01Z",
                    "message": {"role": "assistant", "content": "ok"},
                },
            ],
        )

        result = extract_dialog(path)
        assert result.user_turn_count == 0
        assert result.assistant_turn_count == 1
        assert "noise" not in result.dialog_text
        assert "ok" in result.dialog_text

    def test_drops_system_reminder_inside_multi_item_content(self, tmp_path):
        """system-reminder 与真实文本混在同一个 content 数组里时，应只剔除 system-reminder 段，
        保留用户的真实输入。回归保护：避免 system-reminder 噪音泄漏到 summary prompt。"""
        path = tmp_path / "session.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "type": "user",
                    "timestamp": "2026-05-19T10:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "<system-reminder>noise here</system-reminder>",
                            },
                            {"type": "text", "text": "实际的用户输入"},
                        ],
                    },
                },
            ],
        )

        result = extract_dialog(path)
        assert result.user_turn_count == 1
        assert "实际的用户输入" in result.dialog_text
        assert "noise here" not in result.dialog_text
        assert "system-reminder" not in result.dialog_text

    def test_truncation_when_too_long(self, tmp_path):
        path = tmp_path / "session.jsonl"
        big = "x" * 20000
        records = [
            {
                "type": "user",
                "timestamp": "2026-05-19T10:00:00Z",
                "message": {"role": "user", "content": big},
            }
            for _ in range(5)  # 5 * 20000 = 100k > 30k 默认上限
        ]
        _write_jsonl(path, records)

        result = extract_dialog(path)
        assert result.truncated
        assert len(result.dialog_text) <= DEFAULT_MAX_DIALOG_CHARS + 200  # +separator
        assert "省略中间" in result.dialog_text

    def test_handles_malformed_jsonl_lines(self, tmp_path):
        path = tmp_path / "session.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"type":"user","message":{"role":"user","content":"hello"}}\n')
            f.write("not json at all\n")
            f.write('{"type":"assistant","message":{"role":"assistant","content":"hi"}}\n')

        result = extract_dialog(path)
        assert result.user_turn_count == 1
        assert result.assistant_turn_count == 1
        assert "hello" in result.dialog_text
        assert "hi" in result.dialog_text

    def test_missing_file_returns_empty(self, tmp_path):
        result = extract_dialog(tmp_path / "no_such.jsonl")
        assert result.dialog_text == ""
        assert result.user_turn_count == 0
