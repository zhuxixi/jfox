# Kimi Code Auto-Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 JFox auto-summary 支持扫描 Kimi Code 的 session（与 Claude Code 共存），并把总结笔记升级为五段 compact 结构。

**Architecture:** 引入 `SessionSource` 协议 + 工厂（`get_sources(cfg)`）；`ClaudeCodeSource` 封装现有 scanner/extractor 逻辑（零改动），`KimiCodeSource` 新写扫描 + wire.jsonl/state.json 解析；runner 改为面向 source 编程；ledger key 加来源前缀并迁移旧数据。

**Tech Stack:** Python ≥3.10，pytest，dataclasses，pathlib。无新依赖。

**Spec:** `docs/superpowers/specs/2026-06-16-kimi-code-auto-summary-design.md`（Issue #242）

**测试纪律**：本计划所有单测均为快速测试（无 embedding/ChromaDB/网络），可自主运行。最终集成测试交用户运行。

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `jfox/auto_summary/scanner.py` | `SessionFile` dataclass 加 `source` 字段 | Modify |
| `jfox/auto_summary/sources.py` | `SessionSource` Protocol + `ClaudeCodeSource` + `get_sources()` + `session_key()` + `extract_dialog_for()` | Create |
| `jfox/auto_summary/kimi_source.py` | `KimiCodeSource`：扫描 wire.jsonl + 解析 | Create |
| `jfox/auto_summary/runner.py` | `scan_pending`/`summarize_one` 改面向 source；`SYSTEM_PROMPT` 五段 | Modify |
| `jfox/auto_summary/ledger.py` | `_load` 迁移裸 key → `claude:` 前缀 | Modify |
| `jfox/global_config.py` | `AutoSummaryConfig` 加 `session_sources`/`kimi_sessions_dir` | Modify |
| `tests/unit/test_*.py` | 各任务单测 | Create |
| `tests/integration/test_auto_summary_kimi.py` | 端到端集成（mock claude） | Create |

---

## Task 1: ledger key 来源前缀 + 旧数据迁移

**Files:**

- Modify: `jfox/auto_summary/ledger.py`（`_load` 方法，约 118-126 行）
- Test: `tests/unit/test_ledger_migration.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_ledger_migration.py
import json
from jfox.auto_summary.ledger import Ledger, SessionStatus


def _write_ledger(path, sessions):
    path.write_text(json.dumps({"version": 1, "sessions": sessions}), encoding="utf-8")


def test_legacy_bare_key_migrated_to_claude_prefix(tmp_path):
    f = tmp_path / "state.json"
    _write_ledger(f, {
        "abc-123": {"project": "p", "processed_at": "2026-01-01T00:00:00",
                    "status": "success", "note_id": "n1"}
    })
    led = Ledger(path=f)
    assert "claude:abc-123" in led.all_entries()
    assert "abc-123" not in led.all_entries()
    assert led.is_done("claude:abc-123")


def test_prefixed_key_not_double_prefixed(tmp_path):
    f = tmp_path / "state.json"
    _write_ledger(f, {
        "kimi:xyz": {"project": "p", "processed_at": "2026-01-01T00:00:00",
                     "status": "skipped"}
    })
    led = Ledger(path=f)
    assert "kimi:xyz" in led.all_entries()
    assert "claude:kimi:xyz" not in led.all_entries()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_ledger_migration.py -v`
Expected: FAIL —— 旧 key 未被加前缀，`"claude:abc-123" not in all_entries()`

- [ ] **Step 3: 实现——在 `_load` 解析 sessions 后迁移**

在 `jfox/auto_summary/ledger.py` 的 `_load` 方法里，找到构建 `sessions` dict 的位置（约 119-121 行），在其后加入迁移逻辑：

```python
        sessions_raw = raw.get("sessions", {})
        sessions = {
            sid: LedgerEntry.from_dict(d)
            for sid, d in sessions_raw.items()
            if isinstance(d, dict)
        }
        # 迁移：旧版裸 session_id（不含 ':')视为 claude 来源，加前缀
        sessions = {
            (sid if ":" in sid else f"claude:{sid}"): entry
            for sid, entry in sessions.items()
        }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_ledger_migration.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 回归 + commit**

Run: `uv run pytest tests/unit/ -k ledger -v`（若有现有 ledger 测试，确认不破）

```bash
git add jfox/auto_summary/ledger.py tests/unit/test_ledger_migration.py
git commit -m "feat(auto-summary): prefix ledger keys with source, migrate legacy bare keys"
```

---

## Task 2: AutoSummaryConfig 加 session_sources / kimi_sessions_dir

**Files:**

- Modify: `jfox/global_config.py`（`AutoSummaryConfig`，约 47-104 行）
- Test: `tests/unit/test_auto_summary_config_sources.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_auto_summary_config_sources.py
from jfox.global_config import AutoSummaryConfig


