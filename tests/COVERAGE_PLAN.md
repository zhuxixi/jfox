# 测试覆盖率提升计划：26% → 50%

> 目标：用最少的时间，获得最大的覆盖收益

---

## 📊 当前状况

| 指标 | 数值 |
|------|------|
| 总代码行数 | ~5,850 行 |
| 当前覆盖 | 771 行 (26.67%) |
| 目标覆盖 | ~2,925 行 (50%) |
| **需要新增** | **~2,150 行** |

---

## 🎯 高效策略：先易后难，抓大放小

### 不测试的模块（投入产出比低）

| 模块 | 原因 |
|------|------|
| `cli.py` (~1000行) | UI层，依赖 Rich/Typer，难 mock |
| `embedding_backend.py` | 需要真实模型，已有集成测试覆盖 |
| `vector_store.py` | 依赖 ChromaDB，已有集成测试覆盖 |
| `__main__.py` | 入口文件，只有几行 |

### 优先测试的模块（高收益）

#### Phase 1: 纯逻辑模块（预计 +15% 覆盖，2小时）

| 模块 | 代码量 | 测试难度 | 预估收益 | 关键测试点 |
|------|--------|----------|----------|-----------|
| `formatters.py` | ~200行 | ⭐ 极易 | +3% | JSON/CSV/YAML/Table 转换 |
| `bm25_index.py` | ~250行 | ⭐ 极易 | +4% | 分词、索引、搜索 |
| `models.py` | ~300行 | ⭐⭐ 容易 | +5% | Note 序列化/反序列化 |
| `global_config.py` | ~200行 | ⭐⭐ 容易 | +3% | 配置读写、知识库管理 |

#### Phase 2: 核心算法模块（预计 +10% 覆盖，3小时）

| 模块 | 代码量 | 测试难度 | 预估收益 | 关键测试点 |
|------|--------|----------|----------|-----------|
| `graph.py` | ~350行 | ⭐⭐⭐ 中等 | +6% | 图谱构建、邻居查询、统计 |
| `kb_manager.py` | ~300行 | ⭐⭐⭐ 中等 | +4% | KB 创建/删除/切换 |

#### Phase 3: 业务逻辑模块（预计 +5% 覆盖，2小时）

| 模块 | 代码量 | 测试难度 | 预估收益 | 关键测试点 |
|------|--------|----------|----------|-----------|
| `template.py` | ~250行 | ⭐⭐ 容易 | +3% | 模板渲染、变量替换 |
| `indexer.py` | ~250行 | ⭐⭐⭐ 中等 | +2% | 文件监控、增量索引 |

---

## 📋 详细实施计划

### Week 1: Phase 1 - 纯逻辑模块

#### Day 1: formatters.py + models.py（1小时）
```python
# test_formatters_unit.py
class TestOutputFormatter:
    """测试 formatters.py 的核心函数"""
    
    def test_to_json_basic(self):
        """JSON 格式化基础测试"""
        data = [{"id": "1", "title": "测试"}]
        result = OutputFormatter.to_json(data)
        assert "测试" in result
        assert json.loads(result)  # 验证是合法 JSON
    
    def test_to_csv_basic(self):
        """CSV 格式化基础测试"""
        data = [{"id": "1", "title": "测试"}]
        result = OutputFormatter.to_csv(data)
        lines = result.strip().split('\n')
        assert len(lines) == 2  # header + data
        assert '测试' in lines[1]
    
    def test_to_yaml_basic(self):
        """YAML 格式化基础测试"""
        data = [{"id": "1", "title": "测试"}]
        result = OutputFormatter.to_yaml(data)
        assert "测试" in result
    
    def test_format_table_with_nested(self):
        """Table 格式处理嵌套数据"""
        data = [{"id": "1", "meta": {"count": 5}}]
        result = OutputFormatter.to_table(data)
        assert "1" in result
```

```python
# test_models_unit.py  
class TestNoteModel:
    """测试 models.py 的 Note 类"""
    
    def test_note_creation(self):
        """Note 对象创建"""
        note = Note(id="123", title="测试", content="内容")
        assert note.id == "123"
        assert note.title == "测试"
    
    def test_note_to_markdown(self):
        """Note 转 Markdown"""
        note = Note(id="123", title="测试", content="内容", tags=["a", "b"])
        md = note.to_markdown()
        assert "---" in md  # frontmatter
        assert "测试" in md
        assert "a" in md and "b" in md
    
    def test_note_from_markdown(self):
        """Markdown 转 Note"""
        md = """---
id: '123'
title: 测试
---
# 测试

内容"""
        note = Note.from_markdown(md)
        assert note.id == "123"
        assert note.title == "测试"
```

