"""
测试类型: 单元测试
目标模块: jfox.auto_summary.ledger
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import json
from datetime import datetime, timedelta

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.ledger import Ledger, SessionStatus


@pytest.fixture
def tmp_ledger(tmp_path):
    return Ledger(path=tmp_path / "state.json", max_retries=3)


class TestLedger:
    def test_empty_ledger_has_no_entries(self, tmp_ledger):
        assert tmp_ledger.all_entries() == {}
        assert tmp_ledger.get("anything") is None
        assert tmp_ledger.is_done("anything") is False

    def test_record_success_persists(self, tmp_path):
        path = tmp_path / "s.json"
        led = Ledger(path=path)
        assert led.record_success("sid1", "proj1", "20260519100000")
        assert led.is_done("sid1")
        # reload & verify
        led2 = Ledger(path=path)
        entry = led2.get("sid1")
        assert entry is not None
        assert entry.status == SessionStatus.SUCCESS.value
        assert entry.note_id == "20260519100000"

    def test_record_skip_marks_done(self, tmp_ledger):
        tmp_ledger.record_skip("sid", "proj", "trivial chat")
        assert tmp_ledger.is_done("sid")
        entry = tmp_ledger.get("sid")
        assert entry.status == SessionStatus.SKIPPED.value
        assert entry.last_error == "trivial chat"

    def test_record_failure_increments_retry_and_promotes_to_permanent(self, tmp_ledger):
        # 第一次：transient
        tmp_ledger.record_failure("sid", "proj", "claude timeout")
        e1 = tmp_ledger.get("sid")
        assert e1.status == SessionStatus.FAILED_TRANSIENT.value
        assert e1.retry_count == 1
        assert tmp_ledger.is_done("sid") is False  # transient 不算了结

        # 第二次：仍 transient
        tmp_ledger.record_failure("sid", "proj", "again")
        e2 = tmp_ledger.get("sid")
        assert e2.status == SessionStatus.FAILED_TRANSIENT.value
        assert e2.retry_count == 2

        # 第三次：到达 max_retries=3，转 permanent
        tmp_ledger.record_failure("sid", "proj", "final")
        e3 = tmp_ledger.get("sid")
        assert e3.status == SessionStatus.FAILED_PERMANENT.value
        assert e3.retry_count == 3
        assert tmp_ledger.is_done("sid") is True

    def test_forget_removes_entry(self, tmp_ledger):
        tmp_ledger.record_success("sid", "proj", "n1")
        assert tmp_ledger.forget("sid") is True
        assert tmp_ledger.get("sid") is None
        assert tmp_ledger.forget("sid") is False  # 已经不在

    def test_prune_older_than(self, tmp_path):
        path = tmp_path / "s.json"
        old_ts = (datetime.now() - timedelta(days=40)).isoformat()
        new_ts = datetime.now().isoformat()
        # 直接构造数据并写盘，再重新加载
        raw = {
            "version": 1,
            "sessions": {
                "old": {
                    "project": "p",
                    "processed_at": old_ts,
                    "status": "success",
                    "note_id": "n1",
                    "retry_count": 0,
                    "last_error": None,
                },
                "new": {
                    "project": "p",
                    "processed_at": new_ts,
                    "status": "success",
                    "note_id": "n2",
                    "retry_count": 0,
                    "last_error": None,
                },
            },
        }
        path.write_text(json.dumps(raw), encoding="utf-8")

        led2 = Ledger(path=path)
        deleted = led2.prune_older_than(days=30)
        assert deleted == 1
        assert led2.get("old") is None
        assert led2.get("new") is not None

    def test_stats_counts_per_status(self, tmp_ledger):
        tmp_ledger.record_success("a", "p", "n")
        tmp_ledger.record_skip("b", "p", "x")
        tmp_ledger.record_failure("c", "p", "fail")

        stats = tmp_ledger.stats()
        assert stats[SessionStatus.SUCCESS.value] == 1
        assert stats[SessionStatus.SKIPPED.value] == 1
        assert stats[SessionStatus.FAILED_TRANSIENT.value] == 1
        assert stats[SessionStatus.FAILED_PERMANENT.value] == 0

    def test_corrupted_file_falls_back_to_empty(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")
        led = Ledger(path=path)
        assert led.all_entries() == {}
        # 写入仍然能工作
        assert led.record_success("sid", "p", "n")
