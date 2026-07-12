"""synthesize_anchor 的 dedup hook：命中则不存盘、记 duplicate。"""

from unittest.mock import patch

from jfox.gem_synth import synthesizer


def _anchor():
    return {
        "fragment_id": 77,
        "session_id": "s1",
        "timestamp": "2026-07-12T00:00:00",
        "content": "ctx",
        "transcript_path": "/tmp/x.jsonl",
    }


def test_duplicate_hit_skips_save_and_marks_duplicate(tmp_path):
    # 造一个空 transcript 让 extract_turn_around 返回非空
    import json
    import pathlib

    pathlib.Path("/tmp/_synth_test.jsonl").write_text(
        json.dumps({"type": "user", "content": "hello"}) + "\n", encoding="utf-8"
    )
    _anchor()["transcript_path"] = "/tmp/_synth_test.jsonl"

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_failed(self, fid, reason):
            self.calls.append(("fail", fid, reason))

        def mark_processed(self, **kw):
            self.calls.append(("ok", kw))

    fake_log = FakeLog()

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch("jfox.gem_synth.synthesizer.dedup_check", return_value="existing-id") as mcheck,
        patch("jfox.gem_synth.synthesizer._save_candidate_note") as msave,
    ):
        from jfox.global_config import GemSynthesisConfig

        cfg = GemSynthesisConfig()
        cfg.dedup_enabled = True  # type: ignore[attr-defined]
        cfg.target_kb = "default"  # type: ignore[attr-defined]
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is None
    assert ("dup", 77, "existing-id") in fake_log.calls
    msave.assert_not_called()  # 没存盘
    mcheck.assert_called_once()


def test_no_duplicate_proceeds_to_save(tmp_path):
    import pathlib

    pathlib.Path("/tmp/_synth_test.jsonl").write_text('{"content":"x"}\n', encoding="utf-8")
    _anchor()["transcript_path"] = "/tmp/_synth_test.jsonl"

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_processed(self, **kw):
            self.calls.append(("ok", kw))

    fake_log = FakeLog()
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch("jfox.gem_synth.synthesizer.dedup_check", return_value=None),
        patch("jfox.gem_synth.synthesizer._save_candidate_note", return_value="new-id"),
        patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert,
    ):
        from jfox.global_config import GemSynthesisConfig

        cfg = GemSynthesisConfig()
        cfg.dedup_enabled = True  # type: ignore[attr-defined]
        cfg.target_kb = "default"  # type: ignore[attr-defined]
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is not None and result["candidate_note_id"] == "new-id"
    # 存盘成功后入 dedup 库
    mupsert.assert_called_once()