#### Day 2: bm25_index.py（1小时）
```python
# test_bm25_unit.py
class TestBM25Index:
    """测试 BM25 索引"""
    
    def test_tokenize_chinese(self):
        """中文分词"""
        index = BM25Index()
        tokens = index._tokenize("今天学习了 Python")
        assert "今天" in tokens or "学" in tokens
        assert "python" in [t.lower() for t in tokens]
    
    def test_tokenize_english(self):
        """英文分词"""
        index = BM25Index()
        tokens = index._tokenize("Hello World")
        assert "hello" in [t.lower() for t in tokens]
        assert "world" in [t.lower() for t in tokens]
    
    def test_add_document(self):
        """添加文档"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("doc1", "Python programming guide")
            assert len(index.documents) == 1
    
    def test_search_basic(self):
        """基础搜索"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("doc1", "Python programming guide")
            index.add_document("doc2", "JavaScript web development")
            
            results = index.search("python", top_k=5)
            assert len(results) > 0
            assert results[0]["id"] == "doc1"  # Python 文档应该排第一
    
    def test_save_and_load(self):
        """索引保存和加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 保存
            index1 = BM25Index(index_dir=Path(tmpdir))
            index1.add_document("doc1", "Python guide")
            index1.save()
            
            # 加载
            index2 = BM25Index(index_dir=Path(tmpdir))
            index2.load()
            assert len(index2.documents) == 1
```

#### Day 3-4: global_config.py（补全）（1小时）
```python
# test_global_config_unit.py
class TestGlobalConfigManager:
    """测试全局配置管理"""
    
    def test_kb_exists(self, temp_config_dir):
        """知识库存在检查"""
        manager = GlobalConfigManager(config_dir=temp_config_dir)
        manager.create_kb("test_kb", Path("/tmp/test"))
        assert manager.kb_exists("test_kb")
        assert not manager.kb_exists("nonexistent")
    
    def test_get_kb_path(self, temp_config_dir):
        """获取知识库路径"""
        manager = GlobalConfigManager(config_dir=temp_config_dir)
        manager.create_kb("test_kb", Path("/tmp/test"))
        path = manager.get_kb_path("test_kb")
        assert path == Path("/tmp/test")
    
    def test_switch_kb(self, temp_config_dir):
        """切换知识库"""
        manager = GlobalConfigManager(config_dir=temp_config_dir)
        manager.create_kb("kb1", Path("/tmp/kb1"))
        manager.create_kb("kb2", Path("/tmp/kb2"))
        
        manager.switch_kb("kb2")
        assert manager.get_current_kb() == "kb2"
```

### Week 2: Phase 2 - 核心算法

#### Day 1-2: graph.py（2小时）
```python
# test_graph_unit.py
class TestKnowledgeGraph:
    """测试知识图谱"""
    
    def test_graph_build(self, temp_kb):
        """图谱构建"""
        config = ZKConfig(base_dir=temp_kb)
        graph = KnowledgeGraph(config)
        
        # 创建测试笔记
        note1 = create_note("Note 1", "Content 1")
        note2 = create_note("Note 2", "Content 2", links=[note1.id])
        
        graph.build()
        assert len(graph.graph.nodes) == 2
        assert len(graph.graph.edges) == 1
    
    def test_get_neighbors(self, temp_kb):
        """获取邻居节点"""
        config = ZKConfig(base_dir=temp_kb)
        graph = KnowledgeGraph(config).build()
        
        neighbors = graph.get_neighbors(note1.id)
        assert note2.id in neighbors
    
    def test_get_stats(self, temp_kb):
        """图谱统计"""
        config = ZKConfig(base_dir=temp_kb)
        graph = KnowledgeGraph(config).build()
        
        stats = graph.get_stats()
        assert stats.total_nodes == 2
        assert stats.total_edges == 1
        assert stats.avg_degree > 0
    
    def test_find_orphans(self, temp_kb):
        """查找孤立节点"""
        config = ZKConfig(base_dir=temp_kb)
        # 创建孤立笔记
        create_note("Orphan", "No links")
        
        graph = KnowledgeGraph(config).build()
        orphans = graph.find_orphans()
        assert len(orphans) == 1
```

#### Day 3-4: kb_manager.py（2小时）
```python
# test_kb_manager_unit.py
class TestKnowledgeBaseManager:
    """测试知识库管理器"""
    
    def test_create_kb(self, temp_dir):
        """创建知识库"""
        manager = KnowledgeBaseManager(base_dir=temp_dir)
        kb_path = manager.create_kb("test", "Test KB")
        
        assert kb_path.exists()
        assert (kb_path / "notes" / "fleeting").exists()
        assert (kb_path / "notes" / "permanent").exists()
    
    def test_list_kb(self, temp_dir):
        """列出知识库"""
        manager = KnowledgeBaseManager(base_dir=temp_dir)
        manager.create_kb("kb1", "KB 1")
        manager.create_kb("kb2", "KB 2")
        
        kbs = manager.list_kb()
        assert len(kbs) == 2
    
    def test_remove_kb(self, temp_dir):
        """删除知识库"""
        manager = KnowledgeBaseManager(base_dir=temp_dir)
        kb_path = manager.create_kb("test", "Test")
        
        manager.remove_kb("test", force=True)
        assert not kb_path.exists()
```

