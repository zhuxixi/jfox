# 抑制第三方库 INFO 日志污染 CLI 输出 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抑制第三方库（sentence_transformers、torch、chromadb 等）的 INFO/DEBUG 日志，使其不出现在 CLI 输出中。

**Architecture:** 在 `cli.py` 的 `logging.basicConfig()` 之后，将已知第三方库的 logger 级别设为 WARNING。jfox 自身日志不受影响。

**Tech Stack:** Python stdlib `logging`

**Issue:** #134

---

### Task 1: 添加测试验证第三方库日志被抑制

**Files:**
- Create: `tests/unit/test_logging_config.py`

- [ ] **Step 1: Write the failing test**

验证 `cli.py` 模块导入后，第三方库 logger 级别为 WARNING。

```python
"""测试日志配置：第三方库日志级别应被抑制为 WARNING"""

import logging
import importlib


def test_third_party_loggers_suppressed():
    """导入 jfox.cli 后，第三方库的日志级别应为 WARNING 或更高"""
    import jfox.cli  # noqa: F401

    noisy_libs = [
        "sentence_transformers",
        "torch",
        "chromadb",
        "tqdm",
        "urllib3",
        "watchdog",
        "PIL",
    ]
    for lib in noisy_libs:
        lib_logger = logging.getLogger(lib)
        assert lib_logger.level >= logging.WARNING, (
            f"{lib} logger level is {lib_logger.level}, expected >= {logging.WARNING}"
        )


def test_jfox_own_logger_unchanged():
    """jfox 自身的日志级别应保持 INFO"""
    import jfox.cli  # noqa: F401

    jfox_logger = logging.getLogger("jfox")
    assert jfox_logger.level == logging.INFO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_logging_config.py -v`
Expected: FAIL — 第三方库 logger 级别仍为 NOTSET/DEBUG

---

### Task 2: 实现第三方库日志级别抑制

**Files:**
- Modify: `jfox/cli.py:36-40`

- [ ] **Step 1: 在 `logging.basicConfig()` 之后添加第三方库日志抑制**

将 `jfox/cli.py` 第 36-40 行替换为：

```python
# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 抑制第三方库的 INFO/DEBUG 日志，避免污染 CLI 输出
for _lib in (
    "sentence_transformers",
    "torch",
    "chromadb",
    "tqdm",
    "urllib3",
    "watchdog",
    "PIL",
):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_logging_config.py -v`
Expected: PASS

---

### Task 3: 手动验证

- [ ] **Step 1: 运行 suggest-links 确认输出干净**

Run: `uv run jfox suggest-links "test content" --kb default --format json`
Expected: 无第三方库日志，仅输出 JSON

- [ ] **Step 2: Commit**

```bash
git add jfox/cli.py tests/unit/test_logging_config.py
git commit -m "fix: suppress third-party library INFO logs from CLI output (#134)"
```
