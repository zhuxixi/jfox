"""synthesizer 编排测试（mock transcript/grounding/llm/save）。"""

from unittest.mock import MagicMock, patch

from jfox.gem_synth.store import SynthesisLog
from jfox.gem_synth.synthesizer import synthesize_anchor


def _anchor(frag_id, tmp_path):
    return {
        "fragment_id": frag_id,
        "session_id": "s1",
        "timestamp": "2026-06-21 14:30:00",
        "content": "不对，应该用 patch",
        "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {"session_id": "s1"},
    }


def test_synthesize_anchor_produces_candidate_note(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    fake_llm = {
        "title": "用 patch 而非 sed",
        "content": "## 知识\n改文件优先 patch",
        "confidence": 0.85,
        "knowledge_type": "procedural",
        "grounded_by": ["补丁规范"],
    }
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文X"),
        patch(
            "jfox.gem_synth.synthesizer.fetch_grounding",
            return_value=[{"title": "补丁规范", "content": "y"}],
        ),
        patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=fake_llm),
        patch(
            "jfox.gem_synth.synthesizer._save_candidate_note",
            return_value="candidate_20260621143000",
        ),
        # MagicMock cfg 使 getattr(cfg,"dedup_enabled",True) 为真 → 进入 dedup hook；
        # 不 mock 会触发真 embedding daemon 调用 + 写 ~/.zettelkasten/synthesis_log.db
        patch("jfox.gem_synth.synthesizer.dedup_check", return_value=None),
        patch("jfox.gem_synth.synthesizer.upsert_dedup"),
    ):
        result = synthesize_anchor(_anchor(42, tmp_path), log=log, cfg=MagicMock(grounding_top_k=5))
    assert result is not None
    assert result["candidate_note_id"] == "candidate_20260621143000"
    assert result["title"] == "用 patch 而非 sed"
    assert log.is_processed(42) is True


def test_synthesize_anchor_skips_when_llm_returns_none(tmp_path):
    """LLM 返 None → mark_failed('llm synthesis failed')，is_processed=True（不重试）"""
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=None),
    ):
        result = synthesize_anchor(_anchor(43, tmp_path), log=log, cfg=MagicMock(grounding_top_k=5))
    assert result is None
    assert log.is_processed(43) is True  # 失败也记账，下轮不重试
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 43 and "llm" in f["fail_reason"].lower() for f in failed)


def test_synthesize_anchor_skips_when_no_transcript(tmp_path):
    """无 transcript_path → mark_failed('no transcript_path')"""
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    a = _anchor(44, tmp_path)
    a["transcript_path"] = None
    assert synthesize_anchor(a, log=log, cfg=MagicMock(grounding_top_k=5)) is None
    assert log.is_processed(44) is True
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 44 and "transcript" in f["fail_reason"] for f in failed)


def test_synthesize_marks_failed_when_no_transcript(tmp_path):
    """无 transcript_path → mark_failed，不重试"""
    log = SynthesisLog(db_path=tmp_path / "s.db")
    anchor = {
        "fragment_id": 44,
        "session_id": "s",
        "timestamp": "t",
        "content": "x",
        "transcript_path": None,
        "metadata": {},
    }
    result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), stop_event=None)
    assert result is None
    assert log.is_processed(44) is True  # failed 也算已处理
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 44 and "transcript" in f["fail_reason"] for f in failed)
    log.close()


def test_synthesize_marks_failed_when_llm_none(tmp_path):
    """LLM 返 None → mark_failed('llm ...')"""
    log = SynthesisLog(db_path=tmp_path / "s.db")
    anchor = {
        "fragment_id": 45,
        "session_id": "s",
        "timestamp": "t",
        "content": "x",
        "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {},
    }
    (tmp_path / "t.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":"x"},"timestamp":"t","uuid":"u"}',
        encoding="utf-8",
    )
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=None),
    ):
        result = synthesize_anchor(
            anchor, log=log, cfg=MagicMock(grounding_top_k=5), stop_event=None
        )
    assert result is None
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 45 and "llm" in f["fail_reason"].lower() for f in failed)
    log.close()


def test_synthesize_handles_non_numeric_confidence(tmp_path):
    """LLM 返回非数值 confidence 不应崩（safe float 回退）"""
    from jfox.gem_synth.synthesizer import _safe_float

    assert _safe_float("high") == 0.0
    assert _safe_float(0.85) == 0.85
    assert _safe_float(None) == 0.0
    assert _safe_float("0.9") == 0.9
