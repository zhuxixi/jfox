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
