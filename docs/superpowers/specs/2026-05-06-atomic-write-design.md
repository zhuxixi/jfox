# 原子写入修复：杜绝 0 字节笔记文件 (#201)

## 问题

`save_note()` 和 `update_note()` 使用 `open(path, "w")` 写入笔记文件。`"w"` 模式立即截断文件为 0 字节，然后才写入内容。如果进程在截断和写入之间被 kill（agent 超时、Ctrl+C、OOM），磁盘上留下 0 字节空文件。

`performance.py` 的批量导入路径有同样问题。

## 修复

### 新增 `_atomic_write()` 工具函数

位置：`jfox/note.py`

```python
import os, tempfile

def _atomic_write(filepath: Path, content: str) -> None:
    """原子写入：先写临时文件再 rename，防止崩溃产生空文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

关键设计点：
- `mkstemp(dir=filepath.parent)` — 临时文件与目标文件同目录，保证 `os.replace` 是同文件系统原子操作
- `BaseException` 捕获 — 包括 KeyboardInterrupt/Ctrl+C
- 异常时清理临时文件，用 try/except OSError 包裹（文件可能已被 fdopen 接管关闭）

### 改造 3 处调用

1. **`save_note()`** (note.py:62-95) — 替换 `mkdir` + `open("w")` + `f.write()` 为 `_atomic_write(note.filepath, note.to_markdown())`
2. **`update_note()`** (note.py:244-292) — 替换 `mkdir` + `open("w")` + `f.write()` 为 `_atomic_write(note_obj.filepath, note_obj.to_markdown())`
3. **`performance.py` 批量导入** (performance.py:238-246) — 替换 `mkdir` + `open("w")` + `f.write()` 为 `_atomic_write(note.filepath, note.to_markdown())`，需从 note.py 导入

### 测试

新增单元测试 `tests/unit/test_atomic_write.py`：
- 正常写入：验证文件内容正确
- 写入异常：模拟 `to_markdown()` 抛异常，验证不留空文件、原文件不受影响
- 临时文件清理：异常后无 `.tmp` 残留

## 不在范围

- `global_config.py`、`bm25_index.py`、`config.py` 等非笔记文件的写入（非核心数据路径，影响小）
- `daemon/process.py` 的 PID 文件写入
