"""candidate CLI 迁移 parity 测试（jfox/gem_synth/cli.py → jfox/candidates/）。

验证：
1. 命令行为与迁移前完全一致（list/show/promote/reject）
2. 旧 candidate（无 source_prompts）继续可用
3. promote 后 source_prompts 溯源保留
"""

import json
from datetime import datetime

import pytest
from typer.testing import CliRunner

from jfox.models import GemLevel, Note, NoteType
from jfox.note import save_note
from tests.utils.temp_kb import temp_kb_registered

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _make_candidate(note_id: str, title: str, body: str, source_prompts=None) -> Note:
    now = datetime.now()
    return Note(
        id=note_id,
        title=title,
        content=body,
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        status="pending",
        gem_level=GemLevel.FLAWED.value,
        confidence=0.8,
        knowledge_type="factual",
        source_prompts=source_prompts or [],
    )


@pytest.fixture
def cand_app():
    from jfox.candidates.cli import candidates_app

    return candidates_app


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------


def test_list_empty(cand_app):
    result = CliRunner().invoke(cand_app, ["list", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["candidates"] == []


def test_list_shows_candidates(cand_app):
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb

        with use_kb(kb_name):
            save_note(_make_candidate("20260902000000-000001", "候选A", "正文" * 60))
        result = CliRunner().invoke(cand_app, ["list", "--format", "json", "--kb", kb_name])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total"] == 1
    assert data["candidates"][0]["title"] == "候选A"


def test_show_outputs_full_markdown(cand_app):
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb

        note = _make_candidate("20260902000000-000002", "全文候选", "正文" * 300)
        with use_kb(kb_name):
            save_note(note)
        result = CliRunner().invoke(cand_app, ["show", note.id, "--kb", kb_name])
    assert result.exit_code == 0
    assert "全文候选" in result.output


def test_show_json_has_full_content(cand_app):
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb

        note = _make_candidate("20260902000000-000003", "json候选", "json正文" * 100)
        with use_kb(kb_name):
            save_note(note)
        result = CliRunner().invoke(
            cand_app, ["show", note.id, "--kb", kb_name, "--format", "json"]
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["content"] == note.content  # 完整不截断


def test_show_nonexistent_graceful(cand_app):
    result = CliRunner().invoke(cand_app, ["show", "99999999999999-9"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# promote / reject：旧 candidate（无 source_prompts）兼容
# ---------------------------------------------------------------------------


def test_promote_old_candidate_without_source_prompts(cand_app):
    """旧 candidate（source_prompts 空）照常 promote。"""
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb

        note = _make_candidate("20260902000000-000004", "旧式候选", "内容 [[目标]]")
        with use_kb(kb_name):
            save_note(note)
        result = CliRunner().invoke(cand_app, ["promote", note.id, "--kb", kb_name])
        assert result.exit_code == 0


def test_promote_preserves_source_prompts(cand_app):
    """带 source_prompts 的 candidate promote 后溯源保留。"""
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb
        from jfox.note import load_note_by_id

        note = _make_candidate("20260902000000-000005", "新式候选", "内容", source_prompts=[42, 43])
        with use_kb(kb_name):
            save_note(note)
            result = CliRunner().invoke(cand_app, ["promote", note.id, "--kb", kb_name])
            assert result.exit_code == 0

            promoted = load_note_by_id(note.id)
            assert promoted is not None
            assert promoted.type == NoteType.PERMANENT
            assert promoted.source_prompts == [42, 43]  # 溯源保留


def test_reject_candidate(cand_app):
    with temp_kb_registered() as kb_name:
        from jfox.config import use_kb
        from jfox.note import load_note_by_id

        note = _make_candidate("20260902000000-000006", "要拒的", "内容")
        with use_kb(kb_name):
            save_note(note)
            result = CliRunner().invoke(
                cand_app, ["reject", note.id, "--reason", "测试拒绝", "--kb", kb_name]
            )
            assert result.exit_code == 0

            rejected = load_note_by_id(note.id)
            assert rejected.archived is True
            assert rejected.status == "rejected"


# ---------------------------------------------------------------------------
# 注册路径：主 app 仍然挂 candidates 名字
# ---------------------------------------------------------------------------


def test_main_app_still_registers_candidates():
    from jfox.cli import app

    names = [c.name for c in app.registered_groups]
    assert "candidates" in names


def test_gem_synth_cli_no_longer_exports_candidates():
    """迁移后 gem_synth.cli 不再导出 candidates_app。"""
    import jfox.gem_synth.cli as gsc

    assert not hasattr(gsc, "candidates_app")
