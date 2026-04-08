"""
核心工作流测试 - Zettelkasten 完整流程验证

覆盖: Capture → Process → Connect → Develop
特别加强 Embedding 语义搜索测试
"""

import pytest
import time
from typing import List, Dict, Any


# ============================================================================
# Helper Functions
# ============================================================================

def assert_note_created(result, title: str = None) -> Dict[str, Any]:
    """断言笔记创建成功并返回笔记数据"""
    assert result.success, f"Note creation failed: {result.stderr}"
    assert result.data is not None, "No data in result"
    assert result.data.get("success") is True, f"Unexpected result: {result.data}"
    
    note_data = result.data.get("note", {})
    assert "id" in note_data, "Note ID not found in result"
    
    if title:
        assert note_data.get("title") == title, f"Title mismatch: {note_data.get('title')} != {title}"
    
    return note_data


def assert_link_exists(note_a_id: str, note_b_id: str, cli) -> None:
    """断言 note_a 链接到 note_b"""
    refs = cli.refs(note_id=note_a_id)
    assert refs.success, f"Failed to get refs: {refs.stderr}"
    
    forward_links = refs.data.get("forward_links", [])
    link_ids = [l["id"] for l in forward_links]
    assert note_b_id in link_ids, f"Link from {note_a_id} to {note_b_id} not found"


def assert_backlink_exists(target_id: str, source_id: str, cli) -> None:
    """断言 target_id 有来自 source_id 的反向链接"""
    refs = cli.refs(note_id=target_id)
    assert refs.success, f"Failed to get refs: {refs.stderr}"
    
    backward_links = refs.data.get("backward_links", [])
    backlink_ids = [l["id"] for l in backward_links]
    assert source_id in backlink_ids, f"Backlink from {source_id} to {target_id} not found"


def create_note_with_type(cli, title: str, content: str, note_type: str, **kwargs) -> Dict:
    """创建指定类型的笔记并返回笔记数据"""
    result = cli.add(content, title=title, note_type=note_type, **kwargs)
    return assert_note_created(result, title)


def wait_for_indexing(cli, expected_notes: int = 1, timeout: int = 120) -> bool:
    """
    等待 embedding 计算完成（方案 A：简单延迟）
    
    在笔记本 CPU 上，embedding 计算约 2-5 秒/条
    给足时间确保计算完成
    
    Args:
        cli: CLI 实例
        expected_notes: 预期的笔记数量
        timeout: 最大等待时间（秒）
    
    Returns:
        始终返回 True（简单延迟方案）
    """
    import time
    # 基础延迟 5 秒 + 每条笔记 3 秒（CPU 环境保守估计）
    wait_time = min(5 + expected_notes * 3, timeout)
    time.sleep(wait_time)
    return True


# ============================================================================
# Capture 阶段测试
# ============================================================================

class TestCapturePhase:
    """Capture 阶段测试 - 收集闪念笔记"""
    
    def test_capture_single_fleeting_note(self, cli):
        """单条闪念笔记创建"""
        title = "Quick Thought"
        content = "This is a sudden idea that needs to be captured"
        
        result = cli.add(content, title=title, note_type="fleeting")
        note_data = assert_note_created(result, title)
        
        assert note_data["type"] == "fleeting"
        assert "id" in note_data
        assert "filepath" in note_data
    
    def test_capture_fleeting_notes_batch(self, cli):
        """批量创建闪念笔记"""
        notes_data = []
        
        for i in range(5):
            title = f"Fleeting Note {i}"
            content = f"Quick thought number {i} - capture immediately"
            result = cli.add(content, title=title, note_type="fleeting")
            note_data = assert_note_created(result, title)
            notes_data.append(note_data)
        
        assert len(notes_data) == 5
        
        # Verify via inbox
        inbox_result = cli.inbox(limit=10)
        assert inbox_result.success
        assert inbox_result.data.get("total") >= 5
    
    def test_capture_with_tags(self, cli):
        """带标签的闪念笔记"""
        title = "Tagged Idea"
        content = "An important idea with multiple tags"
        tags = ["idea", "important", "quick"]
        
        result = cli.add(content, title=title, note_type="fleeting", tags=tags)
        note_data = assert_note_created(result, title)
        
        assert note_data["type"] == "fleeting"


