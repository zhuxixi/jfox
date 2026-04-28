# Design: Tag-based Note Filtering (#170)

Date: 2026-04-28
Issue: #170
Status: Approved

## Problem

Tags are stored in notes and persisted to ChromaDB metadata, but no CLI command supports filtering by tag. Users cannot recall notes by tag through `jfox list` or `jfox search`.

## Solution

Add `--tag` (repeatable, AND logic) to `jfox list` and `jfox search`. Thread the `tags` parameter through all layers: CLI → note.py → search_engine.py → vector_store.py. Use ChromaDB's `$contains` metadata filter for semantic/hybrid search, post-filter for BM25, and in-memory filter for list.

## CLI Interface

```
jfox list --tag python --tag async           # List notes tagged with BOTH python AND async
jfox search --tag python "concurrency"       # Pre-filter by tag, then search within that set
```

- `--tag` is repeatable (same pattern as `jfox add --tag`)
- Multiple `--tag` values use AND logic (all tags must match)
- Tags are a hard pre-filter, not a ranking signal

## Data Flow

```
CLI (cli.py)
  └─ list --tag X       → _list_impl(tags=["X"])
       └─ note.list_notes(tags=["X"])
            └─ in-memory filter: all(t in note.tags for t in tags)

  └─ search --tag X     → _search_impl(tags=["X"])
       └─ note.search_notes(tags=["X"])
            └─ search_engine.search(tags=["X"])
                 ├─ vector_store.search(tags=["X"])
                 │    └─ ChromaDB where: {"$and": [{"tags": {"$contains": "X"}}]}
                 └─ bm25_index.search() → post-filter by note.tags
```

## Layer-by-Layer Changes

### 1. vector_store.py — search() method

Add `tags: Optional[List[str]] = None` parameter. Build ChromaDB where clause:

```python
where = {}
if note_type:
    where["type"] = note_type
if tags:
    tag_clauses = [{"tags": {"$contains": t}} for t in tags]
    if where:
        combined = [where] + tag_clauses
        where = {"$and": combined}
    elif len(tag_clauses) > 1:
        where = {"$and": tag_clauses}
    else:
        where = tag_clauses[0]
```

Tags are stored as `",".join(note.tags)` in ChromaDB metadata. `$contains` does literal string matching.

### 2. search_engine.py — HybridSearchEngine.search()

Add `tags: Optional[List[str]] = None`. Pass to `vector_store.search(tags=tags)`. For BM25 results, post-filter:

```python
if tags:
    bm25_results = [r for r in bm25_results
                     if all(t in r.get("metadata", {}).get("tags", "").split(",")
                            for t in tags)]
```

### 3. note.py — search_notes() and list_notes()

- `search_notes()`: add `tags` param, pass to `search_engine.search(tags=tags)`
- `list_notes()`: add `tags: Optional[List[str]] = None`, filter in-memory:

```python
if tags:
    notes = [n for n in notes if all(t in n.tags for t in tags)]
```

### 4. cli.py — search, list, _search_impl, _list_impl

- Add `--tag` option (repeatable `Optional[List[str]]`) to both `search()` and `list()` commands
- Thread through `_search_impl(tags=tags)` and `_list_impl(tags=tags)`

## Files Changed

| File | Change |
|------|--------|
| `jfox/cli.py` | Add `--tag` to `search`, `list`, thread through impl functions |
| `jfox/note.py` | Add `tags` param to `list_notes()`, `search_notes()` |
| `jfox/search_engine.py` | Add `tags` param to `search()`, pass to vector_store + post-filter BM25 |
| `jfox/vector_store.py` | Add `tags` param to `search()`, build `$contains` where clause |

No changes to: `models.py`, `bm25_index.py`, `config.py`, or any file I/O code.

## Edge Cases

### $contains substring matching

ChromaDB `$contains` is literal string matching. Tags like `"web"` could match `"webkit"` within a comma-joined string. For typical Zettelkasten use, this is not a practical concern. If it becomes one, switch to comma-padded storage (`,python,async,`) and check for `,tag,` — but this requires changing the write path and rebuilding the index. Deferred until proven necessary.

### Empty tag list

If `--tag` is not specified, behavior is unchanged (no filtering). If specified with an empty list, treated as no filtering.

### Non-existent tag

Returns empty results (no notes match).

## Testing

### Unit tests (CI fast — no embedding)

- `list_notes(tags=["X"])` correctly filters notes in-memory
- `list_notes(tags=["X", "Y"])` uses AND logic
- `list_notes(tags=["nonexistent"])` returns empty

### Integration tests (CI fast — no embedding)

- `jfox list --tag X --format json` returns only tagged notes via CLI
- `jfox list --tag X --tag Y --format json` AND logic via CLI
- Create notes with tags, verify list filtering

### Integration tests (CI core/full — embedding required, marked `@pytest.mark.embedding`)

- `jfox search --tag X "query"` pre-filters by tag then searches
- Hybrid search with tag filter produces correct intersection

### CI Distribution

- Fast job: runs unit + CLI integration tests for `list --tag` (no embedding needed)
- Core/full job: runs `search --tag` tests (embedding required)
- All tests use `temp_kb` fixture with automatic cleanup — no dirty data

## Out of Scope

- Dedicated `jfox tags` command (tag index with counts) — separate issue
- Tag autocomplete — separate issue
- OR logic for tag matching — not needed per design decision
- Changing tag storage format in ChromaDB — deferred
