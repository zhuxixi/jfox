"""
测试类型: 集成测试
目标功能: 标题含 # 的 wiki-link 端到端解析正确（issue #458 · A5），
          KnowledgeGraph 正文建边指向真实目标（issue #458 · A7）
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

from jfox.config import ZKConfig
from jfox.graph import KnowledgeGraph
from jfox.models import Note, NoteType
from jfox.note import create_note, save_note

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


class TestWikiLinkHashTitleGraph:
    def test_graph_edge_from_hash_title_link(self, temp_kb, cli):
        """A7：[[完整标题（含#）]] 在 graph 中生成指向真实目标的边"""
        target = cli.add(
            "目标笔记正文", title="pi-agent-board issue #42 键位决策", note_type="permanent"
        )
        assert target.success
        target_id = target.data["note"]["id"]

        # 干扰笔记标题恰为 # 前缀：旧实现在 # 处截断后做精确标题匹配，
        # 会确定性地命中它（精确匹配先于子串兜底，与遍历顺序无关）；
        # 新实现按完整原文（candidates[0]）精确匹配真实目标，前缀候选不参与。
        decoy = cli.add("干扰笔记正文", title="pi-agent-board issue", note_type="permanent")
        assert decoy.success
        decoy_id = decoy.data["note"]["id"]

        # 引用方直接落盘且 frontmatter links 置空：隔离 build() 第三趟的
        # 正文 [[...]] 提取建边（若走 cli.add，链接已被解析进 frontmatter，
        # 第二趟会先建边，掩盖第三趟行为）。
        source = create_note(
            content="参见 [[pi-agent-board issue #42 键位决策]]",
            title="图谱引用方",
            note_type=NoteType.PERMANENT,
        )
        source.set_filepath(Path(temp_kb) / "notes" / "permanent" / f"{source.id}.md")
        assert save_note(source, add_to_index=False)
        source_id = source.id

        # 构建方式同 tests/test_advanced_features.py::test_knowledge_graph：
        # 直接以 KB 路径构造 ZKConfig，不依赖全局单例
        graph = KnowledgeGraph(ZKConfig(base_dir=temp_kb)).build()

        assert graph.graph.has_edge(source_id, target_id)
        assert graph.graph.edges[source_id, target_id]["type"] == "wiki_link"
        assert not graph.graph.has_edge(source_id, decoy_id)
