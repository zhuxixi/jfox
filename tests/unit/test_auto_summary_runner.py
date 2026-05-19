"""
测试类型: 单元测试
目标模块: jfox.auto_summary.runner（mock subprocess + filesystem）
预估耗时: < 2秒
依赖要求: 无网络，无 claude 二进制
"""

import json
import subprocess
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary import runner as runner_module
from jfox.auto_summary.ledger import Ledger, SessionStatus
from jfox.auto_summary.runner import (
    SummaryOutcome,
    _extract_object,
    _parse_claude_json,
    summarize_one,
)
from jfox.auto_summary.scanner import SessionFile
from jfox.global_config import AutoSummaryConfig

# ---------------------------------------------------------------------------
# JSON 解析单元测试
# ---------------------------------------------------------------------------


class TestParseClaudeJson:
    def test_envelope_with_result_field(self):
        envelope = {
            "type": "result",
            "result": '{"skip": false, "title": "测试", "topic": "t", "summary_md": "x", "tags": []}',
        }
        parsed = _parse_claude_json(json.dumps(envelope))
        assert parsed["title"] == "测试"
        assert parsed["skip"] is False

    def test_direct_inner_json(self):
        # claude 直接吐出内层对象（无 envelope）
        raw = '{"skip": true, "reason": "trivial", "title": "", "topic": "", "summary_md": "", "tags": []}'
        parsed = _parse_claude_json(raw)
        assert parsed["skip"] is True
        assert parsed["reason"] == "trivial"

    def test_inner_with_markdown_fence(self):
        envelope = {"result": '```json\n{"skip": false, "title": "a"}\n```'}
        parsed = _parse_claude_json(json.dumps(envelope))
        assert parsed["title"] == "a"

    def test_inner_with_prose_around_json(self):
        envelope = {"result": '好的，下面是结果：\n{"skip": false, "title": "hi"}\n谢谢'}
        parsed = _parse_claude_json(json.dumps(envelope))
        assert parsed["title"] == "hi"

    def test_completely_unparseable_raises(self):
        envelope = {"result": "I don't understand."}
        with pytest.raises(runner_module._ParseError):
            _parse_claude_json(json.dumps(envelope))

    def test_extract_object_finds_first_obj(self):
        text = 'junk before {"a": 1, "b": 2} junk after'
        obj = _extract_object(text)
        assert obj == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# summarize_one 行为测试（mock claude 调用 + mock 笔记写入）
# ---------------------------------------------------------------------------


