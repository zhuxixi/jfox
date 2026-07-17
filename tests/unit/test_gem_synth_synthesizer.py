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


def test_strip_leading_h1_strips_title_duplicate():
    """content 以冗余 H1 开头（title 已在 frontmatter）→ 剥掉，剩正文"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# 标题\n\n正文") == "正文"
    assert _strip_leading_h1("# 标题\n正文") == "正文"  # H1 后无空行
    assert _strip_leading_h1("\n\n# 标题\n\n正文") == "正文"  # 前导空白行


def test_strip_leading_h1_noop_without_h1():
    """content 不以 H1 开头 → 原样返回"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("正文无 H1") == "正文无 H1"
    assert _strip_leading_h1("## 二级标题\n正文") == "## 二级标题\n正文"  # H2 不动
    assert _strip_leading_h1("") == ""


def test_strip_leading_h1_protects_all_h1_only():
    """content 仅一个 H1、剥后会空 → 回退原值，避免产出空正文"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# 只有一个标题\n") == "# 只有一个标题\n"
    assert _strip_leading_h1("# 只有一个标题") == "# 只有一个标题"  # 无尾换行：正则本就不匹配


def test_strip_leading_h1_only_first_leading():
    """只剥开头首个 H1；正文内后续 H1（3+H1 场景）保留——后者归 #319"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# A\n\n# B\n正文") == "# B\n正文"


def test_save_candidate_note_strips_leading_h1_from_content():
    """_save_candidate_note 把 LLM content 开头冗余 H1 剥掉，避免 to_markdown 双 H1。

    mock _persist_note 捕获 Note 对象，断言其 content 不以 H1 开头
    （title 已在 frontmatter，to_markdown 会前置 # title）。
    """
    from jfox.gem_synth.synthesizer import _save_candidate_note

    llm_result = {
        "title": "Vocable 客户端优先架构",
        "content": "# Vocable 架构取向：本地打包词库\n\n正文：规避服务器查询成本",
        "confidence": 0.7,
        "knowledge_type": "factual",
        "grounded_by": [],
    }
    anchor = {"fragment_id": 7, "session_id": "s1", "timestamp": "2026-07-17 00:00:00"}
    captured = {}

    def fake_persist(note):
        captured["note"] = note

    with patch("jfox.gem_synth.synthesizer._persist_note", side_effect=fake_persist):
        note_id = _save_candidate_note(llm_result, anchor)

    assert note_id is not None
    # content 开头不再是 H1（被 strip），正文保留
    assert not captured["note"].content.lstrip().startswith("# ")
    assert "规避服务器查询成本" in captured["note"].content
    # title 仍来自 frontmatter 字段，未被破坏
    assert captured["note"].title == "Vocable 客户端优先架构"
