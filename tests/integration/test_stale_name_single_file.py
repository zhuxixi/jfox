"""
测试类型: 集成测试
目标功能: #549 发散名（磁盘名 ≠ 规则名）笔记的全链路单文件契约
       （A3 update_note 自愈 + A4-A8 CLI 症状层：add/edit/rebuild/show+delete/moc 回填）
预估耗时: < 60秒
依赖要求: 临时知识库，mock embedding backend（cli_fast）

发散名 = 只 rename 文件（保留 id 前缀），不改 frontmatter——
等价于「外部改标题未同步改名」的场景。
"""

import json
from pathlib import Path

import pytest
from utils.temp_kb import temp_kb_registered

pytestmark = [pytest.mark.integration]


def _diverge(filepath: str) -> Path:
    """只 rename 文件制造发散名（保留 id 前缀），模拟外部改标题未同步改名"""
    p = Path(filepath)
    d = p.with_name(f"{p.stem}-diverged.md")
    p.rename(d)
    return d


def _files_for(dir_path: Path, nid: str) -> list:
    return sorted(dir_path.glob(f"{nid}*.md"))


class TestUpdateSelfHeal:
    """A3：update_note 写规则名 + 删旧（自愈）+ 成功后重钉 pin，全程单文件"""

    def test_edit_title_on_diverged_name_canonicalizes(self, cli_fast):
        """A3：发散名笔记经 edit --title 后规范化为规则名，全程单文件"""
        add_result = cli_fast.add(
            "发散名自愈场景的正文内容。", title="自愈前旧题甲", note_type="permanent"
        )
        assert add_result.success, add_result.output
        note_id = add_result.data["note"]["id"]
        original = Path(add_result.data["note"]["filepath"])
        assert original.exists()

        diverged = _diverge(str(original))
        assert diverged.exists() and not original.exists()

        edit_result = cli_fast.edit(note_id, title="自愈后新题乙")
        assert edit_result.success, edit_result.output

        # 规范化：唯一文件 = 按新标题现算的规则名；发散名已删
        canonical = diverged.parent / f"{note_id}-自愈后新题乙.md"
        assert _files_for(diverged.parent, note_id) == [
            canonical
        ], f"应只剩规范名单文件，实际 {sorted(diverged.parent.glob(f'{note_id}*.md'))}"
        assert "自愈后新题乙" in canonical.read_text(encoding="utf-8")

    def test_second_save_after_update_no_resurrect(self, mock_embedding_backend):
        """A3：同对象 update_note 后再 save_note，不复活旧路径（重钉 pin 契约）"""
        import jfox.note as note_module
        from jfox.config import use_kb
        from jfox.models import NoteType

        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                n = note_module.create_note(
                    "重钉 pin 契约的正文内容。",
                    title="重钉契约旧题丙",
                    note_type=NoteType.PERMANENT,
                )
                assert note_module.save_note(n, add_to_index=False)
                rules_path = n.filepath

                diverged = _diverge(str(rules_path))

                # 从磁盘加载：pin 必须指向发散的真实路径
                loaded = note_module.load_note_by_id(n.id)
                assert loaded is not None
                assert loaded.filepath == diverged

                loaded.title = "重钉契约新题丁"
                assert note_module.update_note(loaded, add_to_index=False)

                # 自愈：规则名唯一，发散名已删
                canonical = loaded.expected_filepath
                assert canonical.exists()
                assert not diverged.exists()
                assert _files_for(canonical.parent, loaded.id) == [canonical]

                # 关键契约：update_note 成功后 pin 已重钉到刚写入的路径，
                # 同对象再 save_note（就地写）不得在发散旧路径复活同 id 双文件
                assert note_module.save_note(loaded, add_to_index=False)
                assert loaded.filepath == canonical
                assert _files_for(canonical.parent, loaded.id) == [canonical]


