"""
测试类型: 单元测试
目标模块: jfox.redirect（issue #435）
预估耗时: < 2秒
依赖要求: 无外部依赖（不加载 embedding 模型）

直接以显式 cfg 调用 scan_references / redirect_references，不经 CLI：
覆盖 frontmatter+正文同步重写、alias/anchor 保留、代码块排除（等长掩码
保持偏移）、归档来源扫描、重复标题 fail-closed、dry-run、backlinks 同步。
CLI 端到端路径见 TestRedirectCommand。
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app
from jfox.config import ZKConfig
from jfox.models import Note, NoteType
from jfox.note import load_note_by_id
from jfox.redirect import (
    _rewrite_body_links,
    redirect_references,
    scan_references,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()

OLD_ID = "20260828000001"
KEEP_ID = "20260828000002"
SRC_FM_ID = "20260828000003"
SRC_BODY_ID = "20260828000004"
SRC_BOTH_ID = "20260828000005"


def _write_note(
    cfg: ZKConfig,
    note_id: str,
    title: str,
    content: str = "正文内容",
    note_type: NoteType = NoteType.PERMANENT,
    links=None,
    extra_fm: str = None,
):
    """按 to_markdown 真实格式写一个笔记文件，可注入额外 frontmatter 字段。"""
    note = Note(
        id=note_id,
        title=title,
        content=content,
        type=note_type,
        created=datetime(2026, 8, 28, 0, 0),
        updated=datetime(2026, 8, 28, 0, 0),
        tags=[],
        links=links or [],
        backlinks=[],
    )
    md = note.to_markdown()
    if extra_fm:
        # frontmatter 内字段行不会是裸 ---，首个 "\n---\n" 即闭合分隔符
        md = md.replace("\n---\n", f"\n{extra_fm}\n---\n", 1)
    path = cfg.notes_dir / note_type.value / f"{note_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return path


@pytest.fixture
def kb(temp_kb):
    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def scenario(kb):
    """OLD 被三个来源引用（纯 frontmatter / 纯正文 / 两者兼有），KEEP 无引用。"""
    paths = {
        "old": _write_note(kb, OLD_ID, "旧概念"),
        "keep": _write_note(kb, KEEP_ID, "新概念"),
        "src_fm": _write_note(kb, SRC_FM_ID, "来源甲", links=[OLD_ID]),
        "src_body": _write_note(kb, SRC_BODY_ID, "来源乙", content="参考 [[旧概念]] 的分析"),
        "src_both": _write_note(
            kb, SRC_BOTH_ID, "来源丙", links=[OLD_ID], content="见 [[旧概念|详情]]"
        ),
    }
    return paths


class TestScanReferences:
    """入链扫描"""

    def test_scan_finds_frontmatter_and_body_refs(self, kb, scenario):
        report = scan_references(OLD_ID, cfg=kb)

        fm_ids = {sid for sid, _, _ in report.frontmatter_refs}
        body_ids = {sid for sid, _, _ in report.body_refs}
        assert fm_ids == {SRC_FM_ID, SRC_BOTH_ID}
        assert body_ids == {SRC_BODY_ID, SRC_BOTH_ID}
        assert KEEP_ID not in report.referencing_ids()
        assert report.can_proceed()

    def test_scan_includes_archived_sources(self, kb):
        """归档笔记是有效引用来源，不能被默认过滤掉"""
        _write_note(kb, OLD_ID, "旧概念")
        _write_note(kb, "20260828000010", "归档来源", links=[OLD_ID], extra_fm="archived: true")

        report = scan_references(OLD_ID, cfg=kb)
        assert "20260828000010" in {sid for sid, _, _ in report.frontmatter_refs}

    def test_scan_old_not_found(self, kb):
        report = scan_references("99999999000001", cfg=kb)
        assert report.old_not_found
        assert report.blocking_reasons()
        assert not report.can_proceed()

    def test_scan_keep_not_found(self, kb, scenario):
        report = scan_references(OLD_ID, keep_id="99999999000002", cfg=kb)
        assert report.keep_not_found
        assert not report.can_proceed()

    def test_scan_rejects_same_id(self, kb, scenario):
        report = scan_references(OLD_ID, keep_id=OLD_ID, cfg=kb)
        assert report.same_id
        assert not report.can_proceed()

    def test_scan_detects_duplicate_titles(self, kb):
        """重复标题无法确定 [[标题]] 原指哪篇，preflight 必须拒绝"""
        _write_note(kb, OLD_ID, "重复标题")
        _write_note(kb, "20260828000011", "重复标题")
        _write_note(kb, KEEP_ID, "新概念")

        report = scan_references(OLD_ID, keep_id=KEEP_ID, cfg=kb)
        assert len(report.duplicate_old_titles) == 2
        assert not report.can_proceed()


class TestRedirectReferences:
    """引用迁移"""

    def test_redirect_rewrites_frontmatter_and_body(self, kb, scenario):
        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)

        assert result.success, result.errors
        assert result.verification_passed
        assert result.files_changed == 3
        assert result.frontmatter_links_updated == 2
        assert result.body_links_updated == 2

        # frontmatter links：OLD → KEEP
        src_fm = load_note_by_id(SRC_FM_ID, cfg=kb)
        assert src_fm.links == [KEEP_ID]

        # 正文：[[旧概念]] → [[KEEP_ID]]（canonical 纯 ID 形式）
        raw_body = scenario["src_body"].read_text(encoding="utf-8")
        assert f"[[{KEEP_ID}]]" in raw_body
        assert "[[旧概念]]" not in raw_body

        # 两者兼有：frontmatter 与正文都迁移
        src_both = load_note_by_id(SRC_BOTH_ID, cfg=kb)
        assert src_both.links == [KEEP_ID]
        raw_both = scenario["src_both"].read_text(encoding="utf-8")
        assert f"[[{KEEP_ID}|详情]]" in raw_both

        # 旧笔记本身不被删除
        assert scenario["old"].exists()

    def test_redirect_syncs_keep_backlinks(self, kb, scenario):
        """KEEP 的 backlinks 纳入迁移来源，并清掉旧笔记残留"""
        # 预置 KEEP backlinks 里残留 OLD（模拟历史状态）
        scenario["keep"].write_text(
            scenario["keep"]
            .read_text(encoding="utf-8")
            .replace("backlinks: []", f"backlinks:\n- {OLD_ID}"),
            encoding="utf-8",
        )

        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert result.success, result.errors

        keep = load_note_by_id(KEEP_ID, cfg=kb)
        assert OLD_ID not in keep.backlinks
        for src in (SRC_FM_ID, SRC_BODY_ID, SRC_BOTH_ID):
            assert src in keep.backlinks

    def test_redirect_preserves_unknown_frontmatter(self, kb):
        """YAML patch 不得丢失 Note 模型之外的 frontmatter 字段"""
        _write_note(kb, OLD_ID, "旧概念")
        _write_note(kb, KEEP_ID, "新概念")
        src = _write_note(
            kb,
            SRC_FM_ID,
            "来源甲",
            links=[OLD_ID],
            extra_fm="custom_field: keep-me\ngrounded_by:\n- '20260101'",
        )
        before = src.read_text(encoding="utf-8")

        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert result.success, result.errors

        after = src.read_text(encoding="utf-8")
        assert "custom_field: keep-me" in after
        assert "grounded_by:" in after
        assert "keep-me" in before  # sanity：extra 字段确实注入成功

    def test_redirect_skips_code_blocks(self, kb):
        """代码块内的 [[...]] 不参与匹配也不被改写"""
        _write_note(kb, OLD_ID, "旧概念")
        _write_note(kb, KEEP_ID, "新概念")
        src = _write_note(
            kb,
            SRC_BODY_ID,
            "来源乙",
            content="前 [[旧概念]]\n\n```python\ns = '[[旧概念]]'\n```\n\n后 [[旧概念]]",
        )
        before = src.read_text(encoding="utf-8")

        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert result.success, result.errors
        assert result.body_links_updated == 2

        after = src.read_text(encoding="utf-8")
        # 代码块内保持原样
        assert "s = '[[旧概念]]'" in after
        # 代码块外两处被重写
        assert after.count(f"[[{KEEP_ID}]]") == 2
        assert "前 [[旧概念]]" not in after
        # sanity：原文确实含 3 处链接
        assert before.count("[[旧概念]]") == 3

    def test_redirect_preserves_alias_and_anchor(self, kb):
        _write_note(kb, OLD_ID, "旧概念")
        _write_note(kb, KEEP_ID, "新概念")
        src = _write_note(
            kb,
            SRC_BODY_ID,
            "来源乙",
            content="锚点 [[旧概念#章节]] 与别名 [[旧概念|别名X]]",
        )

        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert result.success, result.errors

        after = src.read_text(encoding="utf-8")
        assert f"[[{KEEP_ID}#章节]]" in after
        assert f"[[{KEEP_ID}|别名X]]" in after

    def test_redirect_dry_run_no_writes(self, kb, scenario):
        before = {k: p.read_text(encoding="utf-8") for k, p in scenario.items()}

        result = redirect_references(OLD_ID, KEEP_ID, dry_run=True, cfg=kb)

        assert result.success, result.errors
        assert result.dry_run
        assert result.files_changed == 3  # 影响范围照常统计
        assert result.verification_passed is False  # dry-run 不验证

        after = {k: p.read_text(encoding="utf-8") for k, p in scenario.items()}
        assert after == before

    def test_redirect_fails_on_duplicate_titles(self, kb):
        _write_note(kb, OLD_ID, "重复标题")
        _write_note(kb, "20260828000011", "重复标题")
        _write_note(kb, KEEP_ID, "新概念")
        src = _write_note(kb, SRC_FM_ID, "来源甲", links=[OLD_ID])
        before = src.read_text(encoding="utf-8")

        result = redirect_references(OLD_ID, KEEP_ID, cfg=kb)

        assert not result.success
        assert result.errors
        assert "Ambiguous OLD title" in result.errors[0]
        assert result.files_changed == 0
        assert src.read_text(encoding="utf-8") == before

    def test_redirect_idempotent_second_run(self, kb, scenario):
        first = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert first.success, first.errors

        # 全部迁移后，再扫描应无引用；重复执行不产生副作用
        second = redirect_references(OLD_ID, KEEP_ID, cfg=kb)
        assert second.success, second.errors
        assert second.files_changed == 0
        assert second.verification_passed


class TestRewriteBodyLinks:
    """正文重写纯函数（等长掩码保证偏移正确）"""

    def test_masked_offsets_rewrite_correctly(self):
        body = "a [[旧概念]] b\n```py\n[[旧概念]]\n```\nc [[旧概念]] d"
        new_body, count = _rewrite_body_links(body, "ID1", "旧概念", "KEEP9")
        assert count == 2
        assert "s" not in new_body  # sanity
        assert new_body == "a [[KEEP9]] b\n```py\n[[旧概念]]\n```\nc [[KEEP9]] d"

    def test_html_comment_untouched(self):
        body = "<!-- [[旧概念]] --> [[旧概念]]"
        new_body, count = _rewrite_body_links(body, "ID1", "旧概念", "KEEP9")
        assert count == 1
        assert new_body == "<!-- [[旧概念]] --> [[KEEP9]]"

    def test_no_substring_match(self):
        """精确匹配：[[旧概念延伸]] 不算对 “旧概念” 的引用"""
        body = "[[旧概念延伸]] 和 [[旧概念加]]"
        _, count = _rewrite_body_links(body, "ID1", "旧概念", "KEEP9")
        assert count == 0

    def test_multiple_occurrences_all_rewritten(self):
        body = "[[旧概念]] [[旧概念]] [[旧概念|别名]]"
        new_body, count = _rewrite_body_links(body, "ID1", "旧概念", "KEEP9")
        assert count == 3
        assert new_body == "[[KEEP9]] [[KEEP9]] [[KEEP9|别名]]"

    def test_id_form_matches(self):
        """纯 ID 链接同样迁移"""
        body = "[[ID1]]"
        new_body, count = _rewrite_body_links(body, "ID1", "旧概念", "KEEP9")
        assert count == 1
        assert new_body == "[[KEEP9]]"

    def test_case_insensitive_title(self):
        body = "[[Old Concept]]"
        _, count = _rewrite_body_links(body, "ID1", "old concept", "KEEP9")
        assert count == 1


class TestRedirectCommand:
    """CLI 端到端（CliRunner + --kb）"""

    def test_cli_redirect_json(self, mock_embedding_backend):
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                old = runner.invoke(
                    app,
                    [
                        "add",
                        "old body",
                        "--title",
                        "旧概念",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                keep = runner.invoke(
                    app,
                    [
                        "add",
                        "keep body",
                        "--title",
                        "新概念",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                src = runner.invoke(
                    app,
                    [
                        "add",
                        "参考 [[旧概念]]",
                        "--title",
                        "来源",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert old.exit_code == 0, old.output
                assert keep.exit_code == 0, keep.output
                assert src.exit_code == 0, src.output
                old_id = json.loads(old.output)["note"]["id"]
                keep_id = json.loads(keep.output)["note"]["id"]

                result = runner.invoke(
                    app, ["redirect", old_id, keep_id, "--kb", kb_name, "--json"]
                )
                assert result.exit_code == 0, result.output
                payload = json.loads(result.output)
                assert payload["success"] is True
                assert payload["files_changed"] >= 1
                assert payload["verification_passed"] is True

                # 正文重写为 canonical 纯 ID
                shown = runner.invoke(
                    app, ["show", json.loads(src.output)["note"]["id"], "--kb", kb_name, "--json"]
                )
                assert shown.exit_code == 0, shown.output
                assert f"[[{keep_id}]]" in json.loads(shown.output)["content"]

    def test_cli_redirect_unknown_id_fails(self, mock_embedding_backend):
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend",
                return_value=mock_embedding_backend,
            ):
                result = runner.invoke(
                    app,
                    ["redirect", "99999999000001", "88888888000002", "--kb", kb_name, "--json"],
                )
                assert result.exit_code == 1
                payload = json.loads(result.output)
                assert payload["success"] is False
                assert any("not found" in e for e in payload["errors"])
