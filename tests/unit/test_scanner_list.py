"""验证 list_session_files 返回完整列表"""

import os
import time
from pathlib import Path

from jfox.auto_summary.scanner import list_session_files


def _make_session(tmp_path: Path, name: str, size: int = 5000, age_minutes: int = 60) -> Path:
    """在 tmp_path 下创建一个 .jsonl 文件，size 字节，mtime 为 age_minutes 前"""
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    mtime = time.time() - age_minutes * 60
    os.utime(p, (mtime, mtime))
    return p


def test_list_returns_list_type(tmp_path):
    """返回类型应为 list"""
    _make_session(tmp_path, "abc.jsonl")
    result = list_session_files(
        claude_projects_dir=tmp_path,
        idle_threshold_minutes=1,
        min_session_size_kb=1,
        skip_after_days=0,
        now=time.time(),
    )
    assert isinstance(result, list)


def test_list_matches_iter(tmp_path):
    """list_session_files 应与 list(iter_session_files(...)) 结果一致"""
    _make_session(tmp_path, "s1.jsonl", size=3000, age_minutes=120)
    _make_session(tmp_path, "s2.jsonl", size=2000, age_minutes=30)
    kwargs = dict(
        claude_projects_dir=tmp_path,
        idle_threshold_minutes=1,
        min_session_size_kb=1,
        skip_after_days=0,
        now=time.time(),
    )
    from jfox.auto_summary.scanner import iter_session_files

    from_iter = list(iter_session_files(**kwargs))
    from_list = list_session_files(**kwargs)
    assert len(from_iter) == len(from_list)
    assert {s.session_id for s in from_iter} == {s.session_id for s in from_list}


def test_list_empty_dir(tmp_path):
    """空目录返回空列表"""
    result = list_session_files(
        claude_projects_dir=tmp_path,
        idle_threshold_minutes=1,
        skip_after_days=0,
        now=time.time(),
    )
    assert result == []
