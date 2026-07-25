"""synthesize_anchor 的 dedup hook：命中则不存盘、记 duplicate。"""

from datetime import datetime
from unittest.mock import patch

from jfox.gem_synth import synthesizer
from jfox.gem_synth.dedup import DedupHit, _clean_candidate_content
from jfox.global_config import GemSynthesisConfig
from jfox.models import GemLevel, Note, NoteType


def _existing_candidate():
    """构造一个 pending candidate 给 load_note_by_id 返回（_try_merge_delta guard 用）。"""
    return Note(
        id="cand-target",
        title="T",
        content="已有正文",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )


def _anchor():
    return {
        "fragment_id": 77,
        "session_id": "s1",
        "timestamp": "2026-07-12T00:00:00",
        "content": "ctx",
        "transcript_path": "/tmp/x.jsonl",
    }


def test_duplicate_hit_skips_save_and_marks_duplicate(tmp_path):
    # extract_turn_around 被 mock，transcript 文件不会被读，无需造（且避免 /tmp 在 Windows 不存在）
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
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("existing-id", "candidate", 0.99),
        ) as mcheck,
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


def test_target_kb_none_resolves_to_active_kb_name():
    """cfg.target_kb=None（生产默认配置）时，dedup_check/upsert_dedup 收到的应是
    解析后的具体 KB 名（config.base_dir.name），不是 None。

    回归 Finding 1：dedup_embeddings.kb 是 TEXT NOT NULL，且 dedup_check 的
    WHERE kb=? 绑 None 会匹配 0 行 → 永远检不到重复，整个 dedup 特征静默失效。"""
    import pathlib

    class FakeLog:
        def mark_duplicate(self, fid, dup_of):
            pass

        def mark_processed(self, **kw):
            pass

    fake_log = FakeLog()

    # 把 config.base_dir 钉到已知路径，其 .name 作期望的解析 KB 名
    from jfox.config import config

    fake_kb_name = "testkb_regression"
    original_base_dir = config.base_dir
    config.base_dir = pathlib.Path(f"/tmp/{fake_kb_name}")
    try:
        with (
            patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
            patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
            patch(
                "jfox.gem_synth.synthesizer.synthesize_with_llm",
                return_value={"title": "T", "content": "C", "confidence": 0.9},
            ),
            patch("jfox.gem_synth.synthesizer.dedup_check", return_value=None) as mcheck,
            patch("jfox.gem_synth.synthesizer._save_candidate_note", return_value="new-id"),
            patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert,
        ):
            from jfox.global_config import GemSynthesisConfig

            cfg = GemSynthesisConfig()
            cfg.dedup_enabled = True  # type: ignore[attr-defined]
            cfg.target_kb = None  # type: ignore[attr-defined]  # 关键：模拟生产默认配置
            result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)
    finally:
        config.base_dir = original_base_dir

    assert result is not None and result["candidate_note_id"] == "new-id"
    # dedup_check 第一参数必须是 str 且等于解析后的 KB 名，绝不能是 None
    check_kb = mcheck.call_args[0][0]
    assert isinstance(check_kb, str)
    assert check_kb == fake_kb_name
    # upsert_dedup 同理
    upsert_kb = mupsert.call_args[0][0]
    assert isinstance(upsert_kb, str)
    assert upsert_kb == fake_kb_name


def test_dedup_disabled_skips_both_check_and_upsert():
    """dedup_enabled=False 时完全跳过 dedup：既不查重也不入 dedup 库（spec §11 回原行为）。"""
    from jfox.global_config import GemSynthesisConfig

    class FakeLog:
        def mark_processed(self, **kw):
            pass

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = False  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch("jfox.gem_synth.synthesizer.dedup_check") as mcheck,
        patch("jfox.gem_synth.synthesizer._save_candidate_note", return_value="new-id"),
        patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert,
    ):
        result = synthesizer.synthesize_anchor(_anchor(), log=FakeLog(), cfg=cfg)

    assert result is not None and result["candidate_note_id"] == "new-id"
    mcheck.assert_not_called()  # 不查重
    mupsert.assert_not_called()  # 不入 dedup 库（关键：曾在此漏守卫）


