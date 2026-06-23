"""jfox candidates list/show CLI 测试。

使用 temp_kb_registered 创建真实隔离的临时知识库（注册到全局配置，
使 --kb 参数能真正生效），验证：
1. list/show 命令能挂载、参数解析不崩
2. --kb 真正切换到目标 KB
3. show 默认输出完整 markdown（不截断），--format json 输出完整 content
4. 不存在的 ID 优雅处理
"""

import json

import pytest
from typer.testing import CliRunner

from jfox.config import use_kb
from jfox.gem_synth.cli import candidates_app
from jfox.models import GemLevel, Note, NoteType
from jfox.note import save_note

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
