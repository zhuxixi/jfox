import os

from jfox.auto_summary.kimi_source import KimiCodeSource
from jfox.global_config import AutoSummaryConfig


def _make_session(root, wd, sess, wire_text="x" * 6000, age_secs=3600):
    wire = root / wd / sess / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True, exist_ok=True)
    wire.write_text(wire_text, encoding="utf-8")
    old = os.path.getmtime(wire) - age_secs
    os.utime(wire, (old, old))
    return wire


def test_iter_sessions_finds_wire_jsonl(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1")
    src = KimiCodeSource(tmp_path)
    found = list(src.iter_sessions(AutoSummaryConfig()))
    assert len(found) == 1
    assert found[0].source == "kimi"
    assert found[0].session_id == "s1"
    assert found[0].project_dir_name == "wd_jfox_abc"
    assert found[0].path.name == "wire.jsonl"


def test_iter_sessions_skips_too_recent(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1", age_secs=10)  # 未静默
    src = KimiCodeSource(tmp_path)
    assert list(src.iter_sessions(AutoSummaryConfig())) == []


def test_iter_sessions_skips_too_small(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1", wire_text="x" * 100)  # <5KB
    src = KimiCodeSource(tmp_path)
    assert list(src.iter_sessions(AutoSummaryConfig())) == []


def test_iter_sessions_ignores_non_session_dirs(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1")
    (tmp_path / "random_dir").mkdir()  # 非 wd_ 开头
    src = KimiCodeSource(tmp_path)
    assert len(list(src.iter_sessions(AutoSummaryConfig()))) == 1
