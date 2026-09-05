"""jfox prompts CLI 测试：list/show/status/judge 等命令。"""

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _make_prompts_db(tmp_path, n=2):
    from jfox.prompts.store import PromptStore

    store = PromptStore(db_path=tmp_path / "fragments.db")
    for i in range(n):
        store.insert_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "s1",
                "prompt": f"问题 {i}",
                "transcript_path": f"/tmp/t{i}.jsonl",
            },
            source_key=f"capture:c{i}",
        )
    return store


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_empty_db(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    import json

    data = json.loads(result.output)
    assert data["total_prompts"] == 0
    assert data["unjudged"] == 0


def test_status_reports_unjudged(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    _make_prompts_db(tmp_path, n=3)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    import json

    data = json.loads(result.output)
    assert data["total_prompts"] == 3
    assert data["unjudged"] == 3


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------


def test_list_truncates_prompt_text(tmp_path, monkeypatch):
    """table 输出不含完整 prompt 文本（防信息密度爆炸）。"""
    from jfox.prompts.cli import prompts_app
    from jfox.prompts.store import PromptStore

    store = PromptStore(db_path=tmp_path / "fragments.db")
    long_prompt = "这是一个非常长的 prompt " * 50
    store.insert_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": long_prompt},
        source_key="capture:long",
    )
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["list"])
    assert result.exit_code == 0
    assert long_prompt not in result.output  # 完整文本不出现


def test_list_json_includes_fields(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    _make_prompts_db(tmp_path, n=2)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["list", "--format", "json"])
    assert result.exit_code == 0
    import json

    data = json.loads(result.output)
    assert len(data) == 2
    assert "prompt_id" in data[0]
    assert "session_id" in data[0]


def test_show_by_id(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    _make_prompts_db(tmp_path, n=1)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["show", "1", "--format", "json"])
    assert result.exit_code == 0
    import json

    data = json.loads(result.output)
    assert data["prompt_id"] == 1


def test_show_nonexistent(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["show", "999"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# judge（mock runner）
# ---------------------------------------------------------------------------


def test_judge_report_dict():
    """JudgeReport 可转 dict（CLI 输出用）。"""
    from jfox.prompts.judge import JudgeReport

    r = JudgeReport(total=3, succeeded=3, failed=0, batches=1)
    d = r.__dict__
    assert d["total"] == 3
    assert d["batches"] == 1


# ---------------------------------------------------------------------------
# promote / ignore 等动作命令的前置条件错误输出
# ---------------------------------------------------------------------------


def test_promote_nonexistent_prompt(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    result = CliRunner().invoke(prompts_app, ["promote", "999"])
    assert result.exit_code != 0


def test_ignore_reject_candidate_flag(tmp_path, monkeypatch):
    """--reject-candidate 标志传递到动作层。"""
    from jfox.prompts.cli import prompts_app
    from jfox.prompts.store import PromptStore

    store = PromptStore(db_path=tmp_path / "fragments.db")
    store.insert_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "q"},
        source_key="capture:c1",
    )
    store.claim_prompts("kb", [1], "t", "2026-01-01T00:00:00Z")
    store.finish_judgment(
        "kb",
        1,
        classification="new",
        reason="r",
        confidence=0.9,
        matched_note_ids=[],
        matched_prompt_ids=[],
        matched_unresolved_prompt_ids=[],
        context_mode="prompt_only",
        runner_id="pi",
        model_id="m",
        candidate_note_id="n1",
    )

    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    called = {}

    def fake_ignore(kb, pid, reject_candidate=False, store=None):
        called["rc"] = reject_candidate
        return True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("jfox.prompts.actions.ignore_prompt", fake_ignore)
        result = CliRunner().invoke(prompts_app, ["ignore", "1", "--reject-candidate"])
    assert result.exit_code == 0
    assert called["rc"] is True


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_show_defaults(tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    monkeypatch.setenv("ZK_CONFIG_PATH", str(tmp_path / "zk_config.json"))
    result = CliRunner().invoke(prompts_app, ["config", "--format", "json"])
    assert result.exit_code == 0
    import json

    data = json.loads(result.output)
    assert data["judge"]["runner"] == "pi"
    assert "model" in data["judge"]
