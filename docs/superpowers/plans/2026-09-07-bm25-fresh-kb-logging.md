# BM25 Fresh-KB Logging Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `_read_disk_write_version()` so fresh-KB metadata absence logs INFO (expected path) instead of WARNING, while corrupted-metadata WARNING stays (issue #482, spec `docs/superpowers/specs/2026-09-07-bm25-fresh-kb-logging-design.md`).

**Architecture:** Single-point change in `jfox/bm25_index.py` — split the broad `except` into a leading `FileNotFoundError` branch (INFO + return 0) and the existing broad branch (WARNING + return 0). Return values and control flow unchanged; only log level differs. New unit test file covers both branches plus regression + end-to-end smoke.

**Tech Stack:** Python 3.10+, pytest, logging caplog fixture, uv.

## Global Constraints

- Return value and control flow of `_read_disk_write_version()` must not change (both branches `return 0`) — #396 optimistic-concurrency semantics untouched (spec risk table).
- `FileNotFoundError` must be caught **before** the broad `OSError` branch (it is a subclass).
- No test may depend on embedding models or ChromaDB (unit-level only; spec testability section).
- Line length 100 chars; format with black, lint with ruff.
- All tracked `.md` files must pass `npx --yes markdownlint-cli2` (CI gate).
- Acceptance IDs: Task 1 → A1 (fresh KB: no WARNING, INFO emitted), A2 (corruption: WARNING kept); Task 2 → A3 (existing tests pass), A4 (end-to-end smoke).

---

### Task 1: TDD — log-level split in `_read_disk_write_version`

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging` (absolute paths below start from this worktree root)

**Files:**

- Modify: `jfox/bm25_index.py:239-246` (method `_read_disk_write_version`)
- Create: `tests/unit/test_bm25_fresh_kb_logging.py`

**Interfaces:**

- Consumes: `BM25Index(index_dir: Path)` constructor; class attr `BM25Index.METADATA_FILENAME`; method `_read_disk_write_version(self) -> int` (private; direct-call precedent: `tests/unit/test_bm25_concurrency.py::test_orphan_tmp_self_heal_branch_direct`)
- Produces: behavior — metadata file absent → INFO log `"BM25 metadata not found (fresh KB), write_version treated as 0"` + return 0; corrupted metadata (truncated JSON / malformed field / other OSError) → WARNING `"Failed to read BM25 metadata write_version (...)"` + return 0

- [ ] **Step 0: Prepare worktree env**

Worktree has no `.venv` yet. Run from the worktree root:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging
uv sync --extra dev
```

Expected: resolves from `uv.lock`, creates `.venv` (uv global cache makes this fast). Sanity: `uv run python -c "import jfox; print(jfox.__file__)"` must print a path **inside the worktree** (editable install).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_bm25_fresh_kb_logging.py` with exactly this content:

```python
"""#482: fresh-KB metadata absence is an expected path (INFO), not a failure (WARNING).

_read_disk_write_version 的日志级别语义修正：FileNotFoundError → info（与
_load() 的 "BM25 index not found, will create new index" 先例对齐）；真损坏
（JSON 截断 / 字段畸形 / 其他 OSError）保留 warning 留痕。
"""

import json
import logging

from jfox.bm25_index import BM25Index


class TestFreshKbMissingMetadata:
    """A1: 全新 KB（metadata 不存在）→ INFO，无 WARNING"""

    def test_missing_metadata_logs_info_not_warning(self, tmp_path, caplog):
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        infos = [
            r for r in caplog.records if r.levelname == "INFO" and "fresh KB" in r.message
        ]
        assert infos, "expected an INFO record mentioning fresh KB"
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warnings, f"fresh KB must not emit WARNING, got: {warnings}"


