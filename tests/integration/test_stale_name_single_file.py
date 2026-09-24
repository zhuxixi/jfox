"""
测试类型: 集成测试
目标功能: #549 发散名（磁盘名 ≠ 规则名）笔记经 update_note 触碰后自愈为规则名（A3）
预估耗时: < 10秒
依赖要求: 临时知识库，mock embedding backend（cli_fast）

发散名 = 只 rename 文件（保留 id 前缀），不改 frontmatter——
等价于「外部改标题未同步改名」的场景。
"""

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
