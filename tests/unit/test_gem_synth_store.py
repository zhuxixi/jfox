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


def test_migration_idempotent_when_columns_exist(tmp_path):
    """列已存在时 _maybe_migrate 不应抛 duplicate column（多进程同时迁移场景）"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")  # 首次建表已含列
    # 再开一次 → _maybe_migrate 看到 status/fail_reason 已存在 → 跳过，不抛
    log2 = SynthesisLog(db_path=tmp_path / "s.db")
    log2.status_counts()  # 不抛即通过
    log.close()
    log2.close()


def test_mark_merged_writes_status_and_target(tmp_path):
    """mark_merged 记 status=merged + 目标 candidate_note_id，is_processed 仍 True。"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_merged(7, "cand-target-1")
    assert log.is_processed(7) is True  # merged 也算已处理，锚点不重试
    counts = log.status_counts()
    assert counts.get("merged") == 1
    log.close()


def test_mark_merged_then_duplicate_distinct_counts(tmp_path):
    """merged 与 duplicate 分别计数（status CLI 可观测合并 vs 跳过）。"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_merged(1, "t1")
    log.mark_duplicate(2, "t2")
    counts = log.status_counts()
    assert counts == {"merged": 1, "duplicate": 1}
    log.close()


def test_clear_duplicates_of_also_releases_merged(tmp_path):
    """reject/delete 目标 candidate 时，merged-into 它的锚点也要释放（#309），
    否则增量随 candidate 丢失且锚点永不重合成（silent data loss）。"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_duplicate(1, "cand-X")  # dup-of cand-X
    log.mark_merged(2, "cand-X")  # merged-into cand-X
    log.mark_merged(3, "cand-Y")  # 指向别的，不应被清
    log.clear_duplicates_of("cand-X")
    assert log.is_processed(1) is False  # dup-of cand-X 释放
    assert log.is_processed(2) is False  # merged-into cand-X 释放（#309 关键）
    assert log.is_processed(3) is True  # cand-Y 的不动
    log.close()
