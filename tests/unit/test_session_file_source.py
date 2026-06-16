from pathlib import Path

from jfox.auto_summary.scanner import SessionFile


def test_default_source_is_claude():
    sf = SessionFile(
        session_id="x", project_dir_name="p", path=Path("/a.jsonl"), mtime=0.0, size_bytes=10
    )
    assert sf.source == "claude"


def test_source_can_be_kimi():
    sf = SessionFile(
        session_id="x",
        project_dir_name="p",
        path=Path("/a.jsonl"),
        mtime=0.0,
        size_bytes=10,
        source="kimi",
    )
    assert sf.source == "kimi"