def test_merge_appends_delta_section_and_recomputes_embedding():
    """有增量时：把 ## 补充 段插进 body（meta 之前），清洗后仍含 delta → embedding 真重算。

    fixture 带 _save_candidate_note 追加的元段（## 来源/置信度），贴近生产口径；
    断言 _clean_candidate_content 后 delta 仍在（否则 upsert_dedup 的 content_hash 不变、
    embedding 不重算——曾因此给 #309 增量对后续查重失明提供虚假信心）。"""
    existing = Note(
        id="20260725000000",
        title="Zima 双 Bot CR",
        content="## 双 Bot 工作流\ncc + kimi 轮询\n\n## 来源\n- 碎片 #1\n\n## 置信度\n0.9\n",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )
    delta = {"has_delta": True, "delta": "标签被移除≠审完", "conflict": None}
    anchor = {"fragment_id": 42, "timestamp": "2026-07-25T20:00:00"}

    with (
        patch("jfox.gem_synth.synthesizer.update_note") as mupdate,
        patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert,
    ):
        ok = synthesizer._merge_delta_into_candidate(existing, delta, anchor, "default")

    assert ok is True
    assert "## 补充（来自锚点 #42" in existing.content
    # delta 必须落在 _clean_candidate_content 保留的 body 内（插在 meta 之前），
    # 否则 content_hash 不变 → upsert_dedup 早退 → embedding 不重算（查重失明）
    cleaned = _clean_candidate_content(existing.content)
    assert "标签被移除≠审完" in cleaned
    mupdate.assert_called_once_with(existing, add_to_index=False)
    mupsert.assert_called_once()
    assert mupsert.call_args[0][0] == "default"
    assert mupsert.call_args[0][1] == "20260725000000"
    assert "标签被移除≠审完" in mupsert.call_args[0][3]


def test_merge_includes_conflict_marker():
    """LLM 标了矛盾时，追加段含 ⚠️ 矛盾 行。"""
    from datetime import datetime

    from jfox.models import GemLevel, Note, NoteType

    existing = Note(
        id="20260725000001",
        title="T",
        content="原结论",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )
    delta = {"has_delta": True, "delta": "B 主张 30min", "conflict": "与 X 的 60min 矛盾"}

    with (
        patch("jfox.gem_synth.synthesizer.update_note"),
        patch("jfox.gem_synth.synthesizer.upsert_dedup"),
    ):
        synthesizer._merge_delta_into_candidate(existing, delta, {}, "default")

    assert "⚠️ 矛盾" in existing.content
    assert "60min" in existing.content


def test_merge_returns_false_on_update_failure():
    """update_note 抛异常 → 返回 False（调用方降级 mark_duplicate）。"""
    from datetime import datetime

    from jfox.models import Note, NoteType

    existing = Note(
        id="x",
        title="T",
        content="c",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
    )
    with (
        patch("jfox.gem_synth.synthesizer.update_note", side_effect=RuntimeError("io")),
        patch("jfox.gem_synth.synthesizer.upsert_dedup"),
    ):
        ok = synthesizer._merge_delta_into_candidate(
            existing, {"has_delta": True, "delta": "d", "conflict": None}, {}, "default"
        )
    assert ok is False


# ---------------------------------------------------------------------------
# #309 增量合并：synthesize_anchor dedup 分支决策树
# ---------------------------------------------------------------------------


def _dup_log():
    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    return FakeLog()


def _patch_synth_upstream(score_note_type):
    """patch 掉 synthesize_anchor 上游（transcript/grounding/LLM）+ dedup_check 返回指定 hit。"""
    return (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", *score_note_type),
        ),
    )


def test_candidate_merge_band_triggers_merge_and_mark_merged():
    """candidate + 0.88–0.96 合并带 + merge 开 + 有增量 → 调 extract_delta、
    _merge、mark_merged（非 mark_duplicate）。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch(
            "jfox.gem_synth.synthesizer.extract_delta_with_llm",
            return_value={"has_delta": True, "delta": "新增点", "conflict": None},
        ),
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=_existing_candidate()),
        patch(
            "jfox.gem_synth.synthesizer._merge_delta_into_candidate", return_value=True
        ) as mmerge,
    ):
        fake_log = _dup_log()
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is None  # 合并不产新 candidate
    assert ("merged", 77, "cand-target") in fake_log.calls
    mmerge.assert_called_once()


def test_permanent_hit_still_skips_no_delta_call():
    """命中 permanent → mark_duplicate，不调 extract_delta（scope 外）。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("permanent", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()
    mmerge.assert_not_called()


def test_near_verbatim_skips_delta_call():
    """candidate 但 score≥0.96（近逐字）→ mark_duplicate，省 LLM 不调 extract_delta。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.97))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()


def test_merge_disabled_skips_delta_call():
    """dedup_merge_enabled=False → candidate 合并带也走 mark_duplicate，不调 delta LLM。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = False  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()


def test_delta_llm_returns_none_degrades_to_skip():
    """delta LLM 失败 → 降级 mark_duplicate。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=_existing_candidate()),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm", return_value=None),
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mmerge.assert_not_called()


def test_delta_has_delta_false_skips():
    """LLM 判无实质增量 → mark_duplicate（不合并）。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=_existing_candidate()),
        patch(
            "jfox.gem_synth.synthesizer.extract_delta_with_llm",
            return_value={"has_delta": False, "delta": "", "conflict": None},
        ),
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mmerge.assert_not_called()


def test_delta_load_race_degrades_to_skip():
    """命中后 load_note_by_id 返回 None（已被删/reject）→ mark_duplicate 降级。"""
    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    p1, p2, p3, p4 = _patch_synth_upstream(("candidate", 0.91))
    with (
        p1,
        p2,
        p3,
        p4,
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=None),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = _dup_log()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()  # load 失败就不调 delta LLM