def test_default_sources_both_enabled():
    cfg = AutoSummaryConfig()
    assert cfg.session_sources == ["claude", "kimi"]
    assert cfg.kimi_sessions_dir is None


def test_from_dict_legacy_config_gets_default_sources():
    cfg = AutoSummaryConfig.from_dict({"enabled": True})
    assert cfg.enabled is True
    assert cfg.session_sources == ["claude", "kimi"]


def test_roundtrip_preserves_sources():
    cfg = AutoSummaryConfig(session_sources=["claude"], kimi_sessions_dir="/tmp/k")
    cfg2 = AutoSummaryConfig.from_dict(cfg.to_dict())
    assert cfg2.session_sources == ["claude"]
    assert cfg2.kimi_sessions_dir == "/tmp/k"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_auto_summary_config_sources.py -v`
Expected: FAIL —— `AutoSummaryConfig` 无 `session_sources` 属性

- [ ] **Step 3: 实现**

在 `jfox/global_config.py` 的 `AutoSummaryConfig` dataclass 中（`claude_binary` 字段后）加两个字段：

```python
    claude_binary: Optional[str] = None  # claude 命令路径；None 表示从 PATH 解析
    session_sources: List[str] = field(default_factory=lambda: ["claude", "kimi"])  # 启用的扫描来源
    kimi_sessions_dir: Optional[str] = None  # None → ~/.kimi-code/sessions
```

并在 `from_dict` 的 `return cls(...)` 里加：

```python
            claude_binary=data.get("claude_binary"),
            session_sources=list(data.get("session_sources", ["claude", "kimi"])),
            kimi_sessions_dir=data.get("kimi_sessions_dir"),
```

> `to_dict` 用 `asdict`，自动包含新字段，无需改。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_auto_summary_config_sources.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: commit**

```bash
git add jfox/global_config.py tests/unit/test_auto_summary_config_sources.py
git commit -m "feat(auto-summary): add session_sources and kimi_sessions_dir config"
```

---

## Task 3: SessionFile 加 source 字段

**Files:**

- Modify: `jfox/auto_summary/scanner.py`（`SessionFile` dataclass，约 31-39 行）
- Test: `tests/unit/test_session_file_source.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_session_file_source.py
from pathlib import Path
from jfox.auto_summary.scanner import SessionFile


def test_default_source_is_claude():
    sf = SessionFile(session_id="x", project_dir_name="p",
                     path=Path("/a.jsonl"), mtime=0.0, size_bytes=10)
    assert sf.source == "claude"


def test_source_can_be_kimi():
    sf = SessionFile(session_id="x", project_dir_name="p",
                     path=Path("/a.jsonl"), mtime=0.0, size_bytes=10, source="kimi")
    assert sf.source == "kimi"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_session_file_source.py -v`
Expected: FAIL —— `SessionFile` 无 `source` 字段（TypeError: unexpected keyword 'source' 或 AttributeError）

- [ ] **Step 3: 实现**

在 `jfox/auto_summary/scanner.py` 的 `SessionFile` dataclass 里加字段（带默认值，保证现有构造兼容）：

```python
@dataclass(frozen=True)
class SessionFile:
    """一个待处理的 session 文件"""

    session_id: str  # UUID（去掉 .jsonl 后缀的文件名）
    project_dir_name: str  # 来源相关目录名
    path: Path
    mtime: float  # epoch seconds
    size_bytes: int
    source: str = "claude"  # "claude" / "kimi"
```

> `iter_session_files` 现有构造不传 `source`，自动用默认 `"claude"`，无需改动。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_session_file_source.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 回归 scanner 现有测试 + commit**

Run: `uv run pytest tests/unit/ -k scanner -v`（若有；否则跑 Task 3 两个用例即可）

```bash
git add jfox/auto_summary/scanner.py tests/unit/test_session_file_source.py
git commit -m "feat(auto-summary): add source field to SessionFile"
```

---

## Task 4: SessionSource 协议 + ClaudeCodeSource + 工厂

**Files:**

- Create: `jfox/auto_summary/sources.py`
- Test: `tests/unit/test_session_source.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_session_source.py
from pathlib import Path
from unittest.mock import patch
from jfox.auto_summary.sources import (
    session_key, ClaudeCodeSource, get_sources, kimi_sessions_dir,
)
from jfox.auto_summary.scanner import SessionFile
from jfox.global_config import AutoSummaryConfig


def test_session_key_format():
    sf = SessionFile(session_id="abc", project_dir_name="p",
                     path=Path("/a"), mtime=0.0, size_bytes=1, source="kimi")
    assert session_key(sf) == "kimi:abc"


