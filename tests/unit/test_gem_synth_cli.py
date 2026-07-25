"""jfox candidates list/show CLI 测试。

使用 temp_kb_registered 创建真实隔离的临时知识库（注册到全局配置，
使 --kb 参数能真正生效），验证：
1. list/show 命令能挂载、参数解析不崩
2. --kb 真正切换到目标 KB
3. show 默认输出完整 markdown（不截断），--format json 输出完整 content
4. 不存在的 ID 优雅处理
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.config import use_kb
from jfox.gem_synth.cli import candidates_app
from jfox.models import GemLevel, Note, NoteType
from jfox.note import create_note, load_note_by_id, save_note

# 走完整 app 路由（jfox candidates promote <id>）的测试用此 runner
runner = CliRunner()

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _make_candidate(note_id: str, title: str, body: str) -> Note:
    """构造一个 candidate 笔记（正文长度 > 200 以验证不截断）。"""
    from datetime import datetime

    now = datetime.now()
    # 重复填充使正文明显超过 to_dict 的 200 字符截断阈值
    long_body = body + ("\n这一段是填充内容用于超过两百字符阈值，确保 to_dict 会截断。" * 10)
    return Note(
        id=note_id,
        title=title,
        content=long_body,
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        gem_level=GemLevel.FLAWED.value,
        confidence=0.8,
        knowledge_type="factual",
        status="pending",
    )


def test_list_empty_kb(tmp_path):
    """list 在默认 KB（空 candidate 目录）上应正常返回 0 退出。"""
    result = CliRunner().invoke(candidates_app, ["list"])
    assert result.exit_code == 0


def test_list_json_empty_kb():
    """list --format json 在空 KB 上应返回 total=0。"""
    result = CliRunner().invoke(candidates_app, ["list", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 0


def test_list_and_show_with_real_temp_kb():
    """用真实注册的临时 KB 验证 --kb 切换 + list/show 全流程。

    temp_kb_registered 注册到全局配置，使 use_kb(name) 能解析；
    候选笔记写入该 KB 后，通过 CLI --kb 参数应能读到。
    """
    from tests.utils.temp_kb import temp_kb_registered

    with temp_kb_registered() as kb_name:
        # 切到临时 KB 写入一条 candidate（add_to_index=False 避免 embedding 开销）
        with use_kb(kb_name):
            note = _make_candidate("20260621143000-1", "测试候选", "这是完整正文。")
            assert save_note(note, add_to_index=False)

        # list 通过 --kb 切换应能读到
        result = CliRunner().invoke(candidates_app, ["list", "--kb", kb_name])
        assert result.exit_code == 0
        assert "测试候选" in result.stdout

        # list --format json
        result_json = CliRunner().invoke(
            candidates_app, ["list", "--kb", kb_name, "--format", "json"]
        )
        assert result_json.exit_code == 0
        data = json.loads(result_json.stdout)
        assert data["total"] == 1
        assert data["candidates"][0]["title"] == "测试候选"

        # show 默认输出完整 markdown（不截断）
        show_md = CliRunner().invoke(candidates_app, ["show", "20260621143000-1", "--kb", kb_name])
        assert show_md.exit_code == 0
        # 填充内容应完整出现（to_dict 会截断到 200 字符，这里验证未被截断）
        assert "这一段是填充内容用于超过两百字符阈值" in show_md.stdout
        assert "测试候选" in show_md.stdout

        # show --format json：content 字段为纯正文（note.content，不含 frontmatter）
        show_json = CliRunner().invoke(
            candidates_app,
            ["show", "20260621143000-1", "--kb", kb_name, "--format", "json"],
        )
        assert show_json.exit_code == 0
        jdata = json.loads(show_json.stdout)
        assert jdata["title"] == "测试候选"
        # content 字段为完整正文（含填充内容；cc#5：不再含 frontmatter 重复）
        assert "这一段是填充内容用于超过两百字符阈值" in jdata["content"]


def test_show_nonexistent_id_graceful():
    """show 不存在的 ID 应优雅退出（exit 1，不抛 traceback）。"""
    result = CliRunner().invoke(candidates_app, ["show", "99999999999999-1"])
    assert result.exit_code == 1
    assert "找不到" in result.stdout or "Traceback" not in (result.stdout + result.output)


def test_list_limit_clamped():
    """list --limit 非正值（0 或负）应回退默认 50，exit 0 不崩。

    回归：未 clamp 时 limit<=0 使 fetch_limit=0，list_notes 拉不到任何笔记，
    虽不会抛错但行为错误；clamp 后应与默认等价。
    """
    # 空库下，limit=-5 应与默认行为一致（exit 0，输出 0 条）
    result_neg = CliRunner().invoke(candidates_app, ["list", "--limit", "-5"])
    assert result_neg.exit_code == 0

    result_zero = CliRunner().invoke(candidates_app, ["list", "--limit", "0"])
    assert result_zero.exit_code == 0


def test_list_json_error_structure():
    """list 读取失败且 --format json 时，应输出结构化 JSON 错误（AGENTS.md 约定）。

    通过 monkeypatch 让 list_notes 抛错触发 except 分支，验证输出为
    {"success": false, "error": ...} 而非红色提示文本。
    """
    # list_cmd 函数体内 `from ..note import list_notes` 在调用时解析，
    # 故 patch jfox.note.list_notes 模块属性即可生效。
    import jfox.note as note_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("boom-for-test")

    orig_list_notes = note_mod.list_notes
    note_mod.list_notes = _boom
    try:
        result = CliRunner().invoke(candidates_app, ["list", "--format", "json"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["success"] is False
        assert "boom-for-test" in data["error"]
    finally:
        note_mod.list_notes = orig_list_notes


# ----------------------------------------------------------------------------
# jfox gem-synth status 命令（进度 pending/success/failed + 失败复核）
# ----------------------------------------------------------------------------


def test_gem_synth_status_shows_counts(tmp_path, monkeypatch):
    """jfox gem-synth status 显示 pending/success/failed。

    通过 JFOX_FRAGMENTS_DB / JFOX_SYNTHESIS_DB 环境变量隔离测试 DB。
    """
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.cli import gem_synth_app
    from jfox.gem_synth.store import SynthesisLog

    fdb = tmp_path / "f.db"
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))

    store = FragmentStore(db_path=fdb)
    store.insert("s", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s", "correction", "UserPromptSubmit", "错了", {})
    store.insert("s", "correction", "UserPromptSubmit", "应该", {})
    store.close()

    log = SynthesisLog(db_path=sdb)
    log.mark_processed(1, "c1")
    log.mark_failed(2, "boom")
    log.close()

    result = CliRunner().invoke(gem_synth_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pending"] == 1
    assert data["success"] == 1
    assert data["failed"] == 1


def test_gem_synth_status_shows_merged(tmp_path, monkeypatch):
    """status 显示 merged 计数，并从 pending 扣除 merged（#309）。"""
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.cli import gem_synth_app
    from jfox.gem_synth.store import SynthesisLog

    fdb = tmp_path / "f.db"
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))

    store = FragmentStore(db_path=fdb)
    for i in range(5):
        store.insert("s", "correction", "UserPromptSubmit", f"c{i}", {})
    store.close()

    log = SynthesisLog(db_path=sdb)
    log.mark_processed(1, "c1")
    log.mark_merged(2, "c-target")  # Task 2 加的方法
    log.close()

    result = CliRunner().invoke(gem_synth_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["merged"] == 1
    # total=5, success=1, failed=0, duplicate=0, merged=1 → pending=3
    assert data["pending"] == 3


def test_gem_synth_status_table_runs(tmp_path, monkeypatch):
    """status 默认 table 输出应 exit 0 不崩（空库场景）。"""
    from jfox.gem_synth.cli import gem_synth_app

    fdb = tmp_path / "f.db"
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))

    # 触发 default_db_path() 建表（count_anchors 否则要 fragments 表存在）
    from jfox.fragment.store import FragmentStore

    store = FragmentStore(db_path=fdb)
    store.close()

    result = CliRunner().invoke(gem_synth_app, ["status"])
    assert result.exit_code == 0
    assert "合成进度" in result.output


