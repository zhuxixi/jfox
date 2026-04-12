---
name: jfox-search
description: Use when user wants to search notes, find information, look up knowledge in their Zettelkasten. Triggers on "搜索", "查找", "找一下", "查一下", "搜一下", "帮我找", "有没有关于", "search notes", "look up", "find", "find related notes", "search knowledge base", "notes about".
---

# JFox Knowledge Base Search

Search and retrieve notes from the Zettelkasten knowledge base.

## Prerequisites

Knowledge base must be initialized (`jfox init`). If search index is stale, run `jfox index rebuild` first.

## Search Strategy Selection

Choose the right search approach based on user intent:

| User Intent | Strategy | Command |
|-------------|----------|---------|
| Exact keyword or term | Keyword (BM25) | `jfox search "<keyword>" --mode keyword --format json` |
| Concept or idea (fuzzy) | Hybrid (BM25+semantic) | `jfox search "<concept>" --mode hybrid --format json` |
| Pure semantic similarity | Semantic | `jfox search "<idea>" --mode semantic --format json` |
| Explore related topics | Graph traversal | `jfox query "<topic>" --depth 2 --json` |
| What links to note X | Backlinks | `jfox refs --search "<title>" --format json` |
| What should I link to | Link suggestions | `jfox suggest-links "<content>" --format json` |

**Default strategy**: `--mode hybrid` (best balance of precision and recall).

## Workflow

### Single Search

```bash
jfox search "<query>" --mode hybrid --top 10 --format json
```

Parse the JSON output and present results as:

```
找到 N 条相关笔记：

1. [标题] (score: 0.85)
   类型: permanent | 标签: tag1, tag2
   摘要: 前100字...

2. [标题] (score: 0.72)
   ...
```

### Graph-Aware Search

For exploring connections around a topic:
```bash
jfox query "<topic>" --top 10 --depth 2 --json
```

This returns both search results AND their graph neighbors, giving a broader view of the knowledge landscape.

### Backlink Discovery

To find what references a specific note:
```bash
jfox refs --search "<title>" --format json
```

### Link Recommendations

To find notes that should be linked from given content:
```bash
jfox suggest-links "<content>" --top 10 --threshold 0.6 --format json
```

Default threshold is `0.6`. Lower to `0.3-0.5` for broader suggestions, raise to `0.7-0.8` for stricter matching.

## All Search Commands Reference

```bash
# Basic search
jfox search "<query>" --mode <hybrid|keyword|semantic> --top <N> --format json

# Filter by note type (fleeting|permanent)
jfox search "<query>" --type permanent --format json

# Graph query with traversal
jfox query "<query>" --top <N> --depth <D> --json

# Link suggestions
jfox suggest-links "<content>" --top <N> --threshold <T> --format json

# Backlinks/references
jfox refs --search "<title>" --format json
jfox refs --note "<note-id>" --format json
```

## Multi-KB Search

All search commands support `--kb <name>` to target a specific knowledge base:
```bash
jfox search "<query>" --kb work --format json
```

## Error Handling

- **"Index not found"**: Run `jfox index rebuild` to build the search index.
- **Empty results**: Try broader query, switch mode to `hybrid`, or lower `--threshold`.
- **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast.
