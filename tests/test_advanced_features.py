"""
测试 Issue #4 的高级功能
- 知识图谱 (graph.py)
- 文件监控 (indexer.py)
- 新命令: query, graph, daily, inbox, index
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from jfox import config as config_module
from jfox import note as note_module
from jfox.config import ZKConfig
from jfox.graph import KnowledgeGraph
from jfox.indexer import Indexer
from jfox.models import NoteType
from jfox.vector_store import VectorStore


@pytest.fixture
def isolated_config(tmp_path):
    """创建临时配置并 patch 全局 config，保证测试隔离"""
    temp_config = ZKConfig(base_dir=tmp_path)
    temp_config.ensure_dirs()
    with patch.object(config_module, "config", temp_config):
        yield temp_config


def test_knowledge_graph(isolated_config):
    """测试知识图谱功能"""
    # 创建测试笔记
    note1 = note_module.create_note(
        content="Test content about Python",
        title="Python Note",
        note_type=NoteType.PERMANENT,
        tags=["python", "programming"],
    )
    note1.set_filepath(isolated_config.notes_dir / "permanent" / f"{note1.id}.md")
    note_module.save_note(note1, add_to_index=False)

    note2 = note_module.create_note(
        content="Test content about Machine Learning",
        title="ML Note",
        note_type=NoteType.PERMANENT,
        tags=["ml", "ai"],
        links=[note1.id],  # 链接到第一个笔记
    )
    note2.set_filepath(isolated_config.notes_dir / "permanent" / f"{note2.id}.md")
    note_module.save_note(note2, add_to_index=False)

    # 构建图谱（build() 从 frontmatter links 建边，不单独为 backlinks 建边）
    graph = KnowledgeGraph(isolated_config).build()

    # 验证
    assert len(graph.graph) == 2, f"Expected 2 nodes, got {len(graph.graph)}"
    # note2.links=[note1.id] 产生一条有向边 note2→note1
    assert (
        graph.graph.number_of_edges() == 1
    ), f"Expected 1 edge (note2→note1), got {graph.graph.number_of_edges()}"

    # 测试 get_neighbors
    neighbors = graph.get_neighbors(note1.id)
    assert note2.id in neighbors, "note2 should be a neighbor of note1"

    # 测试 get_related
    related = graph.get_related(note2.id, depth=1)
    assert "depth_1" in related, "Should have depth_1 key"
    assert note1.id in related["depth_1"], "note1 should be related to note2"

    # 测试 get_stats
    stats = graph.get_stats()
    assert stats.total_nodes == 2
    assert stats.total_edges == 1  # note2→note1 一条有向边

    # 测试 get_orphan_notes
    orphans = graph.get_orphan_notes()
    assert note1.id not in orphans, "note1 should not be an orphan (has backlink from note2)"
    assert note2.id not in orphans, "note2 should not be an orphan (has outgoing link)"


def test_indexer(isolated_config):
    """测试索引器功能"""
    # 创建向量存储
    vector_store = VectorStore(isolated_config.chroma_dir)
    vector_store.init()

    # 创建索引器
    indexer = Indexer(isolated_config, vector_store)

    # 初始状态检查
    assert not indexer.is_running(), "Indexer should not be running initially"

    # 创建测试笔记
    note1 = note_module.create_note(
        content="Indexer test content", title="Indexer Test", note_type=NoteType.FLEETING
    )
    note1.set_filepath(isolated_config.notes_dir / "fleeting" / f"{note1.id}.md")
    note_module.save_note(note1, add_to_index=False)

    # 手动索引
    indexer.index_all()

    # 验证索引
    all_ids = vector_store.get_all_ids()
    assert note1.id in all_ids, f"Note {note1.id} should be indexed"

    # 测试 verify_index
    verification = indexer.verify_index()
    assert verification["total_files"] == 1


def test_note_manager(isolated_config):
    """测试 NoteManager 辅助功能"""
    # 创建测试笔记
    note1 = note_module.create_note(
        content="Test content", title="Test Note", note_type=NoteType.PERMANENT
    )
    note1.set_filepath(isolated_config.notes_dir / "permanent" / f"{note1.id}.md")
    note_module.save_note(note1, add_to_index=False)

    # 测试 find_note_file
    from jfox.note import NoteManager

    found_path = NoteManager.find_note_file(isolated_config, note1.id)
    assert found_path is not None, "Should find the note file"
    assert found_path.exists(), "Found path should exist"

    # 测试 load_note
    loaded = NoteManager.load_note(found_path)
    assert loaded is not None, "Should load the note"
    assert loaded.id == note1.id, "Loaded note should have same ID"


def test_daily_inbox_commands(isolated_config):
    """测试 daily 和 inbox 命令逻辑"""
    # 创建不同类型的笔记
    permanent = note_module.create_note(
        content="Permanent note", title="Permanent", note_type=NoteType.PERMANENT
    )
    permanent.set_filepath(isolated_config.notes_dir / "permanent" / f"{permanent.id}.md")
    note_module.save_note(permanent, add_to_index=False)

    fleeting = note_module.create_note(
        content="Fleeting note", title="Fleeting", note_type=NoteType.FLEETING
    )
    fleeting.set_filepath(isolated_config.notes_dir / "fleeting" / f"{fleeting.id}.md")
    note_module.save_note(fleeting, add_to_index=False)

    # 模拟 inbox 命令逻辑
    fleeting_notes = note_module.list_notes(
        note_type=NoteType.FLEETING, limit=20, cfg=isolated_config
    )
    assert len(fleeting_notes) == 1, "Should have 1 fleeting note"
    assert fleeting_notes[0].type == NoteType.FLEETING

    # 模拟 daily 命令逻辑
    date_str = datetime.now().strftime("%Y%m%d")
    all_notes = note_module.list_notes(cfg=isolated_config)
    daily_notes = [n for n in all_notes if n.id.startswith(date_str)]
    assert len(daily_notes) == 2, "Should have 2 notes for today"


def test_verify_index_matches_filenames_to_ids(isolated_config):
    """验证 verify_index 正确匹配文件名和索引 ID（不误报 missing/orphaned）

    Issue #103: 文件名含 slug 或 fleeting 连字符，索引 ID 为纯数字，格式不匹配导致全部误报
    """
    vector_store = VectorStore(isolated_config.chroma_dir)
    vector_store.init()
    indexer = Indexer(isolated_config, vector_store)

    # 创建一个 fleeting 笔记（文件名含连字符）
    note1 = note_module.create_note(
        content="Fleeting test", title="Fleeting Test", note_type=NoteType.FLEETING
    )
    note1.set_filepath(
        isolated_config.notes_dir / "fleeting" / f"{note1.id[:8]}-{note1.id[8:]}.md"
    )
    note_module.save_note(note1, add_to_index=False)

    # 创建一个 permanent 笔记（文件名含 slug）
    note2 = note_module.create_note(
        content="Permanent test", title="Test Slug", note_type=NoteType.PERMANENT
    )
    note2.set_filepath(
        isolated_config.notes_dir / "permanent" / f"{note2.id}-test-slug.md"
    )
    note_module.save_note(note2, add_to_index=False)

    # 索引所有笔记
    indexer.index_all()

    # verify 应报告 healthy
    result = indexer.verify_index()
    assert result["healthy"] is True, (
        f"Expected healthy=True, got missing={result['missing_from_index']}, "
        f"orphaned={result['orphaned_in_index']}"
    )
    assert result["missing_from_index"] == []
    assert result["orphaned_in_index"] == []
    assert result["total_files"] == 2
    assert result["total_indexed"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