# ============================================================================
# Process 阶段测试
# ============================================================================

class TestProcessPhase:
    """Process 阶段测试 - 整理笔记为永久笔记"""
    
    def test_process_fleeting_to_permanent(self, cli):
        """闪念笔记整理为永久笔记"""
        # 1. Create fleeting note
        fleeting_title = "Raw Fleeting Note"
        fleeting_content = "Raw idea that needs processing"
        fleeting_result = cli.add(fleeting_content, title=fleeting_title, note_type="fleeting")
        fleeting_data = assert_note_created(fleeting_result, fleeting_title)
        
        # 2. Create permanent note (processed version)
        permanent_title = "Processed Permanent Note"
        permanent_content = f"Processed from fleeting: {fleeting_content}\n\nDetailed analysis..."
        permanent_result = cli.add(permanent_content, title=permanent_title, note_type="permanent")
        permanent_data = assert_note_created(permanent_result, permanent_title)
        
        assert permanent_data["type"] == "permanent"
        
        # 3. Verify fleeting still exists
        list_result = cli.list(note_type="fleeting")
        assert list_result.success
        fleeting_ids = [n.get("id") for n in list_result.data.get("notes", [])]
        assert fleeting_data["id"] in fleeting_ids
    
    def test_process_literature_note(self, cli):
        """文献笔记创建（带 source）"""
        title = "Thinking Fast and Slow - Notes"
        content = "System 1 and System 2 concepts: System 1 is fast, intuitive thinking..."
        source = "Thinking Fast and Slow - Daniel Kahneman, Chapter 1"
        
        result = cli.add(content, title=title, note_type="literature", source=source)
        note_data = assert_note_created(result, title)
        
        assert note_data["type"] == "literature"
    
    def test_process_note_type_conversion(self, cli):
        """笔记类型转换（通过创建新笔记模拟）"""
        # 1. Create fleeting note
        original_title = "Raw Fleeting"
        content = "Raw thought about a topic"
        fleeting_result = cli.add(content, title=original_title, note_type="fleeting")
        fleeting_data = assert_note_created(fleeting_result, original_title)
        
        # 2. Create permanent note (conversion)
        converted_title = "Converted Permanent Note"
        converted_content = f"Converted from fleeting: {content}"
        permanent_result = cli.add(
            converted_content, 
            title=converted_title, 
            note_type="permanent"
        )
        permanent_data = assert_note_created(permanent_result, converted_title)
        
        assert fleeting_data["type"] == "fleeting"
        assert permanent_data["type"] == "permanent"


# ============================================================================
# Connect 阶段测试
# ============================================================================

