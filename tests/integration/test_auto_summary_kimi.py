"""集成测试：Kimi session 端到端走 scan_pending → summarize_one（mock claude）。

交用户运行（标记 integration）。不调用真实 claude、不加载 embedding。
"""

import json
import os
from pathlib import Path

import pytest

from jfox.auto_summary import runner
from jfox.auto_summary.ledger import Ledger
from jfox.global_config import AutoSummaryConfig

pytestmark = pytest.mark.integration


def _seed_kimi_session(
    root: Path, wd="wd_jfox_abc", sess="session_s1", age_secs=3600, dialogue=True
):
    """在 root 下铺一份模拟的 Kimi session 目录树并写入 wire.jsonl + state.json。

    默认填充一段极简 user/assistant 对话，并把 wire.jsonl 的 mtime 回拨 age_secs 秒，
    使其满足 idle_threshold_minutes（默认 30 分钟）判定为「已结束」。
    额外补 6000 字节让文件越过 min_session_size_kb（默认 5KB）下限。
    """
    wire = root / wd / sess / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if dialogue:
        rows += [
            {
                "type": "turn.prompt",
                "input": [{"type": "text", "text": "fix the bug"}],
                "time": 1781532844222,
            },
            {
                "type": "context.append_message",
                "message": {"role": "user", "content": [{"type": "text", "text": "fix the bug"}]},
                "time": 1781532844226,
            },
            {
                "type": "context.append_message",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
                "time": 1781532845000,
            },
        ]
    else:
        rows.append({"type": "metadata", "created_at": 1, "app_version": "0.14.3"})
    wire.write_text("\n".join(json.dumps(r) for r in rows) + "x" * 6000, encoding="utf-8")
    (wire.parent.parent.parent / "state.json").write_text(
        json.dumps({"createdAt": "2026-06-15T14:00:00Z", "updatedAt": "2026-06-15T14:30:00Z"}),
        encoding="utf-8",
    )
    old = os.path.getmtime(wire) - age_secs
    os.utime(wire, (old, old))


def test_kimi_session_appears_in_scan(tmp_path, monkeypatch):
    _seed_kimi_session(tmp_path)
    cfg = AutoSummaryConfig(session_sources=["kimi"], kimi_sessions_dir=str(tmp_path))
    ledger = Ledger(path=tmp_path / "ledger.json")
    pending = runner.scan_pending(cfg=cfg, ledger=ledger)
    assert len(pending) == 1
    assert pending[0].source == "kimi"
    assert runner.session_key(pending[0]) == "kimi:s1"


def test_kimi_session_skip_flows_through_ledger(tmp_path, monkeypatch):
    _seed_kimi_session(tmp_path)
    cfg = AutoSummaryConfig(session_sources=["kimi"], kimi_sessions_dir=str(tmp_path))
    ledger = Ledger(path=tmp_path / "ledger.json")
    monkeypatch.setattr(
        runner,
        "_invoke_claude",
        lambda extracted_dialog_text, cfg: '{"skip": true, "reason": "empty"}',
    )
    report = runner.run_once(cfg=cfg, ledger=ledger)
    assert report.scanned == 1
    assert report.skipped == 1
    assert ledger.is_done("kimi:s1")
