"""集成测试：pi session 端到端 scan → summarize（mock claude）。"""

import json
import os
from pathlib import Path

import pytest

from jfox.auto_summary import runner
from jfox.auto_summary.ledger import Ledger
from jfox.config import use_kb
from jfox.global_config import AutoSummaryConfig
from jfox.note import load_note_by_id
from tests.utils.temp_kb import temp_kb_registered

pytestmark = pytest.mark.integration


def _seed(root: Path, sid: str = "uuid-1", age_secs: int = 3600) -> Path:
    path = root / "view_abc.jsonl"
    rows = [
        {
            "type": "session",
            "version": 3,
            "id": sid,
            "timestamp": "2026-10-19T00:00:00Z",
            "cwd": "/repo/proj",
        },
        {"type": "model_change", "provider": "deepseek", "modelId": "deepseek-flash"},
        {
            "type": "message",
            "id": "m1",
            "parentId": None,
            "timestamp": "2026-10-19T00:01:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "fix bug"}]},
        },
        {
            "type": "message",
            "id": "m2",
            "parentId": "m1",
            "timestamp": "2026-10-19T00:02:00Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n" + "x" * 6000, encoding="utf-8")
    old = os.path.getmtime(path) - age_secs
    os.utime(path, (old, old))
    return path


def test_pi_session_end_to_end(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    session_path = _seed(root)

    with temp_kb_registered() as kb_name:
        cfg = AutoSummaryConfig(
            session_sources=["pi"], pi_session_dirs=[str(root)], target_kb=kb_name
        )
        ledger = Ledger(path=tmp_path / "ledger.json")

        pending = runner.scan_pending(cfg=cfg, ledger=ledger)
        assert [p.session_id for p in pending] == ["uuid-1"]

        monkeypatch.setattr(
            runner,
            "_invoke_claude",
            lambda extracted_dialog_text, cfg: json.dumps(
                {
                    "skip": False,
                    "title": "Pi 会话",
                    "topic": "",
                    "summary_md": "## 背景\n x",
                    "tags": [],
                }
            ),
        )
        result = runner.summarize_one(pending[0], cfg=cfg, ledger=ledger)
        assert result.outcome == runner.SummaryOutcome.SUCCESS

        with use_kb(kb_name):
            note = load_note_by_id(result.note_id)

        assert note.agent == "pi-coding-agent"
        assert note.session_file == str(session_path)
        assert note.agent_model == "deepseek/deepseek-flash"
        assert note.topic == "pi-coding-agent-session"
        assert ledger.get("pi:uuid-1") is not None