def test_get_sources_skips_missing_dirs(tmp_path):
    # claude 目录不存在，kimi 目录不存在 → 都跳过
    cfg = AutoSummaryConfig(
        kimi_sessions_dir=str(tmp_path / "no-kimi"),
    )
    with patch("jfox.auto_summary.sources.default_claude_projects_dir",
               return_value=tmp_path / "no-claude"):
        sources = get_sources(cfg)
    assert sources == []


def test_get_sources_includes_kimi_when_dir_exists(tmp_path):
    (tmp_path / "kimi").mkdir()
    cfg = AutoSummaryConfig(kimi_sessions_dir=str(tmp_path / "kimi"))
    with patch("jfox.auto_summary.sources.default_claude_projects_dir",
               return_value=tmp_path / "no-claude"):
        sources = get_sources(cfg)
    assert [s.name for s in sources] == ["kimi"]


def test_kimi_sessions_dir_default(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("/fakehome"))
    assert kimi_sessions_dir(AutoSummaryConfig()) == Path("/fakehome/.kimi-code/sessions")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_session_source.py -v`
Expected: FAIL —— `jfox.auto_summary.sources` 模块不存在（ImportError）

- [ ] **Step 3: 实现 sources.py**

```python
# jfox/auto_summary/sources.py
"""
Session 来源抽象：把 Claude Code / Kimi Code 的「扫描 + 对话提取」收拢为
统一的 SessionSource 接口，runner 只面向接口编程。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, Optional, Protocol, runtime_checkable

from ..global_config import AutoSummaryConfig
from .extractor import ExtractedDialog, extract_dialog
from .kimi_source import KimiCodeSource
from .scanner import SessionFile, default_claude_projects_dir, iter_session_files

logger = logging.getLogger(__name__)


def session_key(sf: SessionFile) -> str:
    """统一的 ledger 去重键：{source}:{session_id}"""
    return f"{sf.source}:{sf.session_id}"


@runtime_checkable
class SessionSource(Protocol):
    name: str

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]: ...

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog: ...


class ClaudeCodeSource:
    """封装现有 scanner + extractor，逻辑零改动。"""

    name = "claude"

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        yield from iter_session_files(
            idle_threshold_minutes=cfg.idle_threshold_minutes,
            max_session_size_mb=cfg.max_session_size_mb,
            min_session_size_kb=cfg.min_session_size_kb,
            skip_after_days=cfg.skip_after_days,
        )

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        return extract_dialog(sf.path)


def kimi_sessions_dir(cfg: AutoSummaryConfig) -> Path:
    """返回 Kimi session 根目录（配置优先，否则 ~/.kimi-code/sessions）"""
    if cfg.kimi_sessions_dir:
        return Path(cfg.kimi_sessions_dir).expanduser()
    return Path.home() / ".kimi-code" / "sessions"


def get_sources(cfg: AutoSummaryConfig) -> list[SessionSource]:
    """按 cfg.session_sources 返回启用的来源实例，auto-detect 目录存在性。"""
    sources: list[SessionSource] = []
    for name in cfg.session_sources:
        if name == "claude":
            if default_claude_projects_dir().is_dir():
                sources.append(ClaudeCodeSource())
            else:
                logger.info("跳过 claude 来源：目录不存在 %s", default_claude_projects_dir())
        elif name == "kimi":
            kdir = kimi_sessions_dir(cfg)
            if kdir.is_dir():
                sources.append(KimiCodeSource(kdir))
            else:
                logger.info("跳过 kimi 来源：目录不存在 %s", kdir)
        else:
            logger.warning("未知 session source: %s（已忽略）", name)
    return sources


def extract_dialog_for(sf: SessionFile, cfg: AutoSummaryConfig) -> ExtractedDialog:
    """按 sf.source 找到对应 source 并提取对话（供 runner.summarize_one 使用）。"""
    for src in get_sources(cfg):
        if src.name == sf.source:
            return src.extract_dialog(sf)
    raise ValueError(f"没有启用的来源匹配 source={sf.source!r}")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_session_source.py -v`
Expected: PASS（4 passed）

> 注意：本任务依赖 `KimiCodeSource`（Task 5/6 实现）。为让 Task 4 测试通过，先在 `kimi_source.py` 放一个最小桩：

```python
# jfox/auto_summary/kimi_source.py（最小桩，Task 5/6 填充）
from __future__ import annotations
from pathlib import Path


class KimiCodeSource:
    name = "kimi"

    def __init__(self, kimi_dir: Path):
        self.kimi_dir = kimi_dir
```

- [ ] **Step 5: commit**

```bash
git add jfox/auto_summary/sources.py jfox/auto_summary/kimi_source.py tests/unit/test_session_source.py
git commit -m "feat(auto-summary): add SessionSource protocol, ClaudeCodeSource and get_sources factory"
```

---

## Task 5: KimiCodeSource.iter_sessions 扫描

**Files:**

- Modify: `jfox/auto_summary/kimi_source.py`
- Test: `tests/unit/test_kimi_scanner.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_kimi_scanner.py
import os
from pathlib import Path
from jfox.auto_summary.kimi_source import KimiCodeSource
from jfox.global_config import AutoSummaryConfig


def _make_session(root, wd, sess, wire_text="x" * 6000, age_secs=3600):
    wire = root / wd / sess / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True, exist_ok=True)
    wire.write_text(wire_text, encoding="utf-8")
    old = os.path.getmtime(wire) - age_secs
    os.utime(wire, (old, old))
    return wire


def test_iter_sessions_finds_wire_jsonl(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1")
    src = KimiCodeSource(tmp_path)
    cfg = AutoSummaryConfig()
    found = list(src.iter_sessions(cfg))
    assert len(found) == 1
    assert found[0].source == "kimi"
    assert found[0].session_id == "s1"
    assert found[0].project_dir_name == "wd_jfox_abc"
    assert found[0].path.name == "wire.jsonl"


def test_iter_sessions_skips_too_recent(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1", age_secs=10)  # 未静默
    src = KimiCodeSource(tmp_path)
    assert list(src.iter_sessions(AutoSummaryConfig())) == []


def test_iter_sessions_skips_too_small(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1", wire_text="x" * 100)  # <5KB
    src = KimiCodeSource(tmp_path)
    assert list(src.iter_sessions(AutoSummaryConfig())) == []


def test_iter_sessions_ignores_non_session_dirs(tmp_path):
    _make_session(tmp_path, "wd_jfox_abc", "session_s1")
    (tmp_path / "random_dir").mkdir()  # 非 wd_ 开头
    src = KimiCodeSource(tmp_path)
    assert len(list(src.iter_sessions(AutoSummaryConfig()))) == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_kimi_scanner.py -v`
Expected: FAIL —— `iter_sessions` 未实现，返回空

- [ ] **Step 3: 实现 iter_sessions**

替换 `jfox/auto_summary/kimi_source.py` 全文：

```python
# jfox/auto_summary/kimi_source.py
"""
Kimi Code session 来源：扫描 ~/.kimi-code/sessions/wd_*/session_*/agents/main/wire.jsonl，
解析 wire 协议提取对话。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Iterator, Optional