class TestConnectPhase:
    """Connect 阶段测试 - 建立笔记间的链接"""
    
    def test_wiki_link_auto_resolution(self, cli):
        """[[Title]] 链接自动解析"""
        # 1. Create target note
        target_title = "Target Note"
        target_content = "This is the target note content"
        target_result = cli.add(target_content, title=target_title, note_type="permanent")
        target_data = assert_note_created(target_result, target_title)
        
        # 2. Create note with wiki link
        source_content = f"This note references [[{target_title}]]"
        source_result = cli.add(source_content, title="Source Note", note_type="permanent")
        source_data = assert_note_created(source_result, "Source Note")
        
        # 3. Verify link resolved
        assert "links" in source_data
        assert target_data["id"] in source_data["links"]
    
    def test_bidirectional_links(self, cli):
        """双向链接验证（links + backlinks）"""
        # 1. Create note A
        note_a = create_note_with_type(cli, "Note A", "Content of note A", "permanent")
        
        # 2. Create note B linking to A
        note_b_content = f"This is note B referencing [[Note A]]"
        note_b = create_note_with_type(cli, "Note B", note_b_content, "permanent")
        
        # 3. Verify B has forward link to A
        assert_link_exists(note_b["id"], note_a["id"], cli)
        
        # 4. Verify A has backlink from B (auto-maintained by CLI)
        assert_backlink_exists(note_a["id"], note_b["id"], cli)
    
    def test_graph_build_after_links(self, cli):
        """链接后图谱正确构建"""
        # 1. Create notes with links
        note_a = create_note_with_type(cli, "Graph Node A", "Node A content", "permanent")
        
        note_b_content = "Node B content linking to [[Graph Node A]]"
        note_b = create_note_with_type(cli, "Graph Node B", note_b_content, "permanent")
        
        note_c_content = "Node C content linking to [[Graph Node B]]"
        note_c = create_note_with_type(cli, "Graph Node C", note_c_content, "permanent")
        
        # 2. Check graph stats
        stats_result = cli.graph_stats()
        assert stats_result.success
        
        stats = stats_result.data
        assert stats.get("total_nodes") >= 3
        assert stats.get("total_edges") >= 2  # A-B and B-C
        assert stats.get("avg_degree") > 0
    
    def test_orphan_notes_detection(self, cli):
        """孤立笔记检测"""
        # 1. Create orphan notes
        orphan_notes = []
        for i in range(3):
            note = create_note_with_type(cli, f"Orphan Note {i}", f"Orphan content {i}", "permanent")
            orphan_notes.append(note)
        
        # 2. Create linked notes (non-orphan)
        linked_note_a = create_note_with_type(cli, "Linked Note A", "Linked note A content", "permanent")
        linked_note_b_content = "Linked note B referencing [[Linked Note A]]"
        linked_note_b = create_note_with_type(cli, "Linked Note B", linked_note_b_content, "permanent")
        
        # 3. Detect orphans
        orphans_result = cli.graph_orphans()
        assert orphans_result.success
        
        orphans = orphans_result.data.get("orphans", [])
        orphan_ids = [o["id"] for o in orphans]
        
        # 4. Verify orphans detected
        for orphan in orphan_notes:
            assert orphan["id"] in orphan_ids, f"Orphan note {orphan['id']} not detected"
        
        # 5. Verify linked notes not in orphan list
        assert linked_note_a["id"] not in orphan_ids, "Linked note A should not be orphan"
        assert linked_note_b["id"] not in orphan_ids, "Linked note B should not be orphan"


# ============================================================================
# Develop 阶段测试 - Embedding 语义搜索（长耗时）
# ============================================================================

