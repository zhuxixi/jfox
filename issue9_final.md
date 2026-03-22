# Obsidian CLI & Omnisearch 调研报告

> 对比当前 ZK CLI 实现，提出优化建议

---

## 1. Obsidian CLI 架构分析

### 核心设计
Obsidian CLI (v1.12.4) 采用 **"遥控器"模式**：
- CLI 作为客户端，与运行中的 Obsidian 应用通信
- 所有操作在 Obsidian 的完整上下文环境中执行
- 支持插件、主题、同步等全部功能

### 命令体系 (100+ 命令)

| 类别 | 代表命令 | 说明 |
|------|---------|------|
| **文件操作** | `files`, `read`, `create`, `append`, `move`, `delete` | 笔记 CRUD |
| **搜索** | `search`, `search:context` | 全文搜索 |
| **属性** | `properties`, `property:set` | Frontmatter 操作 |
| **标签** | `tags`, `tag:rename` | 标签管理 |
| **链接** | `links`, `backlinks`, `orphans` | 链接结构分析 |
| **每日笔记** | `daily`, `daily:append` | Daily notes |
| **任务** | `tasks`, `task:toggle` | 任务管理 |
| **模板** | `templates`, `template:apply` | 模板应用 |
| **插件** | `plugins`, `plugin:install` | 插件管理 |

### 特色功能

#### TUI 模式
```bash
$ obsidian  # 无参数启动 TUI

# 快捷键：
# ↑↓ - 选择文件
# /  - 搜索
# Enter - 打开文件
# n - 新建文件
# q - 退出
```

#### 多格式输出
```bash
obsidian search query="TODO" format=json   # JSON
obsidian search query="TODO" format=csv    # CSV
obsidian search query="TODO" format=paths  # 仅路径
obsidian files list format=tree            # 树形结构
```

#### Vault 切换
```bash
obsidian vault="Work" search query="meeting"
obsidian vault="Personal" daily
```

---

## 2. Omnisearch 技术分析

### 核心架构

```
Omnisearch (Obsidian Plugin)
├── MiniSearch - 内存中的倒排索引
├── BM25 - 文档评分算法
├── Text Extractor - OCR + PDF 文本提取
└── HTTP Server - 外部查询接口
```

### BM25 算法

```python
# BM25 评分公式
score(D, Q) = Σ IDF(q_i) * (f(q_i) * (k1 + 1)) / (f(q_i) + k1 * (1 - b + b * |D|/avgDL))

# 参数：
# - k1=1.2, b=0.75 (默认)
# - f(q_i): 词项在文档中的频率
# - |D|: 文档长度
# - avgDL: 平均文档长度
```

**优势：**
- 比 TF-IDF 更好的长度归一化
- 对长文档更公平
- 计算简单，纯 CPU 运行

### MiniSearch 特点

```javascript
const miniSearch = new MiniSearch({
  fields: ['title', 'content', 'headings'],
  storeFields: ['title', 'path'],
  searchOptions: {
    boost: { title: 2, headings: 1.5 },
    fuzzy: 0.2  // 模糊匹配
  }
})
```

- 内存索引，无外部依赖
- 支持字段加权
- 支持模糊匹配和拼写纠错
- 支持前缀搜索

---

## 3. 当前 ZK CLI vs Obsidian CLI/Omnisearch

### 功能对比矩阵

| 功能 | ZK CLI (当前) | Obsidian CLI | Omnisearch | 差距分析 |
|------|--------------|--------------|------------|---------|
| **搜索算法** | 语义搜索 (向量) | 原生搜索 | BM25 + 模糊 | ✅ 各有优势，可考虑混合 |
| **索引方式** | ChromaDB (持久化) | 内存索引 | MiniSearch (内存) | ✅ ChromaDB 更适合大规模 |
| **文件监控** | ✅ Watchdog | ✅ 内置 | ❌ 无 | 平手 |
| **图谱分析** | ✅ NetworkX | ⚠️ 基础 | ❌ 无 | ZK 领先 |
| **TUI 模式** | ❌ 无 | ✅ 完整 | ❌ 无 | 可考虑添加 |
| **多格式输出** | ❌ 仅 JSON/Text | ✅ 8+ 格式 | ❌ JSON | 可扩展 |
| **HTTP API** | ⚠️ MCP only | ❌ 无 | ✅ 可选 | 可考虑 HTTP |
| **OCR/PDF** | ❌ 无 | ⚠️ 插件 | ✅ Text Extractor | 低优先级 |
| **模板系统** | ❌ 无 | ✅ 完整 | ❌ 无 | 可考虑添加 |
| **Vault 切换** | ✅ `kb switch` | ✅ vault= | ❌ 单 vault | 平手 |

---

## 4. 优化建议 (已拆分子 Issue)

| 优先级 | 优化项 | 子 Issue | 说明 |
|--------|--------|----------|------|
| **高** | BM25 混合搜索 | #17 | 补充语义搜索，精确关键词匹配 |
| **高** | 多格式输出 | #18 | csv, yaml, paths 格式 |
| **中** | TUI 模式 | #19 | 交互式界面 (textual) |
| **中** | HTTP API | #20 | 外部工具访问 (FastAPI) |
| **中** | 模板系统 | #21 | 快速创建标准化笔记 |
| **低** | OCR/PDF | #22 | 非文本内容索引 |

---

## 5. 建议的 Roadmap

```
Phase 1 (近期)
├── Issue #17: BM25 混合搜索
├── Issue #18: 多格式输出
└── Issue #13/14/15/16 (Voice-to-Knowledge 相关)

Phase 2 (中期)
├── Issue #19: TUI 模式
├── Issue #20: HTTP API
└── Issue #21: 模板系统

Phase 3 (远期)
└── Issue #22: OCR/PDF 支持
```

---

## 6. 当前 ZK CLI 的优势

- ✅ **语义搜索** - ChromaDB 持久化，适合大规模
- ✅ **知识图谱** - NetworkX 领先于其他方案
- ✅ **多知识库** - 独立 vault 管理
- ✅ **文件监控** - Watchdog 实时同步

---

## 7. 参考资料

- [Obsidian CLI 官方文档](https://help.obsidian.md/Obsidian+CLI)
- [Omnisearch GitHub](https://github.com/scambier/obsidian-omnisearch)
- [MiniSearch 文档](https://lucaong.github.io/minisearch/)
- [BM25 算法详解](https://towardsai.net/p/artificial-intelligence/enhance-your-llm-agents-with-bm25-lightweight-retrieval-that-works)

---

## 子 Issue 追踪

- #17 - [Feature] Hybrid Search: BM25 + Semantic Search
- #18 - [Feature] Multi-format Output Support
- #19 - [Feature] TUI Mode
- #20 - [Feature] HTTP API Server
- #21 - [Feature] Template System
- #22 - [Feature] OCR & PDF Text Extraction

---

*调研日期: 2026-03-22*
*关联: Issue #9*
