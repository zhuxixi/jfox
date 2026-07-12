"""SynthesisLog.mark_duplicate + dup_of 列迁移单测。"""

from jfox.gem_synth.store import SynthesisLog


def test_mark_duplicate_records_status_and_dup_of(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    log.mark_duplicate(123, "20260712000000-abc")
    counts = log.status_counts()
    assert counts.get("duplicate") == 1
    # 该锚点已处理（不重试）
    assert log.is_processed(123) is True
    log.close()


def test_dup_of_migration_idempotent(tmp_path):
    db = tmp_path / "syn.db"
    SynthesisLog(db_path=db).close()
    # 第二次实例化触发 _maybe_migrate 再次 → 不应抛 duplicate column
    log2 = SynthesisLog(db_path=db)
    log2.mark_duplicate(456, "x")
    assert log2.status_counts().get("duplicate") == 1
    log2.close()
