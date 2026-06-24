"""SynthesisLog SQLite 测试（临时库）。"""

from jfox.gem_synth.store import SynthesisLog


def _log(tmp_path):
    return SynthesisLog(db_path=tmp_path / "synthesis.db")


def test_is_processed_false_initially(tmp_path):
    assert _log(tmp_path).is_processed(42) is False


def test_mark_and_check(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(42, "candidate_20260621143000")
    assert log.is_processed(42) is True


def test_filter_unprocessed(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(1, "c1")
    log.mark_processed(3, "c3")
    assert log.filter_unprocessed([1, 2, 3, 4]) == [2, 4]


def test_idempotent_mark(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(1, "c1")
    log.mark_processed(1, "c1b")  # 重复不应崩
    assert log.is_processed(1) is True


def test_mark_failed_and_status_counts(tmp_path):
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_processed(1, "c1")
    log.mark_failed(2, "no transcript_path")
    log.mark_failed(3, "llm failed: 非 JSON")
    counts = log.status_counts()
    assert counts == {"success": 1, "failed": 2}
    log.close()


def test_list_failed(tmp_path):
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_failed(2, "no transcript_path")
    log.mark_processed(1, "c1")
    log.mark_failed(3, "llm failed")
    failed = log.list_failed()
    ids = [f["anchor_fragment_id"] for f in failed]
    assert 2 in ids and 3 in ids and 1 not in ids
    assert all(f["fail_reason"] for f in failed)
    log.close()


def test_failed_anchor_is_processed_not_retried(tmp_path):
    """failed 也算已处理 → filter_unprocessed 不返回它"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_failed(5, "boom")
    assert log.is_processed(5) is True
    assert log.filter_unprocessed([5, 6]) == [6]
    log.close()


def test_migration_adds_columns_to_old_table(tmp_path):
    """旧表（无 status/fail_reason 列）建后 SynthesisLog 能升级"""
    import sqlite3

    p = tmp_path / "old.db"
    conn = sqlite3.connect(str(p))
    conn.execute(
        "CREATE TABLE synthesis_log (anchor_fragment_id INTEGER PRIMARY KEY, "
        "candidate_note_id TEXT NOT NULL, synthesized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO synthesis_log (anchor_fragment_id, candidate_note_id) VALUES (1, 'c1')"
    )
    conn.commit()
    conn.close()
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=p)
    counts = log.status_counts()
    assert counts == {"success": 1}
    log.mark_failed(2, "x")
    assert log.status_counts() == {"success": 1, "failed": 1}
    log.close()
