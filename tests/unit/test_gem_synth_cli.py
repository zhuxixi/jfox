"""jfox candidates list CLI 测试（临时/空 KB，验证命令能挂载、不崩）。"""

from typer.testing import CliRunner

from jfox.gem_synth.cli import candidates_app


def test_list_runs_on_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTELKASTEN_ROOT", str(tmp_path))
    result = CliRunner().invoke(candidates_app, ["list"])
    assert result.exit_code == 0


def test_list_json_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTELKASTEN_ROOT", str(tmp_path))
    result = CliRunner().invoke(candidates_app, ["list", "--format", "json"])
    assert result.exit_code == 0