class TestAddBackfill:
    """A4：add 链接发散名目标 → 单文件 + backlinks 落真实文件"""

    def test_add_link_to_diverged_target_keeps_single_file(self, cli_fast):
        """A4：add 引用 [[发散名目标]] 时回填落在真实文件，不产生同 id 双文件"""
        import jfox.note as note_module

        add_a = cli_fast.add("回填目标甲的正文本体。", title="回填目标甲", note_type="permanent")
        assert add_a.success, add_a.output
        a_id = add_a.data["note"]["id"]
        diverged_a = _diverge(add_a.data["note"]["filepath"])
        assert diverged_a.exists()

        add_b = cli_fast.add(
            "正文引用 [[回填目标甲]] 作为论据。",
            title="链向发散靶标的笔记乙",
            note_type="permanent",
        )
        assert add_b.success, add_b.output
        b_id = add_b.data["note"]["id"]

        # 单文件：目标笔记仍只有那份发散名文件（修复前回填会另写在规则名路径）
        assert _files_for(diverged_a.parent, a_id) == [diverged_a]
        # backlinks 落真实文件：直接解析发散文件 frontmatter 真值
        loaded_a = note_module.load_note(diverged_a)
        assert loaded_a is not None
        assert b_id in loaded_a.backlinks


class TestEditBackfill:
    """A5：edit 增/删链接时对发散名目标的 backlink 增量同步 → 单文件 + 落位"""

    def test_edit_add_link_diverged_target_keeps_single_file(self, cli_fast):
        """A5：edit 新增链接指向发散名目标 → backlinks 落真实文件，单文件"""
        import jfox.note as note_module

        # 目标笔记先行发散名化
        add_b = cli_fast.add(
            "编辑补链目标的正文内容。", title="回链编辑目标丙", note_type="permanent"
        )
        assert add_b.success, add_b.output
        b_id = add_b.data["note"]["id"]
        diverged_b = _diverge(add_b.data["note"]["filepath"])
        assert diverged_b.exists()

        # 源笔记初始无链接，edit 时补上指向发散名目标的链接
        add_a = cli_fast.add(
            "初始无链接的普通正文。", title="编辑补链笔记丁", note_type="permanent"
        )
        assert add_a.success, add_a.output
        a_id = add_a.data["note"]["id"]

        edit_result = cli_fast.edit(a_id, content="补上链接 [[回链编辑目标丙]] 的正文。")
        assert edit_result.success, edit_result.output

        # 单文件 + backlinks 落真实文件
        assert _files_for(diverged_b.parent, b_id) == [diverged_b]
        loaded_b = note_module.load_note(diverged_b)
        assert loaded_b is not None
        assert a_id in loaded_b.backlinks

    def test_edit_remove_link_diverged_target_keeps_single_file(self, cli_fast):
        """A5：edit 移除链接后发散名目标的 backlinks 同步摘除，仍单文件"""
        import jfox.note as note_module

        # 目标笔记先行发散名化
        add_b = cli_fast.add("摘链目标的正文内容。", title="摘链目标戊", note_type="permanent")
        assert add_b.success, add_b.output
        b_id = add_b.data["note"]["id"]
        diverged_b = _diverge(add_b.data["note"]["filepath"])
        assert diverged_b.exists()

        # 源笔记创建时即含链接，add 回填使 B.backlinks 含 A（前置确认，否则测试自身无效）
        add_a = cli_fast.add(
            "带链接 [[摘链目标戊]] 的初始正文。", title="移除链接笔记己", note_type="permanent"
        )
        assert add_a.success, add_a.output
        a_id = add_a.data["note"]["id"]
        seeded_b = note_module.load_note(diverged_b)
        assert seeded_b is not None and a_id in seeded_b.backlinks

        # edit 换成无链接正文 → 触发 backlinks 增量移除
        edit_result = cli_fast.edit(a_id, content="链接已移除的新正文。")
        assert edit_result.success, edit_result.output

        # 单文件 + 发散文件 frontmatter 真值已摘除
        assert _files_for(diverged_b.parent, b_id) == [diverged_b]
        loaded_b = note_module.load_note(diverged_b)
        assert loaded_b is not None
        assert a_id not in loaded_b.backlinks


