from pathlib import Path
from unittest.mock import patch

from jfox.auto_summary.scanner import SessionFile
from jfox.auto_summary.sources import (
    get_sources,
    kimi_sessions_dir,
    session_key,
)
from jfox.global_config import AutoSummaryConfig


def test_session_key_format():
    sf = SessionFile(
        session_id="abc",
        project_dir_name="p",
        path=Path("/a"),
        mtime=0.0,
        size_bytes=1,
        source="kimi",
    )
    assert session_key(sf) == "kimi:abc"


def test_get_sources_skips_missing_dirs(tmp_path):
    cfg = AutoSummaryConfig(kimi_sessions_dir=str(tmp_path / "no-kimi"))
    with patch(
        "jfox.auto_summary.sources.default_claude_projects_dir", return_value=tmp_path / "no-claude"
    ):
        sources = get_sources(cfg)
    assert sources == []


def test_get_sources_includes_kimi_when_dir_exists(tmp_path):
    (tmp_path / "kimi").mkdir()
    cfg = AutoSummaryConfig(kimi_sessions_dir=str(tmp_path / "kimi"))
    with patch(
        "jfox.auto_summary.sources.default_claude_projects_dir", return_value=tmp_path / "no-claude"
    ):
        sources = get_sources(cfg)
    assert [s.name for s in sources] == ["kimi"]


def test_kimi_sessions_dir_default(monkeypatch):
    fake_home = Path("/fakehome")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    # 与实现侧保持一致，都走 resolve()，避免 Windows 下盘符差异导致断言失败
    expected = (fake_home / ".kimi-code" / "sessions").resolve()
    assert kimi_sessions_dir(AutoSummaryConfig()) == expected
