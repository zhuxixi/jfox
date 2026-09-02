"""prompts config / help CLI 测试：配置展示、安全校验、命令帮助。"""

import json

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _invoke(*args, tmp_path, monkeypatch):
    from jfox.prompts.cli import prompts_app

    monkeypatch.setenv("ZK_CONFIG_PATH", str(tmp_path / "zk.json"))
    return CliRunner().invoke(prompts_app, list(args))


def test_config_show_rejects_none(tmp_path, monkeypatch):
    """config 默认 judge.runner 是 pi（本地二进制），非远程。"""
    result = _invoke("config", "--format", "json", tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["judge"]["runner"] == "pi"
    assert data["judge"]["binary"] == "pi"


def test_config_set_simple_field(tmp_path, monkeypatch):
    result = _invoke(
        "config", "--set", "default_limit=10", tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert result.exit_code == 0
    # 验证已持久化
    data2 = json.loads(
        _invoke(
            "config", "--format", "json", tmp_path=tmp_path, monkeypatch=monkeypatch
        ).output
    )
    assert data2["judge"]["default_limit"] == 10


def test_config_set_bool_field(tmp_path, monkeypatch):
    result = _invoke(
        "config", "--set", "allow_remote=true", tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert result.exit_code == 0
    data2 = json.loads(
        _invoke(
            "config", "--format", "json", tmp_path=tmp_path, monkeypatch=monkeypatch
        ).output
    )
    assert data2["judge"]["allow_remote"] is True


def test_config_set_bad_format_rejected(tmp_path, monkeypatch):
    result = _invoke(
        "config", "--set", "noequals", tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert result.exit_code != 0


def test_config_set_capture_field(tmp_path, monkeypatch):
    result = _invoke(
        "config", "--set", "endpoint_timeout_seconds=2",
        tmp_path=tmp_path, monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0
    data2 = json.loads(
        _invoke(
            "config", "--format", "json", tmp_path=tmp_path, monkeypatch=monkeypatch
        ).output
    )
    assert data2["capture"]["endpoint_timeout_seconds"] == 2


def test_help_lists_all_commands():
    from jfox.prompts.cli import prompts_app

    result = CliRunner().invoke(prompts_app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "list", "show", "status", "drain", "backfill", "judge",
        "promote", "unresolved", "resolve-unresolved", "ignore", "retry", "config",
    ):
        assert cmd in result.output, f"help 缺少命令 {cmd}"


def test_judge_help_mentions_remote_consent():
    from jfox.prompts.cli import prompts_app

    result = CliRunner().invoke(prompts_app, ["judge", "--help"])
    assert result.exit_code == 0
    assert "allow-remote" in result.output


def test_backfill_help_has_dry_run():
    from jfox.prompts.cli import prompts_app

    result = CliRunner().invoke(prompts_app, ["backfill", "--help"])
    assert result.exit_code == 0
    assert "dry-run" in result.output
