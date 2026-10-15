"""
测试类型: 集成测试
目标功能: 标题含 # 的 wiki-link 端到端解析正确（issue #458 · A5）
预估耗时: 数秒

复用 conftest 的 temp_kb / cli fixture（见 tests/conftest.py）：
add / show 均为真实 CLI 子进程落库，读回校验 frontmatter links。
干扰笔记（A5「不含任何指向干扰笔记的条目」）用于暴露旧行为——
旧实现把 [[标题#后缀]] 在 # 处截断后走子串兜底，截断前缀同时命中
真实目标与干扰标题，谁先入索引（文件名倒序）谁被静默选中。
"""

import time
from pathlib import Path

import pytest

from jfox.models import Note

pytestmark = [pytest.mark.integration]

# 同前缀的两条标题：真实目标（含 #），干扰笔记（不含 # 的讨论稿）
TARGET_TITLE = "jfox 增量索引修复方案（#387）：verify 差集"
DECOY_TITLE = "jfox 增量索引修复方案（讨论稿）"


def _load_note(filepath: str) -> Note:
    p = Path(filepath)
    return Note.from_markdown(p.read_text(encoding="utf-8"), p)


class TestWikiLinkHashTitleEndToEnd:
    def test_add_note_with_hash_title_link_resolves_to_real_target(self, temp_kb, cli):
        """A5：add 正文含 [[完整标题（含#）]] 后，show --json 的 links 指向真实目标"""
        target = cli.add("目标笔记正文", title=TARGET_TITLE, note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        # 干扰笔记晚于目标创建：文件名（时间戳前缀）倒序排在真实目标之前，
        # 旧实现的子串兜底按索引顺序会先命中它（截断前缀同时是两者标题的子串）
        time.sleep(1.1)  # 错开秒级时间戳，保证文件名排序确定性
        decoy = cli.add("干扰笔记正文", title=DECOY_TITLE, note_type="permanent")
        assert decoy.success
        decoy_id = decoy.data["note"]["id"]

        source = cli.add(
            f"参见 [[{TARGET_TITLE}]]",
            title="引用方笔记",
            note_type="permanent",
        )
        assert source.success

        shown = cli.run("show", source.data["note"]["id"])
        assert shown.success
        links = shown.data["links"]
        assert target_id in links
        assert decoy_id not in links

        # 落盘 frontmatter 与 show 输出一致（读回同一存储路径）
        n = _load_note(source.data["note"]["filepath"])
        assert n.links == [target_id]