from ..global_config import AutoSummaryConfig
from .extractor import ExtractedDialog
from .scanner import SessionFile

logger = logging.getLogger(__name__)


class KimiCodeSource:
    name = "kimi"

    def __init__(self, kimi_dir: Path):
        self.kimi_dir = kimi_dir

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        """遍历 kimi_dir/wd_*/session_*/agents/main/wire.jsonl，按 mtime/size 过滤。"""
        if not self.kimi_dir.is_dir():
            return

        now = time.time()
        idle_sec = max(0, cfg.idle_threshold_minutes) * 60
        min_size = max(0, cfg.min_session_size_kb) * 1024
        max_size = max(0, cfg.max_session_size_mb) * 1024 * 1024
        skip_sec = max(0, cfg.skip_after_days) * 86400

        for wd in sorted(self.kimi_dir.iterdir()):
            if not wd.is_dir() or not wd.name.startswith("wd_"):
                continue
            for sess in sorted(wd.iterdir()):
                if not sess.is_dir() or not sess.name.startswith("session_"):
                    continue
                wire = sess / "agents" / "main" / "wire.jsonl"
                if not wire.is_file():
                    continue
                try:
                    stat = wire.stat()
                except OSError as e:
                    logger.debug("无法 stat %s: %s", wire, e)
                    continue
                size, mtime = stat.st_size, stat.st_mtime
                age = now - mtime
                if size < min_size:
                    continue
                if max_size and size > max_size:
                    logger.debug("跳过过大 kimi session %s", wire)
                    continue
                if age < idle_sec:
                    continue
                if skip_sec and age > skip_sec:
                    continue
                yield SessionFile(
                    session_id=sess.name[len("session_"):],
                    project_dir_name=wd.name,
                    path=wire,
                    mtime=mtime,
                    size_bytes=size,
                    source="kimi",
                )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_kimi_scanner.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: commit**

```bash
git add jfox/auto_summary/kimi_source.py tests/unit/test_kimi_scanner.py
git commit -m "feat(auto-summary): KimiCodeSource.iter_sessions scans wire.jsonl"
```

---

## Task 6: KimiCodeSource.extract_dialog 解析

**Files:**

