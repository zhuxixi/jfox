## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

当前 ZK CLI 使用**纯语义搜索** (ChromaDB + sentence-transformers)，擅长概念匹配，但在以下场景表现不佳：
- 精确关键词搜索（如搜索特定函数名、变量名）
- 短查询（1-2 个词）
- 拼写错误的容错

Omnisearch 使用的 **BM25 算法**在精确关键词匹配上表现更好，且计算成本低。

## 目标

实现**混合搜索**：结合语义搜索 (向量) 和关键词搜索 (BM25)，取长补短。

## 技术方案

### 方案 A: 并行搜索 + RRF 融合 (推荐)

```python
class HybridSearchEngine:
    def __init__(self):
        self.vector_store = ChromaDBVectorStore()  # 现有
        self.bm25_index = BM25Index()  # 新增
    
    def search(self, query: str, top_k: int = 5):
        # 1. 并行执行两种搜索
        semantic_results = self.vector_store.search(query, top_k=top_k)
        bm25_results = self.bm25_index.search(query, top_k=top_k)
        
        # 2. RRF (Reciprocal Rank Fusion) 融合
        return self._rrf_fuse(semantic_results, bm25_results, k=60)
```

**RRF 公式：**
```
score = Σ 1 / (k + rank)
其中 k=60 (常数)
```

### 方案 B: 级联搜索

先 BM25 过滤，再语义排序：
```python
def search(self, query: str, top_k: int = 5):
    # 1. BM25 快速召回 50 个候选
    candidates = self.bm25_index.search(query, top_k=50)
    
    # 2. 语义重排序
    return self.vector_store.rerank(query, candidates, top_k=top_k)
```

## 实现步骤

1. **添加 BM25 索引模块** `zk/bm25_index.py`
   - 使用 `rank-bm25` 库
   - 从现有笔记构建索引
   - 增量更新（笔记增删时）

2. **修改搜索逻辑** `zk/vector_store.py` 或新建 `zk/search_engine.py`
   - 实现混合搜索类
   - 支持 RRF 融合

3. **CLI 接口**
   ```bash
   # 默认使用混合搜索
   zk search "query"
   
   # 指定搜索模式
   zk search "query" --mode semantic    # 纯语义
   zk search "query" --mode keyword     # 纯关键词 (BM25)
   zk search "query" --mode hybrid      # 混合 (默认)
   ```

## 新增依赖

```txt
rank-bm25>=0.2.2
```

## 性能考虑

- BM25 索引完全在内存中，搜索速度 <10ms
- 需要定期重建索引或实现增量更新
- 内存占用：约笔记内容的 10-20%

## 验收标准

- [ ] BM25 索引模块实现
- [ ] 混合搜索支持 RRF 融合
- [ ] CLI 支持 `--mode` 参数选择搜索模式
- [ ] 搜索质量测试：混合搜索优于单一方法
- [ ] 性能测试：混合搜索延迟 <200ms

## 优先级

**高** - 显著提升搜索体验

## 依赖

- Issue #9 (Obsidian CLI 调研)