class TestRebuildBacklinks:
    """A6：index rebuild --backlinks 触及发散名笔记时就地写单文件"""

    def test_rebuild_touches_diverged_note_in_place(self, cli_fast):
        """A6：手改发散文件 frontmatter 塞假 backlink id → rebuild 就地重算清除，单文件"""
        import jfox.note as note_module

        add_n = cli_fast.add(
            "重建回链的正文内容。", title="重建回链发散靶庚", note_type="permanent"
        )
        assert add_n.success, add_n.output
        n_id = add_n.data["note"]["id"]
        diverged_n = _diverge(add_n.data["note"]["filepath"])
        assert diverged_n.exists()

        # 直接改发散文件 frontmatter：给 backlinks 塞一个不存在的假 id（YAML flow 写法合法）
        fake_id = "99990101000000"
        raw = diverged_n.read_text(encoding="utf-8")
        assert "backlinks: []" in raw
        diverged_n.write_text(
            raw.replace("backlinks: []", f"backlinks: ['{fake_id}']"), encoding="utf-8"
        )
        poisoned = note_module.load_note(diverged_n)
        assert poisoned is not None and fake_id in poisoned.backlinks  # 前置确认污染成功

        rebuild = cli_fast.index_rebuild(backlinks=True)
        assert rebuild.success, rebuild.output
        assert rebuild.data is not None
        assert rebuild.data.get("backlinks_rebuilt") is True
        assert rebuild.data.get("backlinks_updated", 0) >= 1
        assert rebuild.data.get("backlinks_failed") == 0

        # 就地写（save_note 契约）：仍是那一份发散名文件，不在规则名另写双文件
        assert _files_for(diverged_n.parent, n_id) == [diverged_n]
        # 假 id 被重算清除：frontmatter 真值 + 文件文本双断言
        rebuilt = note_module.load_note(diverged_n)
        assert rebuilt is not None
        assert fake_id not in rebuilt.backlinks
        assert fake_id not in diverged_n.read_text(encoding="utf-8")


class TestShowDelete:
    """A7：show 可读发散名笔记 + delete 删真实文件"""

    def test_show_reads_diverged_note(self, cli_fast):
        """A7：show 发散名笔记 success=true（修复前按规则名找文件报 Errno 2）"""
        add_n = cli_fast.add(
            "展示可读性的正文内容。", title="发散可读展示壬", note_type="permanent"
        )
        assert add_n.success, add_n.output
        n_id = add_n.data["note"]["id"]
        diverged_n = _diverge(add_n.data["note"]["filepath"])
        assert diverged_n.exists()

        show_result = cli_fast.run("show", n_id, "--json")
        assert show_result.success, show_result.output
        # ZKCLI.run 对显式传 --json 的命令不自动解析 data，直接从 stdout 读 JSON 真值
        show_data = json.loads(show_result.stdout)
        assert show_data["success"] is True
        assert show_data["id"] == n_id
        assert show_data["title"] == "发散可读展示壬"
        # filepath 即钉住的真实发散路径
        assert show_data["filepath"] == str(diverged_n)

    def test_delete_removes_real_file(self, cli_fast):
        """A7：delete --force 删真实发散文件（无入链前置）→ 按 id glob 为空"""
        add_n = cli_fast.add(
            "无入链可安全删除的正文。", title="无链可删发散癸", note_type="permanent"
        )
        assert add_n.success, add_n.output
        n_id = add_n.data["note"]["id"]
        diverged_n = _diverge(add_n.data["note"]["filepath"])
        assert diverged_n.exists()

        del_result = cli_fast.delete(n_id, force=True)
        assert del_result.success, del_result.output
        assert del_result.data is not None
        assert del_result.data["success"] is True

        # 真实文件被删：按 id 前缀 glob 为空（修复前可能去删不存在的规则名路径）
        assert _files_for(diverged_n.parent, n_id) == []
        assert not diverged_n.exists()


class TestMocMemberBackfill:
    """A8：MOC 成员回填（python 级 backfill_moc_backlinks）→ 发散名成员单文件"""

    def test_moc_backfill_diverged_member_keeps_single_file(self, mock_embedding_backend):
        """A8：backfill_moc_backlinks 对发散名成员就地写，backlinks 含 moc.id 且单文件"""
        import jfox.note as note_module
        from jfox.config import use_kb
        from jfox.moc.generate import backfill_moc_backlinks
        from jfox.models import NoteType

        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                moc = note_module.create_note(
                    "结构地图的导航正文。", title="结构地图子", note_type=NoteType.STRUCTURE
                )
                assert note_module.save_note(moc, add_to_index=False)

                member = note_module.create_note(
                    "地图成员的正文内容。", title="地图成员丑", note_type=NoteType.PERMANENT
                )
                assert note_module.save_note(member, add_to_index=False)
                diverged_member = _diverge(str(member.filepath))
                assert diverged_member.exists()

                result = backfill_moc_backlinks(moc, [member.id])
                assert member.id in result.changed_ids
                assert result.failed_ids == ()

                # 单文件 + backlinks 落发散名真实文件
                assert _files_for(diverged_member.parent, member.id) == [diverged_member]
                loaded = note_module.load_note(diverged_member)
                assert loaded is not None
                assert moc.id in loaded.backlinks