- Modify: `jfox/auto_summary/kimi_source.py`（加 `extract_dialog` + 辅助函数）
- Test: `tests/unit/test_kimi_extractor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_kimi_extractor.py
import json
from pathlib import Path
from jfox.auto_summary.kimi_source import KimiCodeSource
from jfox.auto_summary.scanner import SessionFile


def _session_file(tmp_path) -> SessionFile:
    wire = tmp_path / "wd_jfox_abc" / "session_s1" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    sess_dir = wire.parent.parent.parent  # session_s1
    state = {
        "createdAt": "2026-06-15T14:13:57.138Z",
        "updatedAt": "2026-06-15T14:42:02.478Z",
        "title": "demo",
    }
    (sess_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    rows = [
        {"type": "metadata", "created_at": 1781532837205, "app_version": "0.14.3"},
        {"type": "turn.prompt", "input": [{"type": "text", "text": "list open issues"}],
         "time": 1781532844222},
        {"type": "context.append_message",
         "message": {"role": "user",
                     "content": [{"type": "text", "text": "list open issues"}]},
         "time": 1781532844226},
        {"type": "context.append_loop_event",
         "event": {"cwd": "/home/elling/git-repo/github/jfox"}, "time": 1781532844230},
        {"type": "context.append_message",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "here are the issues"}]},
         "time": 1781532845000},
        {"type": "usage.record", "tokens": 123, "time": 1781532845100},
    ]
    wire.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return SessionFile(session_id="s1", project_dir_name="wd_jfox_abc",
                       path=wire, mtime=0.0, size_bytes=600, source="kimi")


def test_extract_dialog_pulls_messages_and_skips_noise(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert "list open issues" in d.dialog_text
    assert "here are the issues" in d.dialog_text
    assert "usage.record" not in d.dialog_text  # 噪音过滤
    assert d.user_turn_count >= 1
    assert d.assistant_turn_count == 1


def test_extract_dialog_cwd_from_loop_event(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.cwd == "/home/elling/git-repo/github/jfox"


def test_extract_dialog_timestamps_from_state_json(tmp_path):
    sf = _session_file(tmp_path)
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.started_at == "2026-06-15T14:13:57.138Z"
    assert d.ended_at == "2026-06-15T14:42:02.478Z"


def test_extract_dialog_state_missing_falls_back_to_wire_time(tmp_path):
    sf = _session_file(tmp_path)
    (sf.path.parent.parent.parent / "state.json").unlink()  # 删 state
    src = KimiCodeSource(tmp_path)
    d = src.extract_dialog(sf)
    assert d.started_at is not None  # 从首行 time(毫秒) 推导
    assert d.ended_at is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_kimi_extractor.py -v`
Expected: FAIL —— `extract_dialog` 未实现

- [ ] **Step 3: 实现 extract_dialog + 辅助**

在 `jfox/auto_summary/kimi_source.py` 的 `KimiCodeSource` 类内追加方法，并在模块顶层加辅助函数：

```python
# ---- 模块顶层辅助 ----
from datetime import datetime, timezone


def _ms_to_iso(ms: int) -> Optional[str]:
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _flatten_text(content) -> str:
    """Kimi content: [{type:text,text:...}, ...] → 纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts)
    return ""


def _find_cwd(record: dict) -> Optional[str]:
    """在 loop_event 记录里递归找 cwd 字段"""
    def _walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("cwd"), str):
                return o["cwd"]
            for v in o.values():
                r = _walk(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = _walk(v)
                if r:
                    return r
        return None
    return _walk(record)
```

在 `KimiCodeSource` 类内追加：