class TestCorruptedMetadataKeepsWarning:
    """A2: 真损坏场景 WARNING 保留"""

    def test_truncated_json_keeps_warning(self, tmp_path, caplog):
        (tmp_path / BM25Index.METADATA_FILENAME).write_text('{"write_version": ', encoding="utf-8")
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        assert any(
            r.levelname == "WARNING" and "Failed to read" in r.message
            for r in caplog.records
        )

    def test_malformed_write_version_field_keeps_warning(self, tmp_path, caplog):
        (tmp_path / BM25Index.METADATA_FILENAME).write_text(
            json.dumps({"write_version": "abc"}), encoding="utf-8"
        )
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        assert any(
            r.levelname == "WARNING" and "Failed to read" in r.message
            for r in caplog.records
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging
uv run pytest tests/unit/test_bm25_fresh_kb_logging.py -v
```

Expected: `test_missing_metadata_logs_info_not_warning` FAILS (currently emits WARNING "Failed to read BM25 metadata write_version", no INFO with "fresh KB"). The two corruption tests PASS already (current code already warns) — they are regression guards for the split.

- [ ] **Step 3: Write minimal implementation**

In `jfox/bm25_index.py`, replace the body of `_read_disk_write_version` (lines ~239-246) — the current single broad except:

```python
        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to read BM25 metadata write_version ({e}), treat as 0")
            return 0
```

with the split version (keep the existing docstring line and `try` block above unchanged):

```python
        except FileNotFoundError:
            # 全新 KB 首写是预期路径（_load() 同场景发 INFO），非异常——降级对齐先例
            logger.info("BM25 metadata not found (fresh KB), write_version treated as 0")
            return 0
        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to read BM25 metadata write_version ({e}), treat as 0")
            return 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_bm25_fresh_kb_logging.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add jfox/bm25_index.py tests/unit/test_bm25_fresh_kb_logging.py
git commit -m "fix(bm25): fresh-KB metadata missing logs info instead of warning (#482)"
```

---

### Task 2: Regression, end-to-end smoke, lint gates

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging`

**Files:**

- No new source files; may fix formatting the previous task's files produced (black/ruff).

**Interfaces:**

- Consumes: Task 1 implementation and test file.
- Produces: verified acceptance A3 (existing BM25 tests green) and A4 (end-to-end smoke: fresh-KB first write has no WARNING on stderr).

- [ ] **Step 1: Run existing BM25 tests (A3)**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging
uv run pytest tests/unit/test_bm25_concurrency.py tests/unit/test_bm25_batch.py -v
```

Expected: all pass (these cover #396 concurrency semantics — proves the change did not disturb them).

- [ ] **Step 2: End-to-end smoke (A4)**

Isolated env (same mechanism as `tests/conftest.py`; never touches real `~/.zettelkasten` or `~/.zk_config.json`):

```bash
export SMOKE=/tmp/issue482-smoke && rm -rf $SMOKE && mkdir -p $SMOKE
export ZK_KB_ROOT=$SMOKE/kbs ZK_CONFIG_PATH=$SMOKE/zk_config.json
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-482-bm25-fresh-kb-logging
uv run jfox kb create smoke >/dev/null 2>&1
uv run jfox add "smoke content" --title "smoke" 2>&1 | tee $SMOKE/out.log | grep -c "Failed to read BM25 metadata" || echo "0 occurrences"
grep -i "fresh KB" $SMOKE/out.log || true
unset ZK_KB_ROOT ZK_CONFIG_PATH SMOKE
rm -rf /tmp/issue482-smoke
```

Expected: `0 occurrences` of "Failed to read BM25 metadata"; the fresh-KB INFO line present in `out.log` (note: INFO shows because non-JSON mode keeps default logging; `jfox add` without `--json`).

- [ ] **Step 3: Lint gates**

```bash
uv run black --check jfox/bm25_index.py tests/unit/test_bm25_fresh_kb_logging.py
uv run ruff check jfox/ tests/
npx --yes markdownlint-cli2 docs/superpowers/specs/2026-09-07-bm25-fresh-kb-logging-design.md docs/superpowers/plans/2026-09-07-bm25-fresh-kb-logging.md
```

Expected: all clean. If black/ruff flags formatting, run `uv run black jfox/bm25_index.py tests/unit/test_bm25_fresh_kb_logging.py` and `uv run ruff check --fix`, re-run Step 1 sanity, then continue.

- [ ] **Step 4: Commit (only if lint produced fixes)**

```bash
git add -u
git commit -m "style: apply black/ruff to #482 changes"
```

(If nothing changed, skip — no empty commit.)
