# Fix Last Used Never - 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `Last Used` field always showing "Never" by calling `update_last_used()` in `use_kb()` and adding 5-minute throttling to prevent excessive disk writes.

**Architecture:** Two changes — add `update_last_used()` call in both paths of `use_kb()` context manager, and add a TTL-based throttle inside `update_last_used()` itself so all callers benefit.

**Tech Stack:** Python 3.10+, pytest, unittest.mock

---

### Task 1: Add throttling to `update_last_used()`

**Files:**
- Modify: `jfox/global_config.py:315-324`
- Test: `tests/unit/test_global_config.py`

- [ ] **Step 1: Write failing tests for throttling**

Add to `tests/unit/test_global_config.py`, inside `class TestGlobalConfigManager`, after `test_update_last_used_nonexistent` (around line 465):

```python
def test_update_last_used_throttle_skips_recent(self, manager):
    """5分钟内不重复写入"""
    recent_time = datetime.now().isoformat()
    entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=recent_time)
    manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

    with patch.object(manager, "_save", return_value=True) as mock_save:
        result = manager.update_last_used("my_kb")

    assert result is True
    mock_save.assert_not_called()  # 跳过写入

def test_update_last_used_throttle_allows_stale(self, manager):
    """超过5分钟则正常写入"""
    stale_time = "2020-01-01T00:00:00"
    entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=stale_time)
    manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

    with patch.object(manager, "_save", return_value=True):
        result = manager.update_last_used("my_kb")

    assert result is True
    assert entry.last_used != stale_time

def test_update_last_used_no_throttle_when_null(self, manager):
    """last_used 为 None 时直接写入"""
    entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=None)
    manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

    with patch.object(manager, "_save", return_value=True):
        result = manager.update_last_used("my_kb")

    assert result is True
    assert entry.last_used is not None
```

需要确保文件顶部有 `from datetime import datetime` import（已有则跳过）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_global_config.py::TestGlobalConfigManager::test_update_last_used_throttle_skips_recent tests/unit/test_global_config.py::TestGlobalConfigManager::test_update_last_used_throttle_allows_stale tests/unit/test_global_config.py::TestGlobalConfigManager::test_update_last_used_no_throttle_when_null -v`
Expected: `test_update_last_used_throttle_skips_recent` FAIL (currently `_save` is always called)

- [ ] **Step 3: Add throttling to `update_last_used()`**

Replace `jfox/global_config.py:315-324`:

```python
    def update_last_used(self, name: str) -> bool:
        """更新知识库最后使用时间（5分钟内不重复写入）"""
        config = self._load()

        if name in config.knowledge_bases:
            existing = config.knowledge_bases[name].last_used
            if existing:
                try:
                    last_time = datetime.fromisoformat(existing)
                    if (datetime.now() - last_time).total_seconds() < 300:
                        return True
                except (ValueError, TypeError):
                    pass
            config.knowledge_bases[name].last_used = datetime.now().isoformat()
            self._config = config
            return self._save()

        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_global_config.py::TestGlobalConfigManager::test_update_last_used -v`
Expected: ALL PASS (包括原有的 2 个 + 新增的 3 个)

- [ ] **Step 5: Commit**

```bash
git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "fix: add 5-minute throttle to update_last_used()"
```

---

### Task 2: Call `update_last_used()` in `use_kb()` Path A (default KB)

**Files:**
- Modify: `jfox/config.py:174-176`
- Test: `tests/unit/test_use_kb_env_var.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_use_kb_env_var.py`, inside `class TestUseKbEnvVar`, after `test_no_env_var_falls_back_to_global_default`:

```python
def test_default_kb_updates_last_used(self):
    """使用默认 KB 时应更新 last_used"""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("JFOX_KB", None)
        with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.get_default_kb_name.return_value = "default"
            mock_manager.config_manager.update_last_used.return_value = True
            mock_get_manager.return_value = mock_manager

            with use_kb(None) as _:
                pass

            mock_manager.config_manager.update_last_used.assert_called_once_with("default")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py::TestUseKbEnvVar::test_default_kb_updates_last_used -v`
Expected: FAIL — `update_last_used` is not called in Path A

- [ ] **Step 3: Fix existing test that will break**

`test_no_env_var_falls_back_to_global_default` (line 66-78) currently asserts `mock_get_manager.assert_not_called()`. After our change, Path A will call `get_kb_manager()`. Update this test:

```python
def test_no_env_var_falls_back_to_global_default(self):
    """当没有设置 JFOX_KB 且 kb_name 为 None 时，应直接使用当前默认知识库"""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("JFOX_KB", None)
        with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.get_default_kb_name.return_value = "default"
            mock_manager.config_manager.update_last_used.return_value = True
            mock_get_manager.return_value = mock_manager
            original_base_dir = config.base_dir

            with use_kb(None) as _:
                # 验证配置没有被修改
                assert config.base_dir == original_base_dir