def _make_session_jsonl(tmp_path, sid="abcd1234"):
    proj = tmp_path / "C--Users-test-proj"
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{sid}.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-05-19T10:00:00Z",
                        "cwd": "C:/work",
                        "gitBranch": "main",
                        "message": {"role": "user", "content": "帮我做一个 X"},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-19T10:00:30Z",
                        "message": {"role": "assistant", "content": "好的，我开始"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    return SessionFile(
        session_id=sid,
        project_dir_name=proj.name,
        path=p,
        mtime=p.stat().st_mtime,
        size_bytes=p.stat().st_size,
    )


@pytest.fixture
def fake_cfg(tmp_path):
    return AutoSummaryConfig(
        enabled=True,
        target_kb=None,
        claude_timeout_seconds=10,
        claude_binary=str(tmp_path / "fake-claude"),  # 不存在，让 _resolve_claude_binary 走 which
    )


@pytest.fixture
def ledger(tmp_path):
    return Ledger(path=tmp_path / "state.json", max_retries=3)


def _make_completed_proc(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=["claude", "-p"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_summarize_one_success(tmp_path, ledger, fake_cfg):
    sf = _make_session_jsonl(tmp_path)
    inner = {
        "skip": False,
        "title": "实现 auto-summary",
        "topic": "feature",
        "summary_md": "## 做了什么\n- xxx\n\n## 关键决策\n- yyy\n\n## 未决事项\n无",
        "tags": ["python", "knowledge-base"],
    }
    fake_stdout = json.dumps({"type": "result", "result": json.dumps(inner)})

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", return_value=_make_completed_proc(fake_stdout)),
        patch.object(runner_module, "_save_session_note", return_value="20260519T100000"),
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.SUCCESS
    assert result.note_id == "20260519T100000"
    assert result.title == "实现 auto-summary"
    entry = ledger.get(sf.session_id)
    assert entry is not None
    assert entry.status == SessionStatus.SUCCESS.value


def test_summarize_one_claude_marks_skip(tmp_path, ledger, fake_cfg):
    sf = _make_session_jsonl(tmp_path, sid="skip0001")
    inner = {
        "skip": True,
        "reason": "对话过短",
        "title": "",
        "topic": "",
        "summary_md": "",
        "tags": [],
    }
    fake_stdout = json.dumps({"result": json.dumps(inner)})

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", return_value=_make_completed_proc(fake_stdout)),
        patch.object(runner_module, "_save_session_note") as save_mock,
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.SKIPPED
    assert result.reason == "对话过短"
    save_mock.assert_not_called()
    entry = ledger.get(sf.session_id)
    assert entry.status == SessionStatus.SKIPPED.value


def test_summarize_one_claude_nonzero_exit_marks_failure(tmp_path, ledger, fake_cfg):
    sf = _make_session_jsonl(tmp_path, sid="fail0001")
    proc = _make_completed_proc("", returncode=2, stderr="boom")

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", return_value=proc),
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.FAILED  # transient on first attempt
    entry = ledger.get(sf.session_id)
    assert entry.status == SessionStatus.FAILED_TRANSIENT.value
    assert entry.retry_count == 1


def test_summarize_one_invalid_json_marks_failure(tmp_path, ledger, fake_cfg):
    sf = _make_session_jsonl(tmp_path, sid="parse001")
    proc = _make_completed_proc('{"result": "not a json object at all"}')

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", return_value=proc),
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.FAILED
    entry = ledger.get(sf.session_id)
    assert "parse error" in (entry.last_error or "")


def test_summarize_one_empty_dialog_skips_without_calling_claude(tmp_path, ledger, fake_cfg):
    proj = tmp_path / "C--Users-test-empty"
    proj.mkdir(parents=True)
    p = proj / "empty01.jsonl"
    p.write_text(
        json.dumps({"type": "permission-mode", "permissionMode": "x"}) + "\n",
        encoding="utf-8",
    )
    sf = SessionFile(
        session_id="empty01",
        project_dir_name=proj.name,
        path=p,
        mtime=p.stat().st_mtime,
        size_bytes=p.stat().st_size,
    )

    with patch.object(subprocess, "run") as run_mock:
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.SKIPPED
    run_mock.assert_not_called()


def test_summarize_one_empty_summary_md_marks_failure(tmp_path, ledger, fake_cfg):
    """claude 返回 skip=false 但 summary_md 为空白时应标记失败，不写笔记。"""
    sf = _make_session_jsonl(tmp_path, sid="empty_md")
    inner = {
        "skip": False,
        "title": "x",
        "topic": "y",
        "summary_md": "   \n  ",
        "tags": ["a"],
    }
    fake_stdout = json.dumps({"result": json.dumps(inner)})

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", return_value=_make_completed_proc(fake_stdout)),
        patch.object(runner_module, "_save_session_note") as save_mock,
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.FAILED
    save_mock.assert_not_called()
    entry = ledger.get(sf.session_id)
    assert "summary_md" in (entry.last_error or "")


def test_summarize_one_timeout_marks_failure(tmp_path, ledger, fake_cfg):
    sf = _make_session_jsonl(tmp_path, sid="timeout1")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=10)

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch.object(subprocess, "run", side_effect=raise_timeout),
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.FAILED
    entry = ledger.get(sf.session_id)
    assert "超时" in (entry.last_error or "")


# ---------------------------------------------------------------------------
# run_once orchestration tests
# ---------------------------------------------------------------------------


def test_run_once_recursion_guard_skips_when_inside_isolated_dir(tmp_path, fake_cfg):
    """关键安全测试：若当前 cwd 在 ~/.jfox-auto-summary-runs/ 内，run_once 应原地返回，
    避免 daemon 总结自己产生的 session 而陷入死循环。"""
    led = Ledger(path=tmp_path / "state.json")

    with (
        patch.object(runner_module, "is_running_inside_isolated_dir", return_value=True),
        patch.object(runner_module, "summarize_one") as summarize_mock,
        patch.object(runner_module, "scan_pending") as scan_mock,
    ):
        report = runner_module.run_once(cfg=fake_cfg, ledger=led)

    assert report.scanned == 0
    assert report.processed == 0
    summarize_mock.assert_not_called()
    scan_mock.assert_not_called()


def test_run_once_honors_max_per_tick(tmp_path, fake_cfg):
    """关键 DoS 防护测试：扫描出 5 个 session，max_per_tick=2 时只处理 2 个。"""
    from jfox.auto_summary.scanner import SessionFile

    led = Ledger(path=tmp_path / "state.json")
    fake_cfg.max_per_tick = 2

    fake_sessions = [
        SessionFile(
            session_id=f"sess{i:04d}",
            project_dir_name="proj",
            path=tmp_path / f"sess{i}.jsonl",
            mtime=0.0,
            size_bytes=10240,
        )
        for i in range(5)
    ]

    def fake_summarize(sf, cfg, ledger):
        return runner_module.SummaryResult(
            session_id=sf.session_id,
            outcome=SummaryOutcome.SUCCESS,
            note_id=f"n_{sf.session_id}",
        )

    with (
        patch.object(runner_module, "scan_pending", return_value=fake_sessions),
        patch.object(runner_module, "summarize_one", side_effect=fake_summarize) as summarize_mock,
    ):
        report = runner_module.run_once(cfg=fake_cfg, ledger=led)

    assert report.scanned == 5
    assert report.processed == 2
    assert report.success == 2
    assert summarize_mock.call_count == 2
    # 应处理前两个，按列表顺序
    assert [c.args[0].session_id for c in summarize_mock.call_args_list] == [
        "sess0000",
        "sess0001",
    ]


def test_run_once_dry_run_skips_summarize(tmp_path, fake_cfg):
    """dry_run 模式仍统计 scanned，但不调 summarize_one。"""
    from jfox.auto_summary.scanner import SessionFile

    led = Ledger(path=tmp_path / "state.json")
    fake_sessions = [
        SessionFile(
            session_id="x", project_dir_name="p", path=tmp_path / "x.jsonl", mtime=0, size_bytes=10
        )
    ]

    with (
        patch.object(runner_module, "scan_pending", return_value=fake_sessions),
        patch.object(runner_module, "summarize_one") as summarize_mock,
    ):
        report = runner_module.run_once(cfg=fake_cfg, ledger=led, dry_run=True)

    assert report.scanned == 1
    assert report.processed == 0
    summarize_mock.assert_not_called()
