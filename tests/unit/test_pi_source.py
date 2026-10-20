"""pi session 扫描：两类根目录、过滤、blocklist、同 id 去重。"""

import json
import os
import time

import pytest

from jfox.auto_summary.pi_source import PiCodeSource, iter_pi_session_files
from jfox.global_config import AutoSummaryConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write(path, sid, cwd="/repo/proj", pad=6000):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "type": "session",
        "version": 3,
        "id": sid,
        "timestamp": "2026-10-19T00:00:00Z",
        "cwd": cwd,
    }
    msg = {
        "type": "message",
        "id": "m1",
        "parentId": None,
        "timestamp": "2026-10-19T00:01:00Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }
    path.write_text(json.dumps(header) + "\n" + json.dumps(msg) + "\n" + "x" * pad, encoding="utf-8")
    old = time.time() - 3600
    os.utime(path, (old, old))


def test_scans_official_two_level_layout(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "--repo-proj--" / "t1_uuid-1.jsonl", "uuid-1")
    found = list(iter_pi_session_files([root], AutoSummaryConfig()))
    assert [s.session_id for s in found] == ["uuid-1"]
    assert found[0].agent == "pi-coding-agent"
    assert found[0].project_dir_name == "proj"


def test_scans_agent_board_flat_layout_with_view_names(tmp_path):
    root = tmp_path / "agent-board" / "sessions"
    _write(root / "view_abc.jsonl", "uuid-2", cwd="/repo/jfox")
    found = list(iter_pi_session_files([root], AutoSummaryConfig()))
    assert found[0].session_id == "uuid-2"
    assert found[0].project_dir_name == "jfox"


def test_skips_blocklisted_cwd(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid3.jsonl", "uuid-3", cwd="/tmp/jfox-auto-summary-runs/x")
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_skips_small_files(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid4.jsonl", "uuid-4", pad=10)
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_skips_non_header_files(tmp_path):
    root = tmp_path / "sessions"
    p = root / "a" / "bad.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("x" * 6000, encoding="utf-8")
    old = time.time() - 3600
    os.utime(p, (old, old))
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_dedupes_same_id_keeping_newest(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_new.jsonl", "uuid-5")
    _write(root / "b" / "t_old.jsonl", "uuid-5")
    old = time.time() - 7200
    os.utime(root / "b" / "t_old.jsonl", (old, old))
    found = list(iter_pi_session_files([root], AutoSummaryConfig()))
    assert len(found) == 1
    assert found[0].path.name == "t_new.jsonl"


def test_extract_dialog_delegates(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid6.jsonl", "uuid-6")
    source = PiCodeSource([root])
    sf = list(source.iter_sessions(AutoSummaryConfig()))[0]
    result = source.extract_dialog(sf)
    assert result.cwd == "/repo/proj"
    assert result.user_turn_count == 1