### Week 3: Phase 3 - 业务逻辑

#### Day 1-2: template.py（1.5小时）
```python
# test_template_unit.py
class TestTemplateManager:
    """测试模板管理"""
    
    def test_render_meeting_template(self, temp_dir):
        """渲染会议模板"""
        manager = TemplateManager(templates_dir=temp_dir)
        variables = {
            "title": "周会",
            "date": "2026-03-28",
            "participants": "张三, 李四"
        }
        
        result = manager.render("meeting", variables)
        assert "周会" in result
        assert "2026-03-28" in result
        assert "张三" in result
    
    def test_render_literature_template(self, temp_dir):
        """渲染文献模板"""
        manager = TemplateManager(templates_dir=temp_dir)
        variables = {
            "title": "某本书",
            "author": "某作者",
            "source": "出版社"
        }
        
        result = manager.render("literature", variables)
        assert "某本书" in result
        assert "某作者" in result
    
    def test_available_templates(self, temp_dir):
        """获取可用模板列表"""
        manager = TemplateManager(templates_dir=temp_dir)
        templates = manager.available_templates()
        assert "meeting" in templates
        assert "literature" in templates
```

#### Day 3-4: indexer.py（1.5小时）
```python
# test_indexer_unit.py
class TestIndexer:
    """测试索引器"""
    
    def test_index_note(self, temp_kb):
        """索引单条笔记"""
        config = ZKConfig(base_dir=temp_kb)
        indexer = Indexer(config)
        
        note = create_note("Test", "Content")
        indexer.index_note(note)
        
        stats = indexer.get_stats()
        assert stats.total_indexed == 1
    
    def test_index_rebuild(self, temp_kb):
        """重建索引"""
        config = ZKConfig(base_dir=temp_kb)
        indexer = Indexer(config)
        
        # 创建多条笔记
        for i in range(5):
            note = create_note(f"Note {i}", f"Content {i}")
            save_note(note)
        
        indexer.rebuild()
        stats = indexer.get_stats()
        assert stats.total_indexed == 5
```

---

## 🛠️ 基础设施

### 1. 创建测试 Fixtures

```python
# conftest.py 新增

@pytest.fixture
def temp_config_dir():
    """临时配置目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_zk_config(temp_dir):
    """Mock ZKConfig"""
    return ZKConfig(base_dir=temp_dir)

def create_note(title, content, **kwargs):
    """快速创建测试笔记"""
    return Note(
        id=generate_note_id(),
        title=title,
        content=content,
        created=datetime.now(),
        updated=datetime.now(),
        **kwargs
    )
```

### 2. 运行测试命令

```bash
# 只跑单元测试（快速）
pytest tests/test_*_unit.py -v --cov=zk --cov-report=term-missing

# 跑所有测试（完整）
pytest tests/ -v --cov=zk --cov-report=html
```

---

## 📈 预期时间线

| 阶段 | 时间 | 新增覆盖 | 累计覆盖 |
|------|------|----------|----------|
| 当前 | - | - | 26.67% |
| Phase 1 (Week 1) | 3-4 小时 | +15% | ~42% |
| Phase 2 (Week 2) | 4 小时 | +10% | ~52% |
| Phase 3 (Week 3) | 3 小时 | +5% | ~57% |
| **总计** | **10-11 小时** | **+30%** | **~57%** |

---

## ✅ 验收标准

```bash
$ pytest tests/ -v --cov=zk --cov-report=term-missing

Name                     Stmts   Miss  Cover
--------------------------------------------
zk/__init__.py               0      0   100%
zk/bm25_index.py           200     20    90%
zk/config.py               150     30    80%
zk/formatters.py           180     10    94%
zk/global_config.py        180     40    78%
zk/graph.py                300     60    80%
zk/kb_manager.py           250     50    80%
zk/models.py               280     30    89%
zk/template.py             200     40    80%
...
--------------------------------------------
TOTAL                     5850   2900    50%
```

---

## 💡 执行建议

1. **分批次提交**：每完成一个模块就提交，避免一次性改动过大
2. **先用测试生成器**：用 ChatGPT/Copilot 生成测试模板，再人工调整
3. **不要追求完美**：80% 覆盖率的模块比 100% 覆盖率的模块更值得投入时间
4. **善用 parametrized**：一个测试函数覆盖多种输入情况

---

需要我开始帮你实施 Phase 1 吗？还是你想先看看某个具体模块的测试示例？
