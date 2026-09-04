"""jfox moc add-member / remove-member 命令编排测试（进程内 + mock）。"""

from __future__ import annotations

import json
import re
from datetime import datetime as dt
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from jfox.cli import app
from jfox.moc.draft import MemberRemovalResult, MemberUpsertResult
from jfox.moc.generate import BacklinkUpdateResult
from jfox.models import Note, NoteType
from jfox.note_index import NoteMeta

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

MOC_ID = "20260822000001"
NOTE_ID = "20260820000003"

ADD_FIELDS = {
    "success",
    "moc_id",
    "note_id",
    "title",
    "group",
    "already_member",
    "applied",
    "partial",
    "rows_added",
    "rows_canonicalized",
    "warnings",
}
REMOVE_FIELDS = {
    "success",
    "moc_id",
    "note_id",
    "title",
    "removed",
    "not_member",
    "applied",
    "partial",
    "removed_rows",
    "removed_groups",
    "warnings",
}


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _help_lines(output: str) -> list[str]:
    return [" ".join(_strip_ansi(line).split()) for line in output.splitlines() if line.strip()]


def _note(
    tmp_path: Path,
    note_id: str = NOTE_ID,
    title: str = "Zima Gem V2",
    note_type: NoteType = NoteType.PERMANENT,
    *,
    links: list[str] | None = None,
    backlinks: list[str] | None = None,
    archived: bool = False,
    tags: list[str] | None = None,
) -> Note:
    note = Note(
        id=note_id,
        title=title,
        content="",
        type=note_type,
        created=dt(2026, 8, 22),
        updated=dt(2026, 8, 22),
        tags=tags if tags is not None else ["zima"],
        links=links or [],
        backlinks=backlinks or [],
        archived=archived,
    )
    note.set_filepath(tmp_path / f"{note_id}.md")
    note.filepath.write_text("x", encoding="utf-8")
    return note


def _meta(note: Note) -> NoteMeta:
    return NoteMeta(
        id=note.id,
        title=note.title,
        type=note.type,
        tags=list(note.tags),
        filepath=str(note.filepath),
        archived=note.archived,
    )


def _upsert_result(**overrides) -> MemberUpsertResult:
    defaults = dict(
        content="content-new",
        resolved_group="zima",
        changed=True,
        rows_added=1,
        rows_canonicalized=0,
        had_existing_row=False,
        matched_groups=("zima",),
        ambiguous_legacy=False,
    )
    defaults.update(overrides)
    return MemberUpsertResult(**defaults)


def _removal_result(**overrides) -> MemberRemovalResult:
    defaults = dict(
        content="content-new",
        changed=True,
        removed_rows=1,
        removed_groups=("zima",),
        ambiguous_legacy=False,
    )
    defaults.update(overrides)
    return MemberRemovalResult(**defaults)


def _patched_idx(moc: Note | None, member: Note | None):
    idx = MagicMock()
    by_id = {}
    if moc is not None:
        by_id[moc.id] = _meta(moc)
    if member is not None:
        by_id[member.id] = _meta(member)
    idx.find_by_id.side_effect = lambda nid: by_id.get(nid)
    all_meta = [_meta(moc)] if moc is not None else []
    if member is not None:
        all_meta.append(_meta(member))
    idx.get_all_meta.return_value = all_meta
    return idx


def _load_map(*notes: Note | None) -> dict[str, Note]:
    return {n.id: n for n in notes if n is not None}


# ---------------------------------------------------------------------------
# help 契约
# ---------------------------------------------------------------------------