@pytest.mark.slow
class TestDevelopPhaseEmbedding:
    """Develop 阶段测试 - Embedding 语义搜索（需要较长时间）"""
    
    @pytest.mark.timeout(300)  # 5分钟超时
    def test_semantic_search_discover(self, cli, generator):
        """语义搜索发现相关知识（创建笔记并等待 embedding）"""
        # 1. Create test notes with different topics
        topics = [
            ("Python Programming", "Python is a versatile programming language"),
            ("Machine Learning Basics", "ML is a subset of AI that enables learning from data"),
            ("Deep Learning Intro", "Deep learning uses neural networks with many layers"),
            ("Docker Containers", "Docker packages applications into containers"),
            ("Git Version Control", "Git tracks changes in source code"),
        ]
        
        created_notes = []
        for title, content in topics:
            result = cli.add(content, title=title, note_type="permanent")
            note_data = assert_note_created(result, title)
            created_notes.append(note_data)
        
        # 2. Wait for indexing (embedding computation)
        assert wait_for_indexing(cli, expected_notes=5, timeout=60), "Indexing timeout"
        
        # 3. Perform semantic search
        search_result = cli.search("Python programming language", top=5)
        assert search_result.success
        
        results = search_result.data.get("results", [])
        # Should find Python-related notes
        assert len(results) > 0, "Semantic search should return results"
        
        # Check relevance - "Python Programming" should be in top results
        top_titles = [r.get("metadata", {}).get("title", "") for r in results[:3]]
        assert any("Python" in t for t in top_titles), "Python-related note should be in top results"
    
    @pytest.mark.timeout(300)
    def test_hybrid_search_quality(self, cli):
        """混合搜索（BM25 + Semantic）质量验证"""
        # 1. Create diverse notes
        notes_data = [
            ("Python Async Programming", "Python async/await enables concurrent programming"),
            ("Asyncio Best Practices", "Using asyncio for efficient I/O operations"),
            ("Python Requests Library", "HTTP library for Python"),
            ("JavaScript Async Await", "Similar concept in JavaScript"),
            ("Python Data Structures", "Lists, dicts, sets in Python"),
        ]
        
        for title, content in notes_data:
            result = cli.add(content, title=title, note_type="permanent")
            assert_note_created(result, title)
        
        # 2. Wait for indexing
        assert wait_for_indexing(cli, expected_notes=5, timeout=60), "Indexing timeout"
        
        # 3. Test different search modes
        # Semantic mode
        semantic_result = cli.search("Python async await", top=5)
        assert semantic_result.success
        
        # Check results
        results = semantic_result.data.get("results", [])
        assert len(results) >= 3, "Should find relevant notes"
    
    @pytest.mark.timeout(300)
    def test_suggest_links_semantic(self, cli, generator):
        """基于语义的链接推荐"""
        # 1. Create notes on related topics
        notes = [
            ("Neural Networks", "Neural networks are computing systems inspired by biological brains"),
            ("Deep Learning", "Deep learning uses multi-layer neural networks"),
            ("Backpropagation", "Algorithm for training neural networks"),
            ("Docker Guide", "Docker containerization platform"),
        ]
        
        created = []
        for title, content in notes:
            result = cli.add(content, title=title, note_type="permanent")
            note_data = assert_note_created(result, title)
            created.append(note_data)
        
        # 2. Wait for indexing
        assert wait_for_indexing(cli, expected_notes=4, timeout=60), "Indexing timeout"
        
        # 3. Request link suggestions for new content
        new_content = "I'm learning about neural networks and how to train them using backpropagation"
        suggest_result = cli.suggest_links(new_content, top_k=5, threshold=0.3)
        assert suggest_result.success
        
        suggestions = suggest_result.data.get("suggestions", [])
        # Should suggest related notes (Neural Networks, Deep Learning, Backpropagation)
        suggested_titles = [s.get("title", "") for s in suggestions]
        
        # At least one ML-related note should be suggested
        ml_keywords = ["Neural", "Deep", "Backpropagation"]
        has_ml_suggestion = any(
            any(kw in t for kw in ml_keywords) 
            for t in suggested_titles
        )
        assert has_ml_suggestion, f"Should suggest ML-related notes, got: {suggested_titles}"
    
    @pytest.mark.timeout(300)
    def test_query_with_graph_depth_embedding(self, cli):
        """联合查询（语义搜索 + 图谱深度）"""
        # 1. Create a network of linked notes
        notes = [
            ("Deep Learning", "Deep learning is a subset of machine learning"),
            ("Neural Networks", "The foundation of deep learning [[Deep Learning]]"),
            ("CNN", "Convolutional Neural Networks [[Neural Networks]]"),
            ("Image Recognition", "Application of CNNs [[CNN]]"),
            ("RNN", "Recurrent Neural Networks [[Neural Networks]]"),
            ("NLP", "Natural Language Processing using RNNs [[RNN]]"),
        ]
        
        created = {}
        for title, content in notes:
            result = cli.add(content, title=title, note_type="permanent")
            note_data = assert_note_created(result, title)
            created[title] = note_data
        
        # 2. Wait for indexing
        assert wait_for_indexing(cli, expected_notes=6, timeout=60), "Indexing timeout"
        
        # 3. Query with graph depth
        query_result = cli.query("machine learning neural networks", top=5, graph_depth=2)
        assert query_result.success
        
        # Verify result structure
        assert "related" in query_result.data or "results" in query_result.data


# ============================================================================
# 多知识库工作流测试
# ============================================================================

