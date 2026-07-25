"""synthesize_anchor 的 dedup hook：命中则不存盘、记 duplicate。"""

from unittest.mock import patch

from jfox.gem_synth import synthesizer
from jfox.gem_synth.dedup import DedupHit


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
    """有增量时：追加 ## 补充 段、update_note 落盘、upsert_dedup 用合并后内容重算。"""
    from datetime import datetime

    from jfox.models import GemLevel, Note, NoteType

    existing = Note(
        id="20260725000000",
        title="Zima 双 Bot CR",
        content="## 双 Bot 工作流\ncc + kimi 轮询",
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
    # 正文被追加了 ## 补充 段 + delta 内容
    assert "## 补充（来自锚点 #42" in existing.content
    assert "标签被移除≠审完" in existing.content
    mupdate.assert_called_once_with(existing, add_to_index=False)
    # 重算 embedding 用的是合并后的正文（关键：内容已变）
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
