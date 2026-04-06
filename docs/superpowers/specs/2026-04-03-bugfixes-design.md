# Bug Fix Design: Issues #67, #62, #54

Date: 2026-04-03

## Summary

Fix three independent bugs: missing jinja2 dependency, KB directory management, and silently skipped tests.

## Bug #67 — jinja2 未显式声明为项目依赖

**Problem**: `zk/template.py` imports jinja2 but it's not in `pyproject.toml` dependencies. Works only via transitive dependency.

**Fix**: Add `"jinja2>=3.0"` to `dependencies` list in `zk-cli/pyproject.toml`.

**Files**: `zk-cli/pyproject.toml`

## Bug #62 — 新增知识库时目录未统一管理

**Problem**: `kb_manager.py` creates named KBs at `~/.zettelkasten-{name}` (scattered in home dir). `add_knowledge_base` accepts arbitrary paths without validation.

**Fix**:
1. Change default KB path in `kb_manager.py` from `~/.zettelkasten-{name}` to `~/.zettelkasten/<name>/`
2. Add path validation in `global_config.py` `add_knowledge_base()` — reject paths outside `~/.zettelkasten/`
3. No migration of existing KBs — fix going forward only

**Files**: `zk-cli/zk/kb_manager.py`, `zk-cli/zk/global_config.py`

## Bug #54 — test_suggest_links.py 测试静默 skip

**Problem**: All 5 tests in `TestSuggestLinks` use `try/except Exception + pytest.skip()`, masking real failures including assertion errors and type errors.

**Fix**: Rewrite tests using `cli_fast` fixture (mocked embeddings). Create test notes via the fixture, then call `suggest_links` directly. Remove all `try/except + skip` patterns.

**Files**: `zk-cli/tests/test_suggest_links.py`
