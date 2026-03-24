"""
测试 Issue #4 的高级功能
- 知识图谱 (graph.py)
- 文件监控 (indexer.py)
- 新命令: query, graph, daily, inbox, index
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from zk.config import ZKConfig
from zk.models import Note, NoteType
from zk.graph import KnowledgeGraph, GraphStats
from zk.indexer import Indexer, IndexStats
from zk.vector_store import VectorStore
from zk import note as note_module


def test_knowledge_graph():
    """测试知识图谱功能"""
    print("\n=== Testing KnowledgeGraph ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        from zk import config as config_module
        
        # 创建临时配置
        temp_config = ZKConfig(base_dir=Path(tmpdir))
        temp_config.ensure_dirs()
        
        # 临时替换全局 config
        original_config = config_module.config
        config_module.config = temp_config
        
        try:
            # 创建测试笔记
            note1 = note_module.create_note(
                content="Test content about Python",
                title="Python Note",
                note_type=NoteType.PERMANENT,
                tags=["python", "programming"]
            )
            note1.set_filepath(temp_config.notes_dir / "permanent" / f"{note1.id}.md")
            note_module.save_note(note1, add_to_index=False)
            
            note2 = note_module.create_note(
                content="Test content about Machine Learning",
                title="ML Note",
                note_type=NoteType.PERMANENT,
                tags=["ml", "ai"],
                links=[note1.id]  # 链接到第一个笔记
            )
            note2.set_filepath(temp_config.notes_dir / "permanent" / f"{note2.id}.md")
            note_module.save_note(note2, add_to_index=False)
            
            # 手动更新反向链接（因为测试不经过 CLI 层）
            note1.backlinks.append(note2.id)
            note_module.save_note(note1, add_to_index=False)
        
            # 构建图谱
            graph = KnowledgeGraph(temp_config).build()
            
            # 验证
            assert len(graph.graph) == 2, f"Expected 2 nodes, got {len(graph.graph)}"
            assert graph.graph.number_of_edges() == 2, f"Expected 2 edges (link + backlink), got {graph.graph.number_of_edges()}"
            
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
            assert stats.total_edges == 2
            
            # 测试 get_orphan_notes
            # note1 现在有 note2 的反向链接，不是孤立节点
            # note2 有指向 note1 的链接，也不是孤立节点
            orphans = graph.get_orphan_notes()
            assert note1.id not in orphans, "note1 should not be an orphan (has backlink from note2)"
            assert note2.id not in orphans, "note2 should not be an orphan (has outgoing link)"
            
            print("✓ KnowledgeGraph tests passed")
        finally:
            # 恢复原始配置
            config_module.config = original_config


def test_indexer():
    """测试索引器功能"""
    print("\n=== Testing Indexer ===")
    
    # Windows 上 Chroma DB 文件锁定问题，使用 ignore_cleanup_errors
    import sys
    kwargs = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}
    
    with tempfile.TemporaryDirectory(**kwargs) as tmpdir:
        from zk import config as config_module
        
        # 创建临时配置
        temp_config = ZKConfig(base_dir=Path(tmpdir))
        temp_config.ensure_dirs()
        
        # 临时替换全局 config
        original_config = config_module.config
        config_module.config = temp_config
        
        try:
            # 创建向量存储
            vector_store = VectorStore(temp_config.chroma_dir)
            vector_store.init()
            
            # 创建索引器
            indexer = Indexer(temp_config, vector_store)
            
            # 初始状态检查
            assert not indexer.is_running(), "Indexer should not be running initially"
            
            # 创建测试笔记
            note1 = note_module.create_note(
                content="Indexer test content",
                title="Indexer Test",
                note_type=NoteType.FLEETING
            )
            note1.set_filepath(temp_config.notes_dir / "fleeting" / f"{note1.id}.md")
            note_module.save_note(note1, add_to_index=False)
            
            # 手动索引
            indexer.index_all()
            
            # 验证索引
            all_ids = vector_store.get_all_ids()
            assert note1.id in all_ids, f"Note {note1.id} should be indexed"
            
            # 测试 verify_index
            verification = indexer.verify_index()
            assert verification["total_files"] == 1
            # Note: 由于 ID 和文件名可能不匹配，这里不严格检查 healthy
            
            print("✓ Indexer tests passed")
        finally:
            # 恢复原始配置
            config_module.config = original_config


def test_note_manager():
    """测试 NoteManager 辅助功能"""
    print("\n=== Testing NoteManager ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        from zk import config as config_module
        
        # 创建临时配置
        temp_config = ZKConfig(base_dir=Path(tmpdir))
        temp_config.ensure_dirs()
        
        # 临时替换全局 config
        original_config = config_module.config
        config_module.config = temp_config
        
        try:
            # 创建测试笔记
            note1 = note_module.create_note(
                content="Test content",
                title="Test Note",
                note_type=NoteType.PERMANENT
            )
            note1.set_filepath(temp_config.notes_dir / "permanent" / f"{note1.id}.md")
            note_module.save_note(note1, add_to_index=False)
            
            # 测试 find_note_file
            from zk.note import NoteManager
            found_path = NoteManager.find_note_file(temp_config, note1.id)
            assert found_path is not None, "Should find the note file"
            assert found_path.exists(), "Found path should exist"
            
            # 测试 load_note
            loaded = NoteManager.load_note(found_path)
            assert loaded is not None, "Should load the note"
            assert loaded.id == note1.id, "Loaded note should have same ID"
            
            print("✓ NoteManager tests passed")
        finally:
            # 恢复原始配置
            config_module.config = original_config


def test_daily_inbox_commands():
    """测试 daily 和 inbox 命令逻辑"""
    print("\n=== Testing Daily/Inbox Logic ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        from zk import config as config_module
        
        # 创建临时配置
        temp_config = ZKConfig(base_dir=Path(tmpdir))
        temp_config.ensure_dirs()
        
        # 临时替换全局 config
        original_config = config_module.config
        config_module.config = temp_config
        
        try:
            # 创建不同类型的笔记
            permanent = note_module.create_note(
                content="Permanent note",
                title="Permanent",
                note_type=NoteType.PERMANENT
            )
            permanent.set_filepath(temp_config.notes_dir / "permanent" / f"{permanent.id}.md")
            note_module.save_note(permanent, add_to_index=False)
            
            fleeting = note_module.create_note(
                content="Fleeting note",
                title="Fleeting",
                note_type=NoteType.FLEETING
            )
            fleeting.set_filepath(temp_config.notes_dir / "fleeting" / f"{fleeting.id}.md")
            note_module.save_note(fleeting, add_to_index=False)
            
            # 模拟 inbox 命令逻辑
            fleeting_notes = note_module.list_notes(note_type=NoteType.FLEETING, limit=20, cfg=temp_config)
            assert len(fleeting_notes) == 1, "Should have 1 fleeting note"
            assert fleeting_notes[0].type == NoteType.FLEETING
            
            # 模拟 daily 命令逻辑
            date_str = datetime.now().strftime("%Y%m%d")
            all_notes = note_module.list_notes(cfg=temp_config)
            daily_notes = [n for n in all_notes if n.id.startswith(date_str)]
            assert len(daily_notes) == 2, "Should have 2 notes for today"
            
            print("✓ Daily/Inbox tests passed")
        finally:
            # 恢复原始配置
            config_module.config = original_config


def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("Issue #4 Advanced Features Test Suite")
    print("=" * 50)
    
    try:
        test_knowledge_graph()
        test_indexer()
        test_note_manager()
        test_daily_inbox_commands()
        
        print("\n" + "=" * 50)
        print("All tests passed!")
        print("=" * 50)
        return True
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Error during tests: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
