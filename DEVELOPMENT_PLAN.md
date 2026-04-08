# ZK CLI 开发计划与验收标准

## 可进入开发阶段的 Issues

### Phase 1: 核心功能增强（立即开始）

#### 1. Issue #13 - Add `--kb` parameter to all note commands
**状态**: ✅ 需求明确，可立即开发  
**优先级**: **高** (阻塞 Agent 工作流)

**实现要点**:
- 修改 `cli.py` 中的以下命令，添加 `--kb` 参数：
  - `zk add`
  - `zk list`
  - `zk search`
  - `zk query`
  - `zk refs`
  - `zk daily`
  - `zk inbox`
  - `zk graph`
  - `zk delete`

**验收测试方案**:

```python
# tests/test_kb_parameter.py

class TestKBParameter:
    """测试 --kb 参数功能"""
    
    def test_add_with_kb(self, temp_kb):
        """测试添加笔记到指定知识库"""
        # 创建两个知识库
        kb1 = create_kb("work")
        kb2 = create_kb("personal")
        
        # 添加到 kb1
        result = run_cmd(f'zk add "test note" --kb work')
        assert result.success
        
        # 验证笔记在 kb1 中
        notes = list_notes(kb="work")
        assert len(notes) == 1
        
        # 验证笔记不在 kb2 中
        notes = list_notes(kb="personal")
        assert len(notes) == 0
    
    def test_search_with_kb(self, temp_kb):
        """测试在指定知识库中搜索"""
        # 在两个知识库添加相同内容的笔记
        run_cmd('zk add "python asyncio" --kb work')
        run_cmd('zk add "python asyncio" --kb personal')
        
        # 搜索 kb1
        result = run_cmd('zk search "python" --kb work --format json')
        assert result.json["total"] == 1
        assert "work" in result.json["results"][0]["kb"]
    
    def test_kb_not_exist(self):
        """测试指定不存在的知识库"""
        result = run_cmd('zk add "test" --kb nonexistent')
        assert not result.success
        assert "not found" in result.stderr.lower()
    
    def test_default_kb_when_not_specified(self, temp_kb):
        """测试不指定 --kb 时使用默认知识库"""
        # 设置默认知识库
        run_cmd('zk kb switch work')
        
        # 不指定 --kb
        run_cmd('zk add "test"')
        
        # 验证在 work 中
        notes = list_notes(kb="work")
        assert len(notes) == 1
```

---

#### 2. Issue #14 - Add `kb current` command
**状态**: ✅ 需求明确，可立即开发  
**优先级**: **高**

**实现要点**:
- 在 `kb` 命令中添加 `current` action
- 显示当前知识库的详细信息

**验收测试方案**:

```python
# tests/test_kb_current.py

class TestKBCurrent:
    """测试 kb current 命令"""
    
    def test_kb_current(self, temp_kb):
        """测试显示当前知识库"""
        run_cmd('zk kb switch work')
        
        result = run_cmd('zk kb current --format json')
        assert result.success
        
        data = result.json
        assert data["name"] == "work"
        assert "path" in data
        assert "total_notes" in data
        assert "by_type" in data
    
    def test_kb_current_table_format(self, temp_kb):
        """测试表格格式输出"""
        result = run_cmd('zk kb current')
        assert "work" in result.stdout
        assert "total notes" in result.stdout.lower()
    
    def test_kb_current_no_default(self):
        """测试没有默认知识库时的错误处理"""
        # 清除默认知识库配置
        result = run_cmd('zk kb current')
        # 应该显示错误或提示
```

---

#### 3. Issue #15 - Extend MCP Server
**状态**: ✅ 需求明确，可立即开发  
**优先级**: **高**

**实现要点**:
- 在 `mcp_server.py` 中添加新方法：
  - `kb_list`
  - `kb_switch`
  - `kb_current`
  - `get_backlinks`
  - `get_graph_stats`
  - `get_orphans`
  - `search_by_tag`
  - `daily_notes`

**验收测试方案**:

```python
# tests/test_mcp_server.py

class TestMCPServer:
    """测试 MCP Server 扩展功能"""
    
    def test_mcp_kb_list(self):
        """测试 kb_list 方法"""
        handler = ZKMCPHandler()
        
        response = handler.handle({
            "method": "kb_list",
            "params": {},
            "id": 1
        })
        
        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert isinstance(response["result"], list)
    
    def test_mcp_kb_switch(self, temp_kb):
        """测试 kb_switch 方法"""
        handler = ZKMCPHandler()
        
        response = handler.handle({
            "method": "kb_switch",
            "params": {"name": "work"},
            "id": 1
        })
        
        assert response["result"]["success"] is True
    
    def test_mcp_get_backlinks(self, temp_kb):
        """测试 get_backlinks 方法"""
        # 创建有链接关系的笔记
        note1 = create_note("Note 1", kb="work")
        note2 = create_note("Note 2 with [[Note 1]]", kb="work")
        
        handler = ZKMCPHandler()
        response = handler.handle({
            "method": "get_backlinks",
            "params": {"note_id": note1.id},
            "id": 1
        })
        
        assert len(response["result"]) == 1
        assert response["result"][0]["id"] == note2.id
    
    def test_mcp_error_handling(self):
        """测试错误处理"""
        handler = ZKMCPHandler()
        
        response = handler.handle({
            "method": "unknown_method",
            "params": {},
            "id": 1
        })
        
        assert "error" in response
        assert response["error"]["code"] == -32601
```

---

### Phase 2: 搜索增强（优先开发）

#### 4. Issue #16 - Add suggest-links command
**状态**: ✅ 需求明确，可开发  
**优先级**: 中

**实现要点**:
- 创建 `zk/suggester.py` 模块
- 基于语义相似度推荐相关笔记
- CLI 命令: `zk suggest-links "内容"`

**验收测试方案**:

```python
# tests/test_suggest_links.py

class TestSuggestLinks:
    """测试链接建议功能"""
    
    def test_suggest_links_basic(self, temp_kb):
        """测试基本的链接建议"""
        # 创建相关笔记
        note1 = create_note("Python async programming guide", kb="work")
        note2 = create_note("Asyncio tutorial for beginners", kb="work")
        
        # 为新内容请求建议
        result = run_cmd('zk suggest-links "Learn about Python async" --format json')
        
        assert result.success
        suggestions = result.json
        
        # 应该推荐 note1 和 note2
        assert len(suggestions) >= 2
        assert any(note1.id in s["id"] for s in suggestions)
    
    def test_suggest_links_threshold(self, temp_kb):
        """测试相似度阈值"""
        # 创建不相关的笔记
        note1 = create_note("Python async", kb="work")
        note2 = create_note("Cooking recipes", kb="work")
        
        result = run_cmd('zk suggest-links "Python async" --threshold 0.7 --format json')
        suggestions = result.json
        
        # 不应该推荐 cooking 笔记
        assert not any("cooking" in s["title"].lower() for s in suggestions)
    
    def test_suggest_links_top_k(self, temp_kb):
        """测试限制返回数量"""
        # 创建多个笔记
        for i in range(10):
            create_note(f"Python topic {i}", kb="work")
        
        result = run_cmd('zk suggest-links "Python" --top 3 --format json')
        suggestions = result.json
        
        assert len(suggestions) <= 3
```

---

#### 5. Issue #17 - Hybrid Search (BM25 + Semantic)
**状态**: ✅ 需求明确，但实现较复杂  
**优先级**: 中

**实现要点**:
- 创建 `zk/bm25_index.py` 模块
- 实现 RRF (Reciprocal Rank Fusion) 融合算法
- CLI: `zk search "query" --mode hybrid`

**验收测试方案**:

```python
# tests/test_hybrid_search.py

class TestHybridSearch:
    """测试混合搜索功能"""
    
    def test_bm25_index_building(self, temp_kb):
        """测试 BM25 索引构建"""
        from zk.bm25_index import BM25Index
        
        # 添加笔记
        create_note("Python asyncio tutorial", kb="work")
        create_note("JavaScript async await", kb="work")
        
        # 构建索引
        bm25 = BM25Index(kb="work")
        bm25.build()
        
        # 验证索引存在
        assert bm25.index_exists()
    
    def test_hybrid_search_results(self, temp_kb):
        """测试混合搜索结果质量"""
        # 创建测试数据
        create_note("Python async programming deep dive", kb="work")
        create_note("Asyncio best practices", kb="work")
        create_note("Python requests library", kb="work")
        
        # 纯语义搜索
        semantic_results = search("async python", mode="semantic")
        
        # 纯 BM25 搜索
        bm25_results = search("async python", mode="keyword")
        
        # 混合搜索
        hybrid_results = search("async python", mode="hybrid")
        
        # 混合搜索应该比单一方法更好
        # 验证：前3个结果中包含相关笔记
        top_ids = [r["id"] for r in hybrid_results[:3]]
        assert any("async" in r["title"].lower() for r in hybrid_results[:3])
    
    def test_search_mode_parameter(self, temp_kb):
        """测试 --mode 参数"""
        result1 = run_cmd('zk search "test" --mode semantic --format json')
        result2 = run_cmd('zk search "test" --mode keyword --format json')
        result3 = run_cmd('zk search "test" --mode hybrid --format json')
        
        # 三种模式都应该返回结果
        assert result1.success
        assert result2.success
        assert result3.success
    
    def test_rrf_fusion(self):
        """测试 RRF 融合算法"""
        from zk.search_engine import rrf_fusion
        
        list1 = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
        list2 = [{"id": "b", "score": 0.95}, {"id": "c", "score": 0.7}]
        
        fused = rrf_fusion(list1, list2, k=60)
        
        # 验证融合结果
        assert len(fused) == 3
        # b 在两个列表中都出现，应该排名更高
        assert fused[0]["id"] == "b"
```