def test_add_member_help_registers_contract():
    result = runner.invoke(app, ["moc", "add-member", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc add-member [OPTIONS] MOC_ID NOTE_ID" in lines
    assert "--group" in " ".join(lines)
    assert "--json" in " ".join(lines)


def test_remove_member_help_registers_contract():
    result = runner.invoke(app, ["moc", "remove-member", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "Usage: jfox moc remove-member [OPTIONS] MOC_ID NOTE_ID" in lines
    assert "--json" in " ".join(lines)
    assert "--group" not in " ".join(lines)


def test_moc_group_help_lists_member_commands():
    result = runner.invoke(app, ["moc", "--help"])

    assert result.exit_code == 0
    lines = _help_lines(result.output)
    assert "│ add-member 向 MOC 添加单个成员，维护正文/links/backlinks 一致。 │" in lines
    assert "│ remove-member 从 MOC 移除单个成员，对称清理正文/links/backlinks。 │" in lines


# ---------------------------------------------------------------------------
# add-member：拒绝路径
# ---------------------------------------------------------------------------


def _invoke_add(moc: Note | None, member: Note | None, *extra: str):
    with patch("jfox.moc.cli.get_note_index", return_value=_patched_idx(moc, member)):
        load_map = _load_map(moc, member)
        with patch(
            "jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)
        ):
            with patch("jfox.moc.cli.update_note", return_value=True) as mock_update:
                result = runner.invoke(
                    app, ["moc", "add-member", *(a for a in extra), "--format", "json"]
                )
    return result, mock_update


def test_add_rejects_invalid_moc_id(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path)

    result, mock_update = _invoke_add(moc, member, "bad/id", NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is False
    assert "Invalid note id" in payload["error"]
    mock_update.assert_not_called()


def test_add_rejects_invalid_note_id(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, "x*y")

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "Invalid note id" in payload["error"]


def test_add_rejects_missing_moc(tmp_path):
    member = _note(tmp_path)

    result, _ = _invoke_add(None, member, MOC_ID, NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "MOC note not found" in payload["error"]


def test_add_rejects_non_structure_moc(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.PERMANENT)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "not a structure note" in payload["error"]


def test_add_rejects_archived_moc(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, archived=True)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "archived" in payload["error"]


def test_add_rejects_missing_member(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)

    result, _ = _invoke_add(moc, None, MOC_ID, NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "Member note not found" in payload["error"]


def test_add_rejects_archived_member(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path, archived=True)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "Member note is archived" in payload["error"]


def test_add_rejects_self_link(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, MOC_ID)

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "self-link" in payload["error"].lower()


def test_add_rejects_reserved_group(tmp_path):
    """--group 近期活动 由纯函数校验拒绝；真实 upsert 参与校验。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID, "--group", "近期活动")

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "reserved section" in payload["error"]


def test_add_rejects_empty_group(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID, "--group", "")

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "group name" in payload["error"]


def test_add_rejects_newline_group(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)

    result, _ = _invoke_add(moc, member, MOC_ID, NOTE_ID, "--group", "a\nb")

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "group name" in payload["error"]


# ---------------------------------------------------------------------------
# add-member：行为与契约
# ---------------------------------------------------------------------------


def _invoke_add_full(tmp_path, moc: Note, member: Note, upsert, backfill, *extra: str):
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    patches = [
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True),
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ]
    for p in patches:
        p.start()
    try:
        result = runner.invoke(app, ["moc", "add-member", *(a for a in extra), "--format", "json"])
    finally:
        for p in patches:
            p.stop()
    return result


def test_add_fresh_member_applies_all_three_writes(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert set(payload.keys()) == ADD_FIELDS
    assert payload["success"] is True
    assert payload["moc_id"] == MOC_ID
    assert payload["note_id"] == NOTE_ID
    assert payload["title"] == "Zima Gem V2"
    assert payload["group"] == "zima"
    assert payload["already_member"] is False
    assert payload["applied"] is True
    assert payload["partial"] is False
    assert payload["rows_added"] == 1
    assert payload["warnings"] == []
    upsert.assert_called_once()
    assert upsert.call_args.kwargs["legacy_title_unique"] is True
    assert backfill.call_args.args[0] is not None
    assert list(backfill.call_args.args[1]) == [NOTE_ID]


def test_add_non_permanent_member_warns_but_applies(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path, note_type=NoteType.LITERATURE)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["applied"] is True
    assert any("not permanent" in w for w in payload["warnings"])


def test_add_structure_member_gets_nested_warning(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path, note_type=NoteType.STRUCTURE)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert any("not permanent" in w for w in payload["warnings"])
    assert any("nested structure" in w for w in payload["warnings"])


def test_add_unsafe_title_warns_id_only_link(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path, title="Bad ]] Title")
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert any("unsafe" in w and NOTE_ID in w for w in payload["warnings"])


def test_add_ambiguous_title_passes_unique_false_to_upsert(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    idx = _patched_idx(moc, member)
    idx.get_all_meta.return_value = [
        _meta(moc),
        _meta(member),
        NoteMeta(id=NOTE_ID + "9", title="Zima Gem V2", type=NoteType.SESSION),
    ]
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True),
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "json"])

    assert result.exit_code == 0
    assert upsert.call_args.kwargs["legacy_title_unique"] is False


def test_add_links_only_repairs_body_and_backlink(tmp_path):
    """links 已有 ID、正文缺行、backlink 缺失：补正文 + 回填 backlink。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["already_member"] is True
    assert payload["applied"] is True
    backfill.assert_called_once()


def test_add_backlink_only_repairs_without_moc_write(tmp_path):
    """正文/links 一致、仅 backlink 缺失：不重写 MOC，回填 backlink。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path)
    upsert = MagicMock(
        return_value=_upsert_result(changed=False, rows_added=0, had_existing_row=True)
    )
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True) as mock_update,
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "json"])

    payload = json.loads(_strip_ansi(result.output))
    assert payload["already_member"] is True
    assert payload["applied"] is True
    assert payload["group"] == "zima"
    mock_update.assert_not_called()
    backfill.assert_called_once()


def test_add_fully_consistent_is_pure_noop(tmp_path):
    """三处一致：applied=False，不写 MOC、不调 helper。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path, backlinks=[MOC_ID])
    upsert = MagicMock(
        return_value=_upsert_result(changed=False, rows_added=0, had_existing_row=True)
    )
    backfill = MagicMock(return_value=BacklinkUpdateResult((), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True) as mock_update,
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "json"])

    payload = json.loads(_strip_ansi(result.output))
    assert payload["already_member"] is True
    assert payload["applied"] is False
    assert payload["partial"] is False
    mock_update.assert_not_called()
    backfill.assert_not_called()


def test_add_normalizes_duplicate_links(tmp_path):
    moc = _note(
        tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID, NOTE_ID]
    )
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True) as mock_update,
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "json"])

    payload = json.loads(_strip_ansi(result.output))
    assert payload["applied"] is True
    saved_moc = mock_update.call_args.args[0]
    assert saved_moc.links == [NOTE_ID]


def test_add_ambiguous_legacy_sets_partial_and_warning(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result(ambiguous_legacy=True))
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["partial"] is True
    assert any("Zima Gem V2" in w and "not unique" in w for w in payload["warnings"])


def test_add_update_failure_aborts_without_backfill(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", MagicMock(return_value=_upsert_result())),
        patch("jfox.moc.cli.update_note", return_value=False),
        patch("jfox.moc.cli.backfill_moc_backlinks") as backfill,
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "Failed to save MOC note" in payload["error"]
    backfill.assert_not_called()


def test_add_backlink_failure_reports_partial(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((), (NOTE_ID,)))

    result = _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["partial"] is True
    assert payload["applied"] is True
    assert any(NOTE_ID in w and MOC_ID in w for w in payload["warnings"])


def test_add_table_output_readable(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.upsert_member_line", upsert),
        patch("jfox.moc.cli.update_note", return_value=True),
        patch("jfox.moc.cli.backfill_moc_backlinks", backfill),
    ):
        result = runner.invoke(app, ["moc", "add-member", MOC_ID, NOTE_ID, "--format", "table"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert NOTE_ID in output
    assert "zima" in output


# ---------------------------------------------------------------------------
# remove-member
# ---------------------------------------------------------------------------


def _invoke_remove_full(moc: Note, member: Note | None, removal, backrem, *extra: str):
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    patches = [
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.remove_member_lines", removal),
        patch("jfox.moc.cli.update_note", return_value=True),
        patch("jfox.moc.cli.remove_moc_backlinks", backrem),
    ]
    for p in patches:
        p.start()
    try:
        result = runner.invoke(
            app, ["moc", "remove-member", *(a for a in extra), "--format", "json"]
        )
    finally:
        for p in patches:
            p.stop()
    return result


def test_remove_cleans_all_three_states(tmp_path):
    moc = _note(
        tmp_path,
        MOC_ID,
        title="Zima MOC",
        note_type=NoteType.STRUCTURE,
        links=[NOTE_ID, "20260820000002"],
    )
    member = _note(tmp_path, backlinks=[MOC_ID])
    removal = MagicMock(return_value=_removal_result(removed_rows=2, removed_groups=("zima", "cr")))
    backrem = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_remove_full(moc, member, removal, backrem, MOC_ID, NOTE_ID)

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert set(payload.keys()) == REMOVE_FIELDS
    assert payload["success"] is True
    assert payload["title"] == "Zima Gem V2"
    assert payload["removed"] is True
    assert payload["not_member"] is False
    assert payload["applied"] is True
    assert payload["partial"] is False
    assert payload["removed_rows"] == 2
    assert payload["removed_groups"] == ["zima", "cr"]
    assert payload["warnings"] == []
    backrem.assert_called_once()
    assert list(backrem.call_args.args[1]) == [NOTE_ID]


def test_remove_not_member_is_noop(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    removal = MagicMock(
        return_value=_removal_result(changed=False, removed_rows=0, removed_groups=())
    )
    backrem = MagicMock(return_value=BacklinkUpdateResult((), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.remove_member_lines", removal),
        patch("jfox.moc.cli.update_note", return_value=True) as mock_update,
        patch("jfox.moc.cli.remove_moc_backlinks", backrem),
    ):
        result = runner.invoke(app, ["moc", "remove-member", MOC_ID, NOTE_ID, "--format", "json"])

    payload = json.loads(_strip_ansi(result.output))
    assert payload["removed"] is False
    assert payload["not_member"] is True
    assert payload["applied"] is False
    assert payload["partial"] is False
    mock_update.assert_not_called()
    # spec §3.3 步骤 6：成员仍存在时调用 helper（幂等空操作）
    backrem.assert_called_once()


def test_remove_ambiguous_only_skips_persistence_and_helper(tmp_path):
    """只有歧义 legacy 行：不改 MOC 文件、不摘 backlink、not_member。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    removal = MagicMock(
        return_value=_removal_result(
            changed=False, removed_rows=0, removed_groups=(), ambiguous_legacy=True
        )
    )
    backrem = MagicMock(return_value=BacklinkUpdateResult((), ()))
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.remove_member_lines", removal),
        patch("jfox.moc.cli.update_note", return_value=True) as mock_update,
        patch("jfox.moc.cli.remove_moc_backlinks", backrem),
    ):
        result = runner.invoke(app, ["moc", "remove-member", MOC_ID, NOTE_ID, "--format", "json"])

    payload = json.loads(_strip_ansi(result.output))
    assert payload["removed"] is False
    assert payload["not_member"] is True
    assert payload["applied"] is False
    assert payload["partial"] is False
    assert any("Zima Gem V2" in w for w in payload["warnings"])
    mock_update.assert_not_called()
    backrem.assert_not_called()


def test_remove_confirmed_cleanup_with_ambiguous_legacy_partial(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path, backlinks=[MOC_ID])
    removal = MagicMock(return_value=_removal_result(removed_rows=1, ambiguous_legacy=True))
    backrem = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_remove_full(moc, member, removal, backrem, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["removed"] is True
    assert payload["applied"] is True
    assert payload["partial"] is True
    assert any("Zima Gem V2" in w for w in payload["warnings"])


def test_remove_missing_member_cleans_links_by_id_only(tmp_path):
    """成员文件不存在：按 ID 清理 links/canonical 行，不调 backlink helper。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    removal = MagicMock(return_value=_removal_result(removed_rows=0, removed_groups=()))
    backrem = MagicMock(return_value=BacklinkUpdateResult((), ()))

    result = _invoke_remove_full(moc, None, removal, backrem, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["title"] is None
    assert payload["removed"] is True
    assert payload["removed_rows"] == 0
    backrem.assert_not_called()
    assert removal.call_args.args[2] is None  # title=None


def test_remove_archived_member_still_allowed(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path, archived=True, backlinks=[MOC_ID])
    removal = MagicMock(return_value=_removal_result(removed_rows=1))
    backrem = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))

    result = _invoke_remove_full(moc, member, removal, backrem, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["removed"] is True
    backrem.assert_called_once()


def test_remove_update_failure_aborts_without_backremoval(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path, backlinks=[MOC_ID])
    idx = _patched_idx(moc, member)
    load_map = _load_map(moc, member)
    with (
        patch("jfox.moc.cli.get_note_index", return_value=idx),
        patch("jfox.moc.cli.load_note", side_effect=lambda path: load_map.get(Path(path).stem)),
        patch("jfox.moc.cli.remove_member_lines", MagicMock(return_value=_removal_result())),
        patch("jfox.moc.cli.update_note", return_value=False),
        patch("jfox.moc.cli.remove_moc_backlinks") as backrem,
    ):
        result = runner.invoke(app, ["moc", "remove-member", MOC_ID, NOTE_ID, "--format", "json"])

    assert result.exit_code == 1
    payload = json.loads(_strip_ansi(result.output))
    assert "Failed to save MOC note" in payload["error"]
    backrem.assert_not_called()


def test_remove_backremoval_failure_reports_partial(tmp_path):
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member = _note(tmp_path, backlinks=[MOC_ID])
    removal = MagicMock(return_value=_removal_result())
    backrem = MagicMock(return_value=BacklinkUpdateResult((), (NOTE_ID,)))

    result = _invoke_remove_full(moc, member, removal, backrem, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["partial"] is True
    assert any(NOTE_ID in w and MOC_ID in w for w in payload["warnings"])


def test_add_then_add_is_idempotent_repeated(tmp_path):
    """重复 add：第二次 no-op（等价 fully consistent 场景的端到端顺序）。"""
    moc = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE)
    member = _note(tmp_path)
    upsert = MagicMock(return_value=_upsert_result())
    backfill = MagicMock(return_value=BacklinkUpdateResult((NOTE_ID,), ()))
    _invoke_add_full(tmp_path, moc, member, upsert, backfill, MOC_ID, NOTE_ID)

    moc2 = _note(tmp_path, MOC_ID, title="Zima MOC", note_type=NoteType.STRUCTURE, links=[NOTE_ID])
    member2 = _note(tmp_path, backlinks=[MOC_ID])
    upsert2 = MagicMock(
        return_value=_upsert_result(changed=False, rows_added=0, had_existing_row=True)
    )
    backfill2 = MagicMock(return_value=BacklinkUpdateResult((), ()))
    result = _invoke_add_full(tmp_path, moc2, member2, upsert2, backfill2, MOC_ID, NOTE_ID)

    payload = json.loads(_strip_ansi(result.output))
    assert payload["already_member"] is True
    assert payload["applied"] is False
    assert payload["rows_added"] == 0