```python
    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        result = ExtractedDialog()
        result.project_dir_name = sf.project_dir_name

        session_dir = sf.path.parent.parent.parent  # wire.jsonl → main → agents → session_<uuid>
        self._read_state(session_dir / "state.json", result)

        turns: list[str] = []
        cwd: Optional[str] = None
        first_time: Optional[int] = None
        last_time: Optional[int] = None

        try:
            with open(sf.path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    t = rec.get("type")
                    if isinstance(rec.get("time"), int):
                        if first_time is None:
                            first_time = rec["time"]
                        last_time = rec["time"]

                    if t == "context.append_loop_event" and cwd is None:
                        cwd = _find_cwd(rec)
                    elif t == "context.append_message":
                        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
                        role = msg.get("role") or "user"
                        text = _flatten_text(msg.get("content")).strip()
                        if text:
                            turns.append(f"## {role}\n\n{text}")
                            if role == "user":
                                result.user_turn_count += 1
                            elif role == "assistant":
                                result.assistant_turn_count += 1
                    elif t == "turn.prompt":
                        text = _flatten_text(rec.get("input")).strip()
                        if text:
                            turns.append(f"## user\n\n{text}")
                            result.user_turn_count += 1
        except OSError as e:
            logger.warning("读取 kimi session 失败 %s: %s", sf.path, e)

        result.cwd = cwd
        result.dialog_text = "\n\n---\n\n".join(turns)

        # 时间戳降级：state.json 没给则从 wire time(毫秒)推导
        if result.started_at is None and first_time is not None:
            result.started_at = _ms_to_iso(first_time)
        if result.ended_at is None and last_time is not None:
            result.ended_at = _ms_to_iso(last_time)
        return result

    @staticmethod
    def _read_state(state_path: Path, result: ExtractedDialog) -> None:
        if not state_path.is_file():
            return
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("state.json 读取失败 %s: %s", state_path, e)
            return
        if isinstance(data, dict):
            if isinstance(data.get("createdAt"), str):
                result.started_at = data["createdAt"]
            if isinstance(data.get("updatedAt"), str):
                result.ended_at = data["updatedAt"]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_kimi_extractor.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: commit**

```bash
git add jfox/auto_summary/kimi_source.py tests/unit/test_kimi_extractor.py
git commit -m "feat(auto-summary): KimiCodeSource.extract_dialog parses wire.jsonl + state.json"
```

---

## Task 7: runner 改为面向 source

**Files:**

- Modify: `jfox/auto_summary/runner.py`（`scan_pending` 约 98-118，`summarize_one` 约 161-276）
- Test: `tests/unit/test_runner_multi_source.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_runner_multi_source.py
from unittest.mock import MagicMock
from jfox.auto_summary import runner
from jfox.auto_summary.scanner import SessionFile
from pathlib import Path


def test_scan_pending_merges_multiple_sources(monkeypatch):
    claude_sf = SessionFile("c1", "proj", Path("/c.jsonl"), 0.0, 10, "claude")
    kimi_sf = SessionFile("k1", "wd_jfox_x", Path("/k.jsonl"), 0.0, 10, "kimi")

    claude_src = MagicMock()
    claude_src.name = "claude"
    claude_src.iter_sessions.return_value = iter([claude_sf])
    kimi_src = MagicMock()
    kimi_src.name = "kimi"
    kimi_src.iter_sessions.return_value = iter([kimi_sf])

    monkeypatch.setattr(runner, "get_sources", lambda cfg: [claude_src, kimi_src])

    ledger = MagicMock()
    ledger.is_done.return_value = False
    pending = runner.scan_pending(ledger=ledger)
    keys = sorted(runner.session_key(sf) for sf in pending)
    assert keys == ["claude:c1", "kimi:k1"]


def test_summarize_one_uses_source_extract_and_prefixed_key(monkeypatch):
    sf = SessionFile("k1", "wd_jfox_x", Path("/k.jsonl"), 0.0, 10, "kimi")
    kimi_src = MagicMock()
    kimi_src.name = "kimi"
    extracted = MagicMock()
    extracted.dialog_text = "hello"
    extracted.user_turn_count = 1
    extracted.cwd = None
    extracted.git_branch = None
    extracted.started_at = None
    extracted.ended_at = None
    extracted.assistant_turn_count = 0
    extracted.truncated = False
    kimi_src.extract_dialog.return_value = extracted
    monkeypatch.setattr(runner, "get_sources", lambda cfg: [kimi_src])

    ledger = MagicMock()
    ledger.is_done.return_value = False
    ledger.get.return_value = None

    # 让 _invoke_claude 返回 skip，快速走 ledger.record_skip 分支验证 key
    monkeypatch.setattr(runner, "_invoke_claude",
                        lambda extracted_dialog_text, cfg: '{"skip": true, "reason": "test"}')
    result = runner.summarize_one(sf, ledger=ledger)
    # record_skip 被调用，且 key 带前缀
    assert ledger.record_skip.called
    called_key = ledger.record_skip.call_args[0][0]
    assert called_key == "kimi:k1"
    assert result.outcome.value == "skipped"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_runner_multi_source.py -v`
Expected: FAIL —— runner 仍用单一 `iter_session_files`、裸 session_id

- [ ] **Step 3: 实现——修改 runner.py**

在 `jfox/auto_summary/runner.py` 顶部 import 区追加：

```python
from .sources import (
    extract_dialog_for,
    get_sources,
    session_key,
)
```

改写 `scan_pending`（替换原 `iter_session_files` 循环为多源遍历）：

```python
def scan_pending(
    cfg: Optional[AutoSummaryConfig] = None,
    claude_projects_dir: Optional[Path] = None,
    ledger: Optional[Ledger] = None,
) -> list[SessionFile]:
    """返回当前会被 run_once 处理的 session 列表（已过滤 ledger 中已了结的）"""
    cfg = cfg or get_global_config_manager().get_auto_summary_config()
    ledger = ledger if ledger is not None else Ledger()

    pending: list[SessionFile] = []
    for source in get_sources(cfg):
        for sf in source.iter_sessions(cfg):
            if ledger.is_done(session_key(sf)):
                continue
            pending.append(sf)
    return pending