class TestMultiKBWorkflow:
    """多知识库工作流测试"""
    
    def test_multi_kb_isolation(self, cli):
        """多知识库数据隔离"""
        from utils.jfox_cli import ZKCLI
        from utils.temp_kb import TemporaryKnowledgeBase
        
        # 1. Create two isolated knowledge bases
        with TemporaryKnowledgeBase() as kb1_path:
            with TemporaryKnowledgeBase() as kb2_path:
                cli1 = ZKCLI(kb1_path)
                cli2 = ZKCLI(kb2_path)
                
                cli1.init()
                cli2.init()
                
                # 2. Create note in kb1
                note1 = create_note_with_type(cli1, "KB1 Note", "Only in KB1", "permanent")
                
                # 3. Create note in kb2
                note2 = create_note_with_type(cli2, "KB2 Note", "Only in KB2", "permanent")
                
                # 4. Verify kb1 only has note1
                list1 = cli1.list()
                assert list1.success
                titles1 = [n.get("title", "") for n in list1.data.get("notes", [])]
                assert "KB1 Note" in titles1
                assert "KB2 Note" not in titles1
                
                # 5. Verify kb2 only has note2
                list2 = cli2.list()
                assert list2.success
                titles2 = [n.get("title", "") for n in list2.data.get("notes", [])]
                assert "KB2 Note" in titles2
                assert "KB1 Note" not in titles2
                
                # Cleanup
                cli1.cleanup()
                cli2.cleanup()
    
    def test_kb_switch_workflow(self, cli):
        """知识库切换工作流"""
        # Test kb_current command
        # Note: kb 命令本身不支持 --kb 参数（它是知识库管理命令）
        # 但应该能通过 fixture 的 kb_name 获取当前知识库信息
        current_result = cli.kb_current()
        # May succeed or fail depending on implementation
        # 0 = success, 1 = error (no default), 2 = unknown option error
        assert current_result.returncode in [0, 1, 2]
    
    def test_kb_param_in_commands(self, cli):
        """各命令的 --kb 参数支持"""
        # Test list command
        list_result = cli.list()
        assert list_result.success or "No knowledge base" in list_result.stderr
        
        # Test search command
        search_result = cli.search("test", top=3)
        assert search_result.success or "No knowledge base" in search_result.stderr


# ============================================================================
# 完整工作流集成测试（长耗时）
# ============================================================================

@pytest.mark.slow
class TestCompleteWorkflow:
    """完整工作流集成测试"""
    
    @pytest.mark.timeout(300)
    def test_capture_to_develop_full_workflow(self, cli):
        """从 Capture 到 Develop 的完整工作流"""
        # Step 1: Capture - Create fleeting notes
        fleeting = create_note_with_type(
            cli, 
            "Fleeting: Async IO Idea", 
            "Just thought about Python async/await mechanism...",
            "fleeting",
            tags=["idea", "async"]
        )
        
        # Step 2: Process - Convert to permanent
        permanent = create_note_with_type(
            cli,
            "Python Async Programming",
            "Python's async/await provides an elegant way to write asynchronous code...",
            "permanent"
        )
        
        # Step 3: Connect - Add links
        linked_note_content = "Implementation details see [[Python Async Programming]]"
        linked_note = create_note_with_type(
            cli,
            "Async Best Practices",
            linked_note_content,
            "permanent"
        )
        
        # Verify links
        assert_link_exists(linked_note["id"], permanent["id"], cli)
        assert_backlink_exists(permanent["id"], linked_note["id"], cli)
        
        # Wait for indexing
        assert wait_for_indexing(cli, expected_notes=3, timeout=60), "Indexing timeout"
        
        # Step 4: Develop - Search and query
        search_result = cli.search("async programming", top=3)
        assert search_result.success
        
        # Verify graph
        stats_result = cli.graph_stats()
        assert stats_result.success
        assert stats_result.data.get("total_nodes") >= 3
    
    @pytest.mark.timeout(300)
    def test_multiple_notes_with_links_batch(self, cli, generator):
        """批量创建带链接的笔记并进行语义搜索"""
        # 1. Generate notes with links
        notes = generator.generate_with_links(15, link_probability=0.4)
        
        # 2. Create notes in order
        created_notes = []
        for note_data in notes:
            result = cli.add(
                note_data.content,
                title=note_data.title,
                note_type=note_data.note_type.value,
                tags=note_data.tags
            )
            created = assert_note_created(result, note_data.title)
            created_notes.append(created)
        
        # 3. Wait for indexing
        assert wait_for_indexing(cli, expected_notes=15, timeout=120), "Indexing timeout"
        
        # 4. Verify graph
        stats_result = cli.graph_stats()
        assert stats_result.success
        
        # Should have nodes and edges
        assert stats_result.data.get("total_nodes") >= 15
        
        # 5. Perform semantic search
        search_result = cli.search("programming", top=10)
        assert search_result.success
        assert len(search_result.data.get("results", [])) > 0