```

- [ ] **Step 4: Add `update_last_used()` call in Path A**

Replace `jfox/config.py:174-176`:

```python
        else:
            from .kb_manager import get_kb_manager

            manager = get_kb_manager()
            default_name = manager.config_manager.get_default_kb_name()
            manager.config_manager.update_last_used(default_name)

            yield
            return
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/config.py tests/unit/test_use_kb_env_var.py
git commit -m "fix: update last_used when using default KB (use_kb Path A)"
```

---

### Task 3: Call `update_last_used()` in `use_kb()` Path B (explicit --kb / JFOX_KB)

**Files:**
- Modify: `jfox/config.py:199-200` (the line after `config.chroma_dir` assignment)
- Test: `tests/unit/test_use_kb_env_var.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_use_kb_env_var.py`:

```python
def test_explicit_kb_updates_last_used(self):
    """通过 --kb 指定知识库时应更新 last_used"""
    with patch("jfox.config._reset_singletons"):
        with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.kb_exists.return_value = True
            mock_manager.config_manager.get_kb_path.return_value = (
                config.base_dir.parent / "work"
            )
            mock_manager.config_manager.update_last_used.return_value = True
            mock_get_manager.return_value = mock_manager

            with use_kb("work") as _:
                pass

            mock_manager.config_manager.update_last_used.assert_called_once_with("work")

def test_env_var_kb_updates_last_used(self):
    """通过 JFOX_KB 环境变量指定知识库时应更新 last_used"""
    with patch.dict(os.environ, {"JFOX_KB": "work"}):
        with patch("jfox.config._reset_singletons"):
            with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
                mock_manager = Mock()
                mock_manager.config_manager.kb_exists.return_value = True
                mock_manager.config_manager.get_kb_path.return_value = (
                    config.base_dir.parent / "work"
                )
                mock_manager.config_manager.update_last_used.return_value = True
                mock_get_manager.return_value = mock_manager

                with use_kb(None) as _:
                    pass

                mock_manager.config_manager.update_last_used.assert_called_once_with("work")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py::TestUseKbEnvVar::test_explicit_kb_updates_last_used tests/unit/test_use_kb_env_var.py::TestUseKbEnvVar::test_env_var_kb_updates_last_used -v`
Expected: FAIL — `update_last_used` is not called in Path B

- [ ] **Step 3: Add `update_last_used()` call in Path B**

In `jfox/config.py`, after line 197 (`config.chroma_dir = config.zk_dir / "chroma_db"`) and before line 199 (`# 重置索引和搜索引擎`), add:

```python
            # 更新最后使用时间
            manager.config_manager.update_last_used(kb_name)
```

The result should be:

```python
            config.chroma_dir = config.zk_dir / "chroma_db"

            # 更新最后使用时间
            manager.config_manager.update_last_used(kb_name)

            # 重置索引和搜索引擎（使用新的知识库路径）
            _reset_singletons()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py -v`
Expected: ALL PASS (including all existing tests)

- [ ] **Step 5: Commit**

```bash
git add jfox/config.py tests/unit/test_use_kb_env_var.py
git commit -m "fix: update last_used when using explicit --kb or JFOX_KB (use_kb Path B)"
```

---

### Task 4: Verify existing tests still pass

**Files:** None (verification only)

- [ ] **Step 1: Run all use_kb and global_config tests**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py tests/unit/test_global_config.py tests/unit/test_kb_manager.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run broader fast test suite to check for regressions**

Run: `uv run pytest tests/ -m "not slow and not embedding" -x -q`
Expected: ALL PASS (this is fast, no embedding loading)

- [ ] **Step 3: Manual verification**

Run: `uv run jfox add "test last_used fix" --type fleeting`
Then check: `cat ~/.zk_config.json | python -c "import sys,json; d=json.load(sys.stdin); print(d['knowledge_bases']['default']['last_used'])"`
Expected: a non-null ISO timestamp

- [ ] **Step 4: Commit (if any adjustments needed from regression fixes)**