```

在 `summarize_one` 内：把 `extracted = extract_dialog(session_file.path)` 改为：

```python
    extracted = extract_dialog_for(session_file, cfg)
```

并把该函数内所有 `session_file.session_id` 作为 ledger key 的地方改为 `session_key(session_file)`。具体替换点：

- `ledger.record_skip(session_file.session_id, ...)` → `ledger.record_skip(session_key(session_file), ...)`
- `ledger.record_failure(session_file.session_id, ...)` → `ledger.record_failure(session_key(session_file), ...)`
- `ledger.record_success(session_file.session_id, ...)` → `ledger.record_success(session_key(session_file), ...)`
- `ledger.get(session_file.session_id)` → `ledger.get(session_key(session_file))`

> `SummaryResult.session_id` 字段保持裸 session_id（展示用，不变）。`project = session_file.project_dir_name` 不变。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_runner_multi_source.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 回归现有 runner 单测 + commit**

Run: `uv run pytest tests/unit/ -k "runner or auto_summary" -v`

```bash
git add jfox/auto_summary/runner.py tests/unit/test_runner_multi_source.py
git commit -m "feat(auto-summary): runner scans multiple sources, ledger keys prefixed"
```

---

## Task 8: SYSTEM_PROMPT 五段结构

**Files:**

- Modify: `jfox/auto_summary/runner.py`（`SYSTEM_PROMPT` 常量，约 38-59 行）
- Test: `tests/unit/test_system_prompt_sections.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_system_prompt_sections.py
from jfox.auto_summary.runner import SYSTEM_PROMPT


def test_system_prompt_requires_five_sections():
    for section in ["背景", "做了什么", "关键决策", "技术细节", "未决事项"]:
        assert section in SYSTEM_PROMPT, f"SYSTEM_PROMPT 缺少章节: {section}"


def test_system_prompt_no_longer_requires_only_three():
    # summary_md 现在应是五段而非三段
    assert "包含五个二级章节" in SYSTEM_PROMPT
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_system_prompt_sections.py -v`
Expected: FAIL —— 现有 SYSTEM_PROMPT 只有三个章节

- [ ] **Step 3: 实现——替换 SYSTEM_PROMPT 的 summary_md 字段说明**

在 `jfox/auto_summary/runner.py` 中，把 `SYSTEM_PROMPT` 里描述 `summary_md` 的段落替换为：

```python
   - summary_md (str): Markdown 正文，包含五个二级章节：
       ## 背景
       <本次会话的目标 / 起点状态>
       ## 做了什么
       <要点列表，每点可含 1-2 句技术细节或涉及的文件/命令>
       ## 关键决策
       <要点列表，每点含决策与理由>
       ## 技术细节
       <关键文件路径 / 代码片段 / 配置等可复用的上下文>
       ## 未决事项
       <要点列表，没有则写 "无">
     正文中文，保留足够上下文使其可独立读懂，但避免冗长。
```

> 即：把原来「三个二级章节：做了什么/关键决策/未决事项」整段替换为上述「五个二级章节」版本。其余字段（skip/reason/title/topic/tags）与强约束 1-4 不变。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_system_prompt_sections.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: commit**

```bash
git add jfox/auto_summary/runner.py tests/unit/test_system_prompt_sections.py
git commit -m "feat(auto-summary): richer 5-section summary notes (compact style)"
```

---

## Task 9: 集成测试 + CHANGELOG

**Files:**

- Create: `tests/integration/test_auto_summary_kimi.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 写集成测试（mock _invoke_claude，验证 Kimi session 端到端进 pending 并能 skip）**

