"""端到端：candidate → promote → permanent（含 backlinks）；candidate → reject → archived"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.config import use_kb
from jfox.models import NoteType
from jfox.note import create_note, load_note_by_id, save_note

pytestmark = [pytest.mark.integration]
runner = CliRunner()


def test_promote_full_flow(temp_kb, mock_embedding_backend):
    """candidate 引用一条 permanent → promote → type 变、文件移动、backlink 建立"""
    kb = "test_promote_e2e"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        assert runner.invoke(app, ["init", "--name", kb, "--path", str(temp_kb)]).exit_code == 0

        with use_kb(kb):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = create_note("讲讲 [[目标笔记]]", title="候选X", note_type=NoteType.CANDIDATE)
            c.status = "pending"
            save_note(c, add_to_index=False)

        res = runner.invoke(app, ["candidates", "promote", c.id, "--kb", kb, "--format", "json"])
        assert res.exit_code == 0
        assert json.loads(res.output)["success"] is True

        with use_kb(kb):
            from jfox.config import config

            p = load_note_by_id(c.id)
            assert p.type == NoteType.PERMANENT
            assert (config.notes_dir / "permanent" / p.filename).exists()
            assert target.id in p.links
            assert c.id in load_note_by_id(target.id).backlinks


def test_reject_full_flow(temp_kb, mock_embedding_backend):
    """candidate → reject → archived + reason，默认 list 不可见"""
    kb = "test_reject_e2e"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        runner.invoke(app, ["init", "--name", kb, "--path", str(temp_kb)])
        with use_kb(kb):
            c = create_note("内容", title="候选Y", note_type=NoteType.CANDIDATE)
            save_note(c, add_to_index=False)

        res = runner.invoke(
            app, ["candidates", "reject", c.id, "--reason", "不准", "--kb", kb, "--format", "json"]
        )
        assert res.exit_code == 0

        with use_kb(kb):
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准"
        # 默认 list 排除归档
        list_res = runner.invoke(app, ["list", "--type", "candidate", "--kb", kb, "--json"])
        assert json.loads(list_res.output)["total"] == 0
