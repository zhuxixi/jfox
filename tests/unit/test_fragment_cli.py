"""jfox fragments list/show CLI 测试（临时 DB，无 daemon/模型）。"""

import json

from typer.testing import CliRunner

from jfox.fragment.cli import fragments_app
from jfox.fragment.store import FragmentStore


def _seed(tmp_path):
    monkey_db = tmp_path / "f.db"
    store = FragmentStore(db_path=monkey_db)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {"prompt": "不对"})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.close()
    return monkey_db


def test_list_table(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["list", "--session", "s1"])
    assert result.exit_code == 0
    assert "correction" in result.stdout
    assert "tool_call" in result.stdout


def test_list_json(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["list", "--session", "s1", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 2


def test_list_filter_type(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(
        fragments_app, ["list", "--session", "s1", "--type", "tool_call", "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 1 and data["fragments"][0]["fragment_type"] == "tool_call"


def test_show_detail(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    store = FragmentStore(db_path=db)
    fid = store.query(session_id="s1", fragment_type="correction")[0]["fragment_id"]
    store.close()
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["show", str(fid)])
    assert result.exit_code == 0
    assert "不对" in result.stdout
    assert "prompt" in result.stdout  # metadata 展开了