```python
# tests/integration/test_auto_summary_kimi.py
"""集成测试：Kimi session 端到端走 scan_pending → summarize_one（mock claude）。

交用户运行（标记 integration）。不调用真实 claude、不加载 embedding。
"""
import json
import os
import pytest
from pathlib import Path

from jfox.auto_summary import runner
from jfox.auto_summary.ledger import Ledger
from jfox.global_config import AutoSummaryConfig


pytestmark = pytest.mark.integration


def _seed_kimi_session(root: Path, wd="wd_jfox_abc", sess="session_s1",
                      age_secs=3600, dialogue=True):
    wire = root / wd / sess / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if dialogue:
        rows += [
            {"type": "turn.prompt", "input": [{"type": "text", "text": "fix the bug"}],
             "time": 1781532844222},
            {"type": "context.append_message",
             "message": {"role": "user",
                         "content": [{"type": "text", "text": "fix the bug"}]},
             "time": 1781532844226},
            {"type": "context.append_message",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "done"}]},
             "time": 1781532845000},
        ]
    else:
        rows.append({"type": "metadata", "created_at": 1, "app_version": "0.14.3"})
    wire.write_text("\n".join(json.dumps(r) for r in rows) + "x" * 6000, encoding="utf-8")
    (wire.parent.parent.parent / "state.json").write_text(
        json.dumps({"createdAt": "2026-06-15T14:00:00Z", "updatedAt": "2026-06-15T14:30:00Z"}),
        encoding="utf-8")
    old = os.path.getmtime(wire) - age_secs
    os.utime(wire, (old, old))


def test_kimi_session_appears_in_scan(tmp_path, monkeypatch):
    _seed_kimi_session(tmp_path)
    cfg = AutoSummaryConfig(session_sources=["kimi"], kimi_sessions_dir=str(tmp_path))
    ledger = Ledger(path=tmp_path / "ledger.json")
    pending = runner.scan_pending(cfg=cfg, ledger=ledger)
    assert len(pending) == 1
    assert pending[0].source == "kimi"
    assert runner.session_key(pending[0]) == "kimi:s1"


def test_kimi_session_skip_flows_through_ledger(tmp_path, monkeypatch):
    _seed_kimi_session(tmp_path)
    cfg = AutoSummaryConfig(session_sources=["kimi"], kimi_sessions_dir=str(tmp_path))
    ledger = Ledger(path=tmp_path / "ledger.json")
    monkeypatch.setattr(runner, "_invoke_claude",
                        lambda extracted_dialog_text, cfg: '{"skip": true, "reason": "empty"}')
    report = runner.run_once(cfg=cfg, ledger=ledger)
    assert report.scanned == 1
    assert report.skipped == 1
    assert ledger.is_done("kimi:s1")
```

- [ ] **Step 2: 运行集成测试**

Run: `uv run pytest tests/integration/test_auto_summary_kimi.py -v -m integration`
Expected: PASS（2 passed）

- [ ] **Step 3: 更新 CHANGELOG.md**

在 `CHANGELOG.md` 顶部「Unreleased」或下一个版本段加入：

```markdown
### Added
- auto-summary 支持 Kimi Code session（`~/.kimi-code/sessions/`），与 Claude Code 共存；新增 `session_sources`/`kimi_sessions_dir` 配置（默认 claude+kimi 都启用，auto-detect 目录）。(#242)
- 总结笔记升级为五段结构（背景/做了什么/关键决策/技术细节/未决事项），更具上下文感。(#242)

### Changed
- auto-summary ledger 去重 key 加来源前缀（`claude:`/`kimi:`），旧数据自动迁移。
```

- [ ] **Step 4: 跑完整快速测试套件确认无回归**

Run: `uv run pytest tests/unit/ -v -m "not slow and not embedding"`
Expected: 全绿（含本计划新增的 8 个单测文件）

- [ ] **Step 5: commit**

```bash
git add tests/integration/test_auto_summary_kimi.py CHANGELOG.md
git commit -m "test+docs: integration test for kimi auto-summary + CHANGELOG (#242)"
```

---

## 收尾验证（交用户执行）

完成全部 9 个任务后，由用户运行：

```bash
# 1. 快速单测全量
uv run pytest tests/unit/ -v -m "not slow and not embedding"

# 2. 集成测试
uv run pytest tests/integration/test_auto_summary_kimi.py -v -m integration

# 3. lint / format
uv run ruff check jfox/ tests/
uv run black --check jfox/ tests/

# 4. 手动冒烟（配置启用 kimi 后 dry-run）
# 编辑 ~/.zk_config.json 的 auto_summary.session_sources 确认含 "kimi"
uv run jfox auto-summary scan --dry-run
```

确认无误后，推送分支开 PR（关 #242）。

---

## Self-Review 记录

- **Spec 覆盖**：8 节设计 → Task 1(§6 ledger) / Task 2(§3 config) / Task 3+4(§1+§2 协议/工厂/SessionFile) / Task 5(§5 扫描) / Task 6(§5 解析+§8 错误降级) / Task 7(§4 数据流) / Task 8(§7 五段) / Task 9(验收+测试)。§1 模块布局、§2 协议、§8 错误处理均有对应任务。✅
- **占位符**：无 TBD/TODO；每步含真实测试与实现代码。✅
- **类型一致**：`SessionFile.source` / `session_key()` / `extract_dialog_for()` / `get_sources()` 在 Task 4 定义、Task 7 使用，签名一致；`KimiCodeSource(kimi_dir)` 构造在 Task 4 桩与 Task 5 实现一致。✅
