"""
测试类型: 单元测试
目标模块: jfox.auto_summary.runner（多来源合并扫描 + session_key 前缀）
预估耗时: < 1秒
依赖要求: 无网络，无 claude 二进制
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary import runner
from jfox.auto_summary.extractor import ExtractedDialog
from jfox.auto_summary.scanner import SessionFile


def test_scan_pending_merges_multiple_sources(monkeypatch):
    claude_sf = SessionFile("c1", "proj", Path("/c.jsonl"), 0.0, 10, "claude")
    kimi_sf = SessionFile("k1", "wd_jfox_x", Path("/k.jsonl"), 0.0, 10, "kimi")

    claude_src = MagicMock()
    claude_src.name = "claude"
    claude_src.iter_sessions.return_value = iter([claude_sf])
    kimi_src = MagicMock()
    kimi_src.name = "kimi"
    kimi_src.iter_sessions.return_value = iter([kimi_sf])

    monkeypatch.setattr(runner, "get_sources", lambda cfg: [claude_src, kimi_src])

    ledger = MagicMock()
    ledger.is_done.return_value = False
    pending = runner.scan_pending(ledger=ledger)
    keys = sorted(runner.session_key(sf) for sf in pending)
    assert keys == ["claude:c1", "kimi:k1"]


def test_summarize_one_uses_source_extract_and_prefixed_key(monkeypatch):
    sf = SessionFile("k1", "wd_jfox_x", Path("/k.jsonl"), 0.0, 10, "kimi")
    extracted = ExtractedDialog(dialog_text="hello", user_turn_count=1)
    # 直接 mock extract_dialog_for，隔离 summarize_one 的 key/skip 逻辑，
    # 不依赖真实 source 或目录存在（CI 无 ~/.kimi-code/sessions）
    monkeypatch.setattr(runner, "extract_dialog_for", lambda sf_, cfg: extracted)

    ledger = MagicMock()
    ledger.is_done.return_value = False
    ledger.get.return_value = None

    # 让 _invoke_claude 返回 skip，快速走 ledger.record_skip 分支验证 key
    monkeypatch.setattr(
        runner,
        "_invoke_claude",
        lambda extracted_dialog_text, cfg: '{"skip": true, "reason": "test"}',
    )
    result = runner.summarize_one(sf, ledger=ledger)
    assert ledger.record_skip.called
    called_key = ledger.record_skip.call_args[0][0]
    assert called_key == "kimi:k1"
    assert result.outcome.value == "skipped"