def test_gem_synth_status_failed_only(tmp_path, monkeypatch):
    """status --failed 应列失败锚点（json）。"""
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.cli import gem_synth_app
    from jfox.gem_synth.store import SynthesisLog

    fdb = tmp_path / "f.db"
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))

    store = FragmentStore(db_path=fdb)
    store.insert("s", "correction", "UserPromptSubmit", "不对", {})
    store.close()

    log = SynthesisLog(db_path=sdb)
    log.mark_failed(1, "boom")
    log.close()

    result = CliRunner().invoke(gem_synth_app, ["status", "--failed", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["failed"]) == 1
    assert data["failed"][0]["anchor_fragment_id"] == 1
    assert data["failed"][0]["fail_reason"] == "boom"


def test_gem_synth_status_help_lists_command():
    """gem_synth_app --help 应列出 status 子命令。"""
    from jfox.gem_synth.cli import gem_synth_app

    result = CliRunner().invoke(gem_synth_app, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.output


# ----------------------------------------------------------------------------
# jfox candidates promote 子命令（candidate → permanent）
# ----------------------------------------------------------------------------


def test_candidates_promote_command(temp_kb, mock_embedding_backend):
    """jfox candidates promote <id> 把 candidate 改成 permanent"""
    from jfox.models import NoteType
    from jfox.note import create_note, load_note_by_id, save_note

    kb_name = "test_promote_cli"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        init_res = runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)])
        assert init_res.exit_code == 0, init_res.output

        with use_kb(kb_name):
            c = create_note("内容", title="候选A", note_type=NoteType.CANDIDATE)
            c.status = "pending"
            save_note(c, add_to_index=False)

        res = runner.invoke(
            app, ["candidates", "promote", c.id, "--kb", kb_name, "--format", "json"]
        )
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["promoted"] == c.id

        with use_kb(kb_name):
            assert load_note_by_id(c.id).type == NoteType.PERMANENT


def test_candidates_promote_nonexistent_exits_nonzero(temp_kb, mock_embedding_backend):
    """promote 不存在的 ID 应 exit 1（优雅失败，不抛 traceback）"""
    kb_name = "test_promote_404"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        assert (
            runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)]).exit_code == 0
        )
        res = runner.invoke(app, ["candidates", "promote", "999999999999999", "--kb", kb_name])
        assert res.exit_code == 1


# ----------------------------------------------------------------------------
# jfox candidates reject 子命令（candidate 归档丢弃 + 记原因）
# ----------------------------------------------------------------------------


def test_candidates_reject_command(temp_kb, mock_embedding_backend):
    """jfox candidates reject <id> 归档 + 记 reason"""
    kb_name = "test_reject_cli"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        assert (
            runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)]).exit_code == 0
        )
        with use_kb(kb_name):
            c = create_note("内容", title="候选B", note_type=NoteType.CANDIDATE)
            save_note(c, add_to_index=False)

        res = runner.invoke(
            app,
            ["candidates", "reject", c.id, "--reason", "不准", "--kb", kb_name, "--format", "json"],
        )
        assert res.exit_code == 0, res.output
        with use_kb(kb_name):
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准"