---

#### 6. Issue #18 - Multi-format Output
**状态**: ✅ 需求明确，可立即开发  
**优先级**: 中

**实现要点**:
- 创建 `zk/formatters.py` 模块
- 支持 json, csv, yaml, paths, table, tree 格式

**验收测试方案**:

```python
# tests/test_formatters.py

class TestFormatters:
    """测试多格式输出"""
    
    def test_csv_format(self, temp_kb):
        """测试 CSV 格式"""
        create_note("Note 1", tags=["python"], kb="work")
        create_note("Note 2", tags=["js"], kb="work")
        
        result = run_cmd('zk list --format csv')
        
        # 验证 CSV 格式
        lines = result.stdout.strip().split('\n')
        assert len(lines) >= 2  # 标题行 + 数据行
        assert 'id,title,type,tags' in lines[0].lower()
    
    def test_yaml_format(self, temp_kb):
        """测试 YAML 格式"""
        create_note("Test Note", kb="work")
        
        result = run_cmd('zk list --format yaml')
        
        # 验证是有效的 YAML
        import yaml
        data = yaml.safe_load(result.stdout)
        assert isinstance(data, list)
        assert len(data) >= 1
    
    def test_paths_format(self, temp_kb):
        """测试 paths 格式（便于管道）"""
        note = create_note("Test", kb="work")
        
        result = run_cmd('zk list --format paths')
        
        # 每行应该是一个路径
        paths = result.stdout.strip().split('\n')
        assert len(paths) >= 1
        assert paths[0].endswith('.md')
    
    def test_pipe_usage(self, temp_kb):
        """测试管道使用场景"""
        create_note("TODO: fix bug", kb="work")
        create_note("TODO: write doc", kb="work")
        
        # 搜索 TODO 并获取路径
        result = run_cmd('zk search "TODO" --format paths')
        paths = result.stdout.strip()
        
        # 可以使用 xargs 处理
        assert paths  # 确保有输出
```

---

## 需要进一步设计的 Issues

### 设计类 Issue（需讨论后开发）

| Issue | 标题 | 状态 | 下一步 |
|-------|------|------|--------|
| #12 | Voice-to-Knowledge Workflow | 需细化 | 确定 Agent 与 CLI 的交互协议 |
| #23 | Link Discovery Strategy | 需细化 | 确定自动 vs 手动策略 |
| #24 | Knowledge Integration Workflow | 需细化 | 设计 `review`/`process` 命令细节 |

### 复杂功能（后续阶段）

| Issue | 标题 | 优先级 | 复杂度 |
|-------|------|--------|--------|
| #19 | TUI Mode | 低 | 高 (需要 textual) |
| #20 | HTTP API Server | 低 | 高 (需要 FastAPI) |
| #21 | Template System | 低 | 中 (需要 Jinja2) |
| #22 | OCR & PDF | 低 | 高 (需要 tesseract) |

---

## 推荐的开发顺序

### Sprint 1 (1-2 天)
1. **Issue #14** - `kb current` (最简单，热身)
2. **Issue #13** - `--kb` parameter (核心功能)

### Sprint 2 (2-3 天)
3. **Issue #15** - MCP Server 扩展 (Agent 必需)

### Sprint 3 (3-5 天)
4. **Issue #18** - Multi-format output (工具集成)
5. **Issue #16** - suggest-links (知识发现)

### Sprint 4 (5-7 天)
6. **Issue #17** - Hybrid Search (性能优化)

---

## 测试基础设施

### 已有测试工具
- `tests/utils/temp_kb.py` - 临时知识库管理
- `tests/utils/jfox_cli.py` - CLI 命令封装
- `tests/conftest.py` - pytest fixtures

### 需要添加
- `tests/utils/format_checker.py` - 格式验证
- `tests/utils/mcp_client.py` - MCP 测试客户端
- `tests/benchmarks/` - 性能测试

---

*创建日期: 2026-03-22*
