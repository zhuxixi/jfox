"""
测试类型: 单元测试
目标模块: jfox.auto_summary.scanner
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import os
import time

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.scanner import (
    DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS,
    iter_session_files,
)


def _make_session(project_dir, name, size_bytes, mtime_offset_seconds=0):
    """在 project_dir 下创建一个指定大小的 jsonl，可设置 mtime 偏移（负值 = 过去）"""
    project_dir.mkdir(parents=True, exist_ok=True)
    p = project_dir / f"{name}.jsonl"
    p.write_bytes(b"x" * size_bytes)
    if mtime_offset_seconds != 0:
        ts = time.time() + mtime_offset_seconds
        os.utime(p, (ts, ts))
    return p


class TestIterSessionFiles:
    def test_returns_idle_sessions_within_size_window(self, tmp_path):
        proj = tmp_path / "C--Users-test-foo"
        # 30 分钟前修改的文件，大小 100KB
        _make_session(proj, "session-a", 100 * 1024, mtime_offset_seconds=-31 * 60)

        results = list(
            iter_session_files(
                claude_projects_dir=tmp_path,
                idle_threshold_minutes=30,
                max_session_size_mb=10,
                min_session_size_kb=5,
                skip_after_days=7,
            )
        )

        assert len(results) == 1
        assert results[0].session_id == "session-a"
        assert results[0].project_dir_name == "C--Users-test-foo"

    def test_skips_recently_modified(self, tmp_path):
        proj = tmp_path / "p1"
        _make_session(proj, "fresh", 50 * 1024, mtime_offset_seconds=-60)  # 1 分钟前

        results = list(iter_session_files(claude_projects_dir=tmp_path, idle_threshold_minutes=30))
        assert results == []

    def test_skips_too_small(self, tmp_path):
        proj = tmp_path / "p1"
        _make_session(proj, "tiny", 1024, mtime_offset_seconds=-60 * 60)  # 1KB

        results = list(
            iter_session_files(
                claude_projects_dir=tmp_path,
                idle_threshold_minutes=10,
                min_session_size_kb=5,
            )
        )
        assert results == []

    def test_skips_too_large(self, tmp_path):
        proj = tmp_path / "p1"
        # 11MB > 10MB 上限
        _make_session(proj, "huge", 11 * 1024 * 1024, mtime_offset_seconds=-60 * 60)

        results = list(
            iter_session_files(
                claude_projects_dir=tmp_path,
                idle_threshold_minutes=10,
                max_session_size_mb=10,
            )
        )
        assert results == []

    def test_skips_too_old(self, tmp_path):
        proj = tmp_path / "p1"
        _make_session(proj, "ancient", 100 * 1024, mtime_offset_seconds=-30 * 86400)  # 30 天

        results = list(
            iter_session_files(
                claude_projects_dir=tmp_path,
                idle_threshold_minutes=10,
                skip_after_days=7,
            )
        )
        assert results == []

    def test_blocklist_filters_isolated_runs_dir(self, tmp_path):
        # 假装一个由 auto-summary 自身产生的项目目录
        bad_proj = tmp_path / "C--Users-test--jfox-auto-summary-runs"
        good_proj = tmp_path / "C--Users-test-real"
        _make_session(bad_proj, "self", 100 * 1024, mtime_offset_seconds=-60 * 60)
        _make_session(good_proj, "real", 100 * 1024, mtime_offset_seconds=-60 * 60)

        results = list(
            iter_session_files(
                claude_projects_dir=tmp_path,
                idle_threshold_minutes=10,
                project_blocklist=DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS,
            )
        )
        names = {r.session_id for r in results}
        assert names == {"real"}

    def test_ignores_non_jsonl_files(self, tmp_path):
        proj = tmp_path / "p1"
        proj.mkdir()
        (proj / "notes.txt").write_text("hello", encoding="utf-8")
        (proj / "subdir").mkdir()  # 不应被当成 session 文件

        results = list(iter_session_files(claude_projects_dir=tmp_path, idle_threshold_minutes=0))
        assert results == []

    def test_missing_root_dir_yields_nothing(self, tmp_path):
        results = list(iter_session_files(claude_projects_dir=tmp_path / "does-not-exist"))
        assert results == []
