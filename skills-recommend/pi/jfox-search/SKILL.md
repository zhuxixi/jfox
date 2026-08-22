---
name: jfox-search
description: |
  Search and retrieve notes from a Zettelkasten knowledge base.
  Use when user wants to search notes, find information, look up knowledge,
  query the knowledge graph, find related notes, discover backlinks, or get link suggestions.
  Triggers on: "搜索", "查找", "找一下", "查一下", "搜一下", "帮我找",
  "有没有关于", "search notes", "look up", "find", "find related notes",
  "search knowledge base", "notes about", "query knowledge graph",
  "backlinks", "suggest links".
---

# JFox Knowledge Base Search

Search and retrieve notes from the Zettelkasten knowledge base.

## Prerequisites

Knowledge base must be initialized (`jfox init`). If search index is stale, run `jfox index rebuild` first.

## Search Strategy Selection

Match search approach to user intent:

| User Intent | Strategy | Command |
|-------------|----------|---------|
| Exact keyword | Keyword (BM25) | `jfox search "<keyword>" --mode keyword --json` |
| Concept or idea (fuzzy) | Hybrid (BM25 + semantic) | `jfox search "<concept>" --mode hybrid --json` |
| Pure semantic similarity | Semantic | `jfox search "<idea>" --mode semantic --json` |
| Explore related topics | Graph traversal | `jfox query "<topic>" --depth 2 --json` |
| What links to note X | Backlinks | `jfox refs --search "<title>" --json` |
| What should I link to | Link suggestions | `jfox suggest-links "<content>" --json` |

**Default strategy**: `--mode hybrid` (best balance of precision and recall).

## Workflow

### Single Search

```bash
jfox search "<query>" --mode hybrid --top 10 --json
```

Parse JSON output and present as:

```
找到 N 条相关笔记：

1. [标题] (score: 0.85)
   类型: permanent | 标签: tag1, tag2
   摘要: 前100字...

2. [标题] (score: 0.72)
   ...
```

提示：使用 `jfox show <note_id>` 查看笔记完整内容。

### Graph-Aware Search

For exploring connections around a topic:

```bash
jfox query "<topic>" --top 10 --depth 2 --json
```

Returns both search results AND their graph neighbors for broader knowledge landscape view.

### Backlink Discovery

Find what references a specific note:

```bash
jfox refs --search "<title>" --json
```

### Link Recommendations

Find notes that should be linked from given content:

```bash
jfox suggest-links "<content>" --top 10 --threshold 0.6 --json
```

Default threshold: `0.6`. Lower to `0.3-0.5` for broader suggestions; raise to `0.7-0.8` for stricter matching.

## Full Command Reference

```bash
# Basic search
jfox search "<query>" --mode <hybrid|keyword|semantic> --top <N> --json

# Filter by note type
jfox search "<query>" --type permanent --json

# Graph query with traversal
jfox query "<query>" --top <N> --depth <D> --json

# Link suggestions
jfox suggest-links "<content>" --top <N> --threshold <T> --json

# Backlinks / references
jfox refs --search "<title>" --json
jfox refs --note "<note-id>" --json
```

## Multi-KB Search

All search commands support `--kb <name>` to target a specific KB:

```bash
jfox search "<query>" --kb work --json
```

## Error Handling

- **"Index not found"**: Run `jfox index rebuild`
- **Empty results**: Try broader query, switch to `hybrid` mode, or lower `--threshold`
- **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. Use `jfox daemon start` to avoid repeated loading.
