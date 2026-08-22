# JFox 碎片采集（Phase 1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 CC Hook → Daemon REST API 的实时碎片采集，纠正/决策信号检测后写入 SQLite，满足 issue #261 的 Phase 1 验收。

**Architecture:** CC hook（哑 curl 脚本，<10ms）把原始事件 JSON POST 到 JFox embedding daemon 的新端点；daemon 调用纯逻辑 `detector.classify` 分类 + `store` 写 SQLite（WAL，单一写者）；`jfox fragments list/show` CLI 直读同一 SQLite。

**Tech Stack:** Python 3.10+ / FastAPI + uvicorn（现有 daemon）/ SQLite3（stdlib，首次引入应用层）/ Typer（CLI）/ bash + curl（hook）。

**关联文档:** 设计方案见 `docs/superpowers/specs/2026-06-21-fragment-capture-design.md`，issue #261。

**测试策略:** Task 1–4、6 的单测都是纯逻辑/临时 SQLite，**几秒内跑完，可自主运行**（符合 CLAUDE.md）。Task 5 的 daemon 路由是 3 行壳，逻辑由 Task 4 单测覆盖；路由本身在 Task 8 的集成 smoke test 验证（涉及真实 daemon + 模型，**用户手动跑**）。

---

## 文件结构

新增：

- `jfox/fragment/__init__.py` — 包入口，导出公开 API
- `jfox/fragment/detector.py` — 纯逻辑：事件 → (fragment_type, content)
- `jfox/fragment/store.py` — `FragmentStore`：SQLite 读写（建表/insert/query/counts）
- `jfox/fragment/service.py` — `ingest_event()` 编排：config → classify → insert → Stop 摘要
- `jfox/fragment/cli.py` — `fragments_app` Typer 子命令组（list/show）
- `packages/cc-plugin/hooks/hooks.json` — hook 注册（plugin wrapper 格式）
- `packages/cc-plugin/hooks/fragment-capture.sh` — 哑 curl 脚本
- `tests/unit/test_fragment_detector.py`
- `tests/unit/test_fragment_store.py`
- `tests/unit/test_fragment_service.py`
- `tests/unit/test_fragment_cli.py`
- `tests/integration/test_fragment_capture_flow.py` — 端到端 smoke（用户跑）

改动：

- `jfox/global_config.py` — 加 `FragmentCaptureConfig` + 挂进 `GlobalConfig` + manager 方法
- `jfox/daemon/server.py` — 加 `POST /api/fragment`、`GET /api/fragments`，lifespan 初始化 store
- `jfox/cli.py` — 挂载 `fragments_app`
- `packages/cc-plugin/.claude-plugin/plugin.json` — 加 `"hooks": "./hooks/hooks.json"`

---

## Task 0: 创建特性分支

**Files:** 无（git 操作）

- [ ] **Step 1: 从最新 main 创建分支**

```bash
cd /home/elling/git-repo/github/jfox
git checkout main && git pull
git checkout -b feat/261-fragment-capture
```

- [ ] **Step 2: 确认当前分支**

Run: `git branch --show-current`
Expected: `feat/261-fragment-capture`

---

## Task 1: FragmentCaptureConfig 配置

依赖：无（叶子配置，detector/service 会用它）。

**Files:**

- Modify: `jfox/global_config.py`（在 `AutoSummaryConfig` 之后、`GlobalConfig` 之前插入新 dataclass；改 `GlobalConfig` 三处）
- Test: `tests/unit/test_fragment_config.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_fragment_config.py`**

```python
"""验证 FragmentCaptureConfig 默认值与可配置关键词。"""

from jfox.global_config import FragmentCaptureConfig


def test_defaults():
    cfg = FragmentCaptureConfig()
    assert cfg.enabled is True
    assert "不对" in cfg.correction_keywords
    assert "我决定" in cfg.decision_keywords
    assert cfg.max_content_chars == 500


def test_from_dict_empty_uses_defaults():
    cfg = FragmentCaptureConfig.from_dict({})
    assert cfg.enabled is True
    assert "错了" in cfg.correction_keywords


def test_from_dict_explicit_keywords():
    cfg = FragmentCaptureConfig.from_dict(
        {"correction_keywords": ["错啦"], "decision_keywords": ["就这么定"]}
    )
    assert cfg.correction_keywords == ["错啦"]
    assert cfg.decision_keywords == ["就这么定"]


def test_from_dict_disable():
    cfg = FragmentCaptureConfig.from_dict({"enabled": False})
    assert cfg.enabled is False


def test_to_dict_roundtrip():
    cfg = FragmentCaptureConfig(correction_keywords=["x"])
    d = cfg.to_dict()
    assert d["correction_keywords"] == ["x"]
    assert FragmentCaptureConfig.from_dict(d).correction_keywords == ["x"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_fragment_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'FragmentCaptureConfig'`

- [ ] **Step 3: 在 `jfox/global_config.py` 加 dataclass**

在 `AutoSummaryConfig.from_dict`（约第 112 行）之后、`@dataclass class GlobalConfig`（约第 115 行）之前插入：

```python
@dataclass
class FragmentCaptureConfig:
    """Claude Code Hook 碎片采集配置（默认启用）"""

    enabled: bool = True
    # 纠正信号关键词（命中 → fragment_type=correction）
    correction_keywords: List[str] = field(
        default_factory=lambda: [
            "不对", "错了", "应该", "不要", "等等", "停", "不是", "别", "换一种", "反过来",
        ]
    )
    # 决策信号关键词（命中 → fragment_type=decision）
    decision_keywords: List[str] = field(
        default_factory=lambda: ["用方案", "选", "因为", "理由是", "我决定", "就这样", "先不做"]
    )
    # content 字段截断长度
    max_content_chars: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FragmentCaptureConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            correction_keywords=(
                list(data["correction_keywords"])
                if isinstance(data.get("correction_keywords"), list)
                else cls().correction_keywords
            ),
            decision_keywords=(
                list(data["decision_keywords"])
                if isinstance(data.get("decision_keywords"), list)
                else cls().decision_keywords
            ),
            max_content_chars=int(data.get("max_content_chars", 500)),
        )
```

- [ ] **Step 4: 把 fragment_capture 挂进 `GlobalConfig`**

改 `GlobalConfig`（约 115–140 行）三处：

```python
@dataclass
class GlobalConfig:
    """全局配置"""

    default: str = DEFAULT_KB_NAME
    knowledge_bases: Dict[str, KnowledgeBaseEntry] = field(default_factory=dict)
    auto_summary: AutoSummaryConfig = field(default_factory=AutoSummaryConfig)
    fragment_capture: FragmentCaptureConfig = field(default_factory=FragmentCaptureConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default": self.default,
            "knowledge_bases": {name: kb.to_dict() for name, kb in self.knowledge_bases.items()},
            "auto_summary": self.auto_summary.to_dict(),
            "fragment_capture": self.fragment_capture.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalConfig":
        kbs = {}
        for name, kb_data in data.get("knowledge_bases", {}).items():
            kbs[name] = KnowledgeBaseEntry.from_dict(name, kb_data)

        return cls(
            default=data.get("default", DEFAULT_KB_NAME),
            knowledge_bases=kbs,
            auto_summary=AutoSummaryConfig.from_dict(data.get("auto_summary")),
            fragment_capture=FragmentCaptureConfig.from_dict(data.get("fragment_capture")),
        )
```

- [ ] **Step 5: 在 `GlobalConfigManager` 加 get/update 方法**

在 `update_auto_summary_config`（约第 428 行）之后插入：

```python
    def get_fragment_capture_config(self) -> FragmentCaptureConfig:
        """获取碎片采集配置"""
        return self._load().fragment_capture

    def update_fragment_capture_config(self, **changes: Any) -> bool:
        """更新碎片采集配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.fragment_capture)
        current.update({k: v for k, v in changes.items() if k in current})
        config.fragment_capture = FragmentCaptureConfig.from_dict(current)
        self._config = config
        return self._save()
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_fragment_config.py -v`
Expected: PASS（5 个测试全过）

- [ ] **Step 7: 回归 global_config 既有测试**

Run: `uv run pytest tests/unit/test_global_config.py tests/unit/test_auto_summary_defaults.py -v`
Expected: PASS（确认没破坏既有配置）

- [ ] **Step 8: 提交**

```bash
git add jfox/global_config.py tests/unit/test_fragment_config.py
git commit -m "feat(fragment): add FragmentCaptureConfig to global config

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: detector.py — 事件分类（纯逻辑）

依赖：Task 1（`FragmentCaptureConfig` 提供关键词）。

**Files:**

- Create: `jfox/fragment/detector.py`
- Test: `tests/unit/test_fragment_detector.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_fragment_detector.py`**

```python
"""detector.classify 纯逻辑测试（无 I/O）。"""

from jfox.fragment.detector import classify
from jfox.global_config import FragmentCaptureConfig


def test_userprompt_correction():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": "不对，应该用 patch"}, cfg)
    assert ftype == "correction"
    assert content == "不对，应该用 patch"


def test_userprompt_decision():
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "UserPromptSubmit", "prompt": "我决定用方案 A"}, cfg)
    assert ftype == "decision"


def test_correction_takes_priority_over_decision():
    """同时命中时纠正优先（被纠正的信号更强）"""
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "UserPromptSubmit", "prompt": "不对，我决定换一种"}, cfg)
    assert ftype == "correction"


def test_userprompt_plain_input():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": "帮我写个函数"}, cfg)
    assert ftype == "user_input"
    assert content == "帮我写个函数"


def test_posttooluse_tool_call():
    cfg = FragmentCaptureConfig()
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_response": {"stdout": "done", "exit_code": 0},
    }
    ftype, content = classify(event, cfg)
    assert ftype == "tool_call"
    assert "done" in content


def test_content_truncated_to_max():
    cfg = FragmentCaptureConfig(max_content_chars=10)
    long_prompt = "x" * 100
    _, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": long_prompt}, cfg)
    assert len(content) == 10


def test_stop_returns_summary_type():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "Stop"}, cfg)
    assert ftype == "session_summary"
    assert content is None


def test_unknown_event_fallback():
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "Whatever"}, cfg)
    assert ftype == "user_input"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_fragment_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: jfox.fragment`

- [ ] **Step 3: 创建 `jfox/fragment/detector.py`**

```python
"""碎片检测器：根据 CC 事件推断 fragment_type 与 content（纯逻辑，无 I/O）。"""

import json
from typing import Any, Optional, Tuple

from ..global_config import FragmentCaptureConfig


def classify(event: dict, config: FragmentCaptureConfig) -> Tuple[str, Optional[str]]:
    """根据事件推断 (fragment_type, content)。

    - UserPromptSubmit: 命中纠正词→correction（优先），命中决策词→decision，否则 user_input
    - PostToolUse:      tool_call，content=tool_response 序列化后截断
    - Stop:             session_summary，content 留空（由 service 填本轮汇总）
    - 其它:             user_input 兜底
    """
    name = event.get("hook_event_name")
    limit = config.max_content_chars

    if name == "PostToolUse":
        resp = event.get("tool_response", event.get("tool_input", ""))
        text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
        return "tool_call", text[:limit]

    if name == "UserPromptSubmit":
        prompt = event.get("prompt", "") or ""
        if any(k in prompt for k in config.correction_keywords):
            ftype = "correction"
        elif any(k in prompt for k in config.decision_keywords):
            ftype = "decision"
        else:
            ftype = "user_input"
        return ftype, prompt[:limit]

    if name == "Stop":
        return "session_summary", None

    return "user_input", None


__all__ = ["classify"]
```

- [ ] **Step 4: 创建空 `jfox/fragment/__init__.py`**

```python
"""JFox 碎片采集子包（Phase 1：Hook → Daemon REST API）。"""

from .detector import classify

__all__ = ["classify"]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_fragment_detector.py -v`
Expected: PASS（8 个测试全过）

- [ ] **Step 6: 提交**

```bash
git add jfox/fragment/__init__.py jfox/fragment/detector.py tests/unit/test_fragment_detector.py
git commit -m "feat(fragment): add event classifier (pure logic)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: store.py — FragmentStore（SQLite CRUD）

依赖：无（独立存储层）。

**Files:**

- Create: `jfox/fragment/store.py`
- Test: `tests/unit/test_fragment_store.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_fragment_store.py`**

```python
"""FragmentStore SQLite 测试（用临时文件，无 daemon/模型依赖）。"""

import json

from jfox.fragment.store import FragmentStore


def _store(tmp_path):
    return FragmentStore(db_path=tmp_path / "fragments.db")


def test_insert_and_get(tmp_path):
    store = _store(tmp_path)
    fid = store.insert(
        session_id="s1",
        fragment_type="correction",
        source_event="UserPromptSubmit",
        content="不对",
        metadata={"hook_event_name": "UserPromptSubmit", "prompt": "不对"},
    )
    assert isinstance(fid, int) and fid >= 1
    row = store.get(fid)
    assert row["session_id"] == "s1"
    assert row["fragment_type"] == "correction"
    assert json.loads(row["metadata_json"])["prompt"] == "不对"


def test_query_by_session_and_type(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.insert("s2", "correction", "UserPromptSubmit", "错了", {})

    rows = store.query(session_id="s1")
    assert len(rows) == 2

    rows = store.query(session_id="s1", fragment_type="tool_call")
    assert len(rows) == 1 and rows[0]["fragment_type"] == "tool_call"


def test_query_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.insert("s1", "user_input", "UserPromptSubmit", f"m{i}", {})
    rows = store.query(session_id="s1", limit=2)
    assert len(rows) == 2


def test_counts_by_type(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "correction", "UserPromptSubmit", "错了", {})
    store.insert("s1", "tool_call", "PostToolUse", "x", {})
    counts = store.counts_by_type("s1")
    assert counts == {"correction": 2, "tool_call": 1}


def test_counts_excludes_other_session(tmp_path):
    store = _store(tmp_path)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s2", "correction", "UserPromptSubmit", "错了", {})
    assert store.counts_by_type("s1") == {"correction": 1}


def test_default_db_path_respects_env(tmp_path, monkeypatch):
    """默认路径读 JFOX_FRAGMENTS_DB 环境变量（CLI 集成测试用）"""
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "env.db"))
    store = FragmentStore()
    store.insert("s1", "user_input", "UserPromptSubmit", "hi", {})
    assert (tmp_path / "env.db").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_fragment_store.py -v`
Expected: FAIL — `ModuleNotFoundError: jfox.fragment.store`

- [ ] **Step 3: 创建 `jfox/fragment/store.py`**

```python
"""碎片存储层：SQLite（WAL 模式，daemon 单一写者，CLI 多读者并发安全）。

落盘默认 ~/.zettelkasten/fragments.db；可用 JFOX_FRAGMENTS_DB 环境变量覆盖（测试/自定义用）。
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_fragments (
    fragment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    fragment_type   TEXT NOT NULL,
    source_event    TEXT NOT NULL,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content         TEXT,
    metadata_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_frag_session ON session_fragments(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_frag_type    ON session_fragments(fragment_type, timestamp);
"""


def default_db_path() -> Path:
    """默认碎片库路径，可被 JFOX_FRAGMENTS_DB 覆盖。"""
    env = os.environ.get("JFOX_FRAGMENTS_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zettelkasten" / "fragments.db"


class FragmentStore:
    """SQLite 碎片存储。daemon 持有一个常驻实例（热连接）；测试传入临时路径。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 同一进程内多线程读写的锁（sqlite3 连接默认 check_same_thread=True）
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert(
        self,
        session_id: str,
        fragment_type: str,
        source_event: str,
        content: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO session_fragments "
                "(session_id, fragment_type, source_event, content, metadata_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    fragment_type,
                    source_event,
                    content,
                    json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get(self, fragment_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session_fragments WHERE fragment_id = ?", (fragment_id,)
            ).fetchone()
        return dict(row) if row else None

    def query(
        self,
        session_id: Optional[str] = None,
        fragment_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM session_fragments WHERE 1=1"
        params: List[Any] = []
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        if fragment_type is not None:
            sql += " AND fragment_type = ?"
            params.append(fragment_type)
        sql += " ORDER BY timestamp DESC, fragment_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def counts_by_type(self, session_id: str) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT fragment_type, COUNT(*) AS n FROM session_fragments "
                "WHERE session_id = ? GROUP BY fragment_type",
                (session_id,),
            ).fetchall()
        return {r["fragment_type"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["FragmentStore", "default_db_path"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_fragment_store.py -v`
Expected: PASS（6 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add jfox/fragment/store.py tests/unit/test_fragment_store.py
git commit -m "feat(fragment): add FragmentStore (SQLite, WAL)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: service.py — ingest_event 编排

依赖：Task 1（config）、Task 2（detector）、Task 3（store）。

**Files:**

- Create: `jfox/fragment/service.py`
- Test: `tests/unit/test_fragment_service.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_fragment_service.py`**

```python
"""service.ingest_event 编排测试（临时 store，无 daemon/模型）。"""

from jfox.fragment.service import ingest_event
from jfox.fragment.store import FragmentStore
from jfox.global_config import FragmentCaptureConfig


def test_userprompt_correction_inserted(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "不对，应该改"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "correction"
    assert isinstance(result["fragment_id"], int)
    assert store.get(result["fragment_id"])["fragment_type"] == "correction"


def test_posttooluse_inserted(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_response": {"stdout": "ok"},
        },
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "tool_call"


def test_stop_writes_summary_and_message(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    # 先攒两条碎片
    ingest_event({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "不对"}, store=store, config=FragmentCaptureConfig())
    ingest_event({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_response": "x"}, store=store, config=FragmentCaptureConfig())
    # 触发 Stop
    result = ingest_event(
        {"hook_event_name": "Stop", "session_id": "s1"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["fragment_type"] == "session_summary"
    assert "纠正" in result["message"]
    assert "工具" in result["message"]
    # session_summary 行也入库
    summaries = store.query(session_id="s1", fragment_type="session_summary")
    assert len(summaries) == 1


def test_disabled_config_returns_skip(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"},
        store=store,
        config=FragmentCaptureConfig(enabled=False),
    )
    assert result["status"] == "skipped"
    assert store.query(session_id="s1") == []


def test_missing_session_id(tmp_path):
    store = FragmentStore(db_path=tmp_path / "f.db")
    result = ingest_event(
        {"hook_event_name": "UserPromptSubmit", "prompt": "hi"},
        store=store,
        config=FragmentCaptureConfig(),
    )
    assert result["status"] == "error"
    assert "session_id" in result["message"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_fragment_service.py -v`
Expected: FAIL — `ModuleNotFoundError: jfox.fragment.service`

- [ ] **Step 3: 创建 `jfox/fragment/service.py`**

```python
"""碎片摄入编排：event → classify → store.insert，Stop 时生成本轮摘要。

纯函数式（依赖注入 store/config），daemon 路由与单测都直接调用，不加载 embedding 模型。
"""

from typing import Any, Dict, Optional

from ..global_config import FragmentCaptureConfig, get_global_config_manager
from .detector import classify
from .store import FragmentStore

# daemon 常驻的 store 单例（lifespan 初始化时设置）
_default_store: Optional[FragmentStore] = None


def set_default_store(store: Optional[FragmentStore]) -> None:
    """daemon lifespan 启动/关闭时调用，注入或清空常驻 store。"""
    global _default_store
    _default_store = store


def _summary_message(counts: Dict[str, int]) -> str:
    total = sum(counts.values())
    parts = []
    label_map = {"correction": "纠正", "decision": "决策", "tool_call": "工具", "user_input": "输入"}
    for k in ("correction", "decision", "tool_call", "user_input"):
        if counts.get(k):
            parts.append(f"{label_map[k]} {counts[k]}")
    detail = " / ".join(parts) if parts else "无"
    return f"本轮采集 {total} 碎片：{detail}"


def ingest_event(
    event: Dict[str, Any],
    store: Optional[FragmentStore] = None,
    config: Optional[FragmentCaptureConfig] = None,
) -> Dict[str, Any]:
    """处理一个 CC 事件，写入碎片，返回响应 dict。

    返回形如：
      {fragment_id, fragment_type, message}            正常写入
      {status: "skipped"}                              配置禁用
      {status: "error", message}                       输入异常（如缺 session_id）
    """
    if config is None:
        config = get_global_config_manager().get_fragment_capture_config()
    if not config.enabled:
        return {"status": "skipped"}

    session_id = event.get("session_id")
    if not session_id:
        return {"status": "error", "message": "missing session_id in event"}

    if store is None:
        if _default_store is None:
            set_default_store(FragmentStore())
        store = _default_store  # type: ignore[assignment]

    ftype, content = classify(event, config)

    if ftype == "session_summary":
        counts = store.counts_by_type(session_id)
        content = _summary_message(counts)

    fid = store.insert(
        session_id=session_id,
        fragment_type=ftype,
        source_event=event.get("hook_event_name", "Unknown"),
        content=content,
        metadata=event,
    )
    message = content if ftype == "session_summary" else "ok"
    return {"fragment_id": fid, "fragment_type": ftype, "message": message}


__all__ = ["ingest_event", "set_default_store"]
```

- [ ] **Step 4: 在 `jfox/fragment/__init__.py` 导出 service**

把 `__init__.py` 更新为：

```python
"""JFox 碎片采集子包（Phase 1：Hook → Daemon REST API）。"""

from .detector import classify
from .service import ingest_event, set_default_store
from .store import FragmentStore

__all__ = ["classify", "ingest_event", "set_default_store", "FragmentStore"]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_fragment_service.py tests/unit/test_fragment_detector.py tests/unit/test_fragment_store.py -v`
Expected: PASS（service 5 个 + detector 8 个 + store 6 个全过）

- [ ] **Step 6: 提交**

```bash
git add jfox/fragment/service.py jfox/fragment/__init__.py tests/unit/test_fragment_service.py
git commit -m "feat(fragment): add ingest_event orchestration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: daemon 端点 + lifespan 初始化 store

依赖：Task 3（store）、Task 4（service）。

**Files:**

- Modify: `jfox/daemon/server.py`（lifespan 加 store 初始化；加两个端点）

说明：端点是 3 行壳，逻辑由 Task 4 单测覆盖；端点本身在 Task 8 集成验证（**用户手动跑**）。

- [ ] **Step 1: 改 `lifespan`，启动时初始化 store、关闭时释放**

定位 `jfox/daemon/server.py` 的 `lifespan` 函数（约 102–109 行），改为：

```python
@asynccontextmanager
async def lifespan(app):
    _load_model()
    _maybe_start_auto_summary()
    _maybe_init_fragment_store()
    try:
        yield
    finally:
        await _maybe_stop_auto_summary()
        _maybe_close_fragment_store()
```

- [ ] **Step 2: 加 store 初始化/关闭的辅助函数**

在 `_maybe_start_auto_summary` 之前（约第 52 行前）插入：

```python
def _maybe_init_fragment_store() -> None:
    """daemon 启动时打开常驻 FragmentStore（热连接，单一写者）"""
    try:
        from .fragment import set_default_store
        from .fragment.store import FragmentStore

        set_default_store(FragmentStore())
        logger.info("Daemon: FragmentStore 已初始化")
    except Exception as e:
        logger.exception("Daemon: 初始化 FragmentStore 失败（碎片采集不可用）: %s", e)
        from .fragment import set_default_store
        set_default_store(None)


def _maybe_close_fragment_store() -> None:
    """daemon 关闭时释放 store 连接"""
    try:
        from .fragment import set_default_store
        from .fragment.service import _default_store

        if _default_store is not None:
            _default_store.close()
        set_default_store(None)
    except Exception as e:
        logger.warning("Daemon: 关闭 FragmentStore 时异常: %s", e)
```

- [ ] **Step 3: 加 POST /api/fragment 与 GET /api/fragments 端点**

在 `auto_summary_status` 端点之后（约第 219 行后）插入：

```python
# =============================================================================
# 碎片采集（Phase 1：Hook → Daemon REST API）
# =============================================================================


@app.post("/api/fragment")
def capture_fragment(event: dict):
    """接收 CC hook POST 的原始事件 JSON，分类后写入 SQLite。

    请求体即 CC 事件的 stdin JSON（UserPromptSubmit / PostToolUse / Stop）。
    """
    from ..fragment import ingest_event

    return ingest_event(event)


@app.get("/api/fragments")
def list_fragments(
    session: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 20,
):
    """按 session / type 查询碎片（最新在前）。"""
    from ..fragment.store import FragmentStore

    store = FragmentStore()
    try:
        rows = store.query(session_id=session, fragment_type=type, limit=limit)
    finally:
        store.close()
    return {"fragments": rows, "total": len(rows)}
```

- [ ] **Step 4: 验证语法/import 无误（不启动 daemon，不加载模型）**

Run: `uv run python -c "import jfox.daemon.server as s; print([r.path for r in s.app.routes if hasattr(r,'path') and '/api/fragment' in r.path])"`
Expected: 打印 `['/api/fragment', '/api/fragments']`（确认两个路由已注册、模块可 import）

- [ ] **Step 5: 提交**

```bash
git add jfox/daemon/server.py
git commit -m "feat(daemon): add /api/fragment capture + /api/fragments query endpoints

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: jfox fragments CLI 子命令组

依赖：Task 3（store）。

**Files:**

- Create: `jfox/fragment/cli.py`
- Modify: `jfox/cli.py`（挂载子命令组，约第 102/104 行附近）
- Test: `tests/unit/test_fragment_cli.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_fragment_cli.py`**

```python
"""jfox fragments list/show CLI 测试（临时 DB，无 daemon/模型）。"""

import json

from typer.testing import CliRunner

from jfox.fragment.cli import fragments_app
from jfox.fragment.store import FragmentStore


def _seed(tmp_path):
    monkey_db = tmp_path / "f.db"
    store = FragmentStore(db_path=monkey_db)
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {"prompt": "不对"})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.close()
    return monkey_db


def test_list_table(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["list", "--session", "s1"])
    assert result.exit_code == 0
    assert "correction" in result.stdout
    assert "tool_call" in result.stdout


def test_list_json(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["list", "--session", "s1", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 2


def test_list_filter_type(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(
        fragments_app, ["list", "--session", "s1", "--type", "tool_call", "--format", "json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 1 and data["fragments"][0]["fragment_type"] == "tool_call"


def test_show_detail(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    store = FragmentStore(db_path=db)
    fid = store.query(session_id="s1", fragment_type="correction")[0]["fragment_id"]
    store.close()
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(db))
    result = CliRunner().invoke(fragments_app, ["show", str(fid)])
    assert result.exit_code == 0
    assert "不对" in result.stdout
    assert "prompt" in result.stdout  # metadata 展开了
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_fragment_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: jfox.fragment.cli`

- [ ] **Step 3: 创建 `jfox/fragment/cli.py`**

```python
"""CLI 子命令组：jfox fragments list / show"""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .store import FragmentStore

console = Console(legacy_windows=False)

fragments_app = typer.Typer(
    name="fragments",
    help="查看 Hook 采集的 session 碎片（纠正/决策/工具调用）",
    no_args_is_help=True,
)


@fragments_app.command("list")
def list_cmd(
    session: Optional[str] = typer.Option(None, "--session", help="按 CC session_id 过滤"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="按 fragment_type 过滤"),
    limit: int = typer.Option(20, "--limit", "-n", help="返回条数"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """列出碎片（最新在前）"""
    store = FragmentStore()
    try:
        rows = store.query(session_id=session, fragment_type=type, limit=limit)
    finally:
        store.close()

    if output_format == "json":
        console.print(_json.dumps({"fragments": rows, "total": len(rows)}, ensure_ascii=False, indent=2))
        return

    table = Table(title=f"碎片（共 {len(rows)} 条）")
    for col in ("ID", "时间", "类型", "来源事件", "内容预览"):
        table.add_column(col)
    for r in rows:
        preview = (r.get("content") or "")[:40].replace("\n", " ")
        table.add_row(
            str(r["fragment_id"]),
            str(r.get("timestamp", "")),
            r["fragment_type"],
            r.get("source_event", ""),
            preview,
        )
    console.print(table)


@fragments_app.command("show")
def show_cmd(
    fragment_id: int = typer.Argument(..., help="碎片 ID"),
) -> None:
    """查看碎片详情（含完整原始事件）"""
    store = FragmentStore()
    try:
        row = store.get(fragment_id)
    finally:
        store.close()
    if row is None:
        console.print(f"[red]找不到碎片 ID={fragment_id}[/red]")
        raise typer.Exit(code=1)
    console.print(_json.dumps(row, ensure_ascii=False, indent=2))


__all__ = ["fragments_app"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_fragment_cli.py -v`
Expected: PASS（4 个测试全过）

- [ ] **Step 5: 在 `jfox/cli.py` 挂载 fragments_app**

在 `auto_summary_app` 的 import/add_typer 旁边（约第 102–104 行）加两行：

```python
from .fragment.cli import fragments_app  # noqa: E402
```

以及紧跟 `app.add_typer(auto_summary_app, name="auto-summary")`（约第 104 行）之后：

```python
app.add_typer(fragments_app, name="fragments", help="查看 Hook 采集的 session 碎片")
```

- [ ] **Step 6: 验证 CLI 挂载成功**

Run: `uv run jfox fragments --help`
Expected: 打印 help，含 `list` 和 `show` 两个子命令

- [ ] **Step 7: 提交**

```bash
git add jfox/fragment/cli.py jfox/cli.py tests/unit/test_fragment_cli.py
git commit -m "feat(cli): add 'jfox fragments list/show' subcommand group

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: CC Plugin hook（hooks.json + 脚本 + plugin.json）

依赖：Task 5（daemon 端点就绪）。

**Files:**

- Create: `packages/cc-plugin/hooks/hooks.json`
- Create: `packages/cc-plugin/hooks/fragment-capture.sh`
- Modify: `packages/cc-plugin/.claude-plugin/plugin.json`

- [ ] **Step 1: 创建 `packages/cc-plugin/hooks/hooks.json`**

```json
{
  "description": "JFox 碎片采集 - 实时捕获 session 纠正/决策信号，POST 到 JFox daemon",
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: 创建 `packages/cc-plugin/hooks/fragment-capture.sh`**

```bash
#!/usr/bin/env bash
# JFox 碎片采集 hook：读 CC stdin JSON，原样 POST 到 JFox daemon。
# 设计：永不阻塞 CC（失败静默 exit 0）；不 spawn Python（curl <10ms，满足 100ms 预算）。
set -u

PAYLOAD="$(cat)"

# POST 原样给 daemon；-m1 限时1秒，-s 静默，失败不报错
RESP="$(printf '%s' "$PAYLOAD" | curl -s -m 1 -X POST \
    http://127.0.0.1:18700/api/fragment \
    -H 'Content-Type: application/json' \
    --data-binary @- 2>/dev/null || true)"

# Stop 事件：打印 daemon 返回的一行采集摘要
case "$PAYLOAD" in
  *'"hook_event_name":"Stop"'*)
    MSG="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("message",""))' 2>/dev/null || true)"
    [ -n "$MSG" ] && echo "JFox 碎片采集: $MSG"
    ;;
esac

exit 0
```

- [ ] **Step 3: 给脚本加可执行权限**

Run: `chmod +x packages/cc-plugin/hooks/fragment-capture.sh`
Expected: 无输出

- [ ] **Step 4: 改 `packages/cc-plugin/.claude-plugin/plugin.json` 注册 hooks**

把 plugin.json 改为（加最后一行 `"hooks"`）：

```json
{
  "name": "jfox",
  "description": "JFox 知识管理 CLI 的 Claude Code 集成——搜索、写入工作流（导入/整理/会话总结）与知识库管理",
  "version": "0.2.0",
  "author": { "name": "zhuxixi" },
  "homepage": "https://github.com/zhuxixi/jfox",
  "repository": "https://github.com/zhuxixi/jfox",
  "license": "MIT",
  "keywords": ["zettelkasten", "knowledge-management", "cli"],
  "hooks": "./hooks/hooks.json"
}
```

- [ ] **Step 5: 校验 JSON 合法 + 脚本 bash 语法**

Run:

```bash
python3 -c "import json; json.load(open('packages/cc-plugin/hooks/hooks.json')); json.load(open('packages/cc-plugin/.claude-plugin/plugin.json')); print('json ok')"
bash -n packages/cc-plugin/hooks/fragment-capture.sh && echo "bash syntax ok"
```

Expected: `json ok` 和 `bash syntax ok`

- [ ] **Step 6: 提交**

```bash
git add packages/cc-plugin/hooks/ packages/cc-plugin/.claude-plugin/plugin.json
git commit -m "feat(cc-plugin): add fragment-capture hook (curl → daemon)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 端到端集成 smoke test（用户手动跑）

依赖：Task 5、7。涉及真实 daemon + 模型加载，**按 CLAUDE.md 由用户手动执行**。

**Files:**

- Create: `tests/integration/test_fragment_capture_flow.py`

- [ ] **Step 1: 写集成测试 `tests/integration/test_fragment_capture_flow.py`**

```python
"""端到端：hook 脚本 → daemon → SQLite。

标记 integration：依赖真实运行的 daemon（jfox daemon start）。
用户手动跑：uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration
"""

import json
import os
import subprocess
import urllib.request

import pytest

pytestmark = pytest.mark.integration

DAEMON = "http://127.0.0.1:18700"
HOOK = "packages/cc-plugin/hooks/fragment-capture.sh"


def _daemon_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DAEMON}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def require_daemon():
    if not _daemon_up():
        pytest.skip("JFox daemon 未运行；先 `jfox daemon start`（需要用户手动启动，会加载模型）")


def test_post_userprompt_correction():
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "it-sess-1", "prompt": "不对，应该用 patch"}
    ).encode()
    req = urllib.request.Request(f"{DAEMON}/api/fragment", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    assert body["fragment_type"] == "correction"


def test_hook_script_end_to_end(tmp_path, monkeypatch):
    """模拟 CC 调用 hook 脚本，验证碎片落到 SQLite"""
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(tmp_path / "fragments.db"))
    # 注意：hook 直接 POST daemon，daemon 用默认路径写入，故这里只验证 POST 成功；
    # 碎片落盘验证在 test_query_fragments 里通过 daemon 查询。
    payload = json.dumps(
        {"hook_event_name": "PostToolUse", "session_id": "it-sess-2", "tool_response": {"stdout": "hi"}}
    )
    proc = subprocess.run(
        ["bash", HOOK], input=payload, capture_output=True, text=True, timeout=5
    )
    assert proc.returncode == 0
    # 查 daemon
    with urllib.request.urlopen(f"{DAEMON}/api/fragments?session=it-sess-2", timeout=5) as r:
        body = json.loads(r.read())
    assert body["total"] >= 1
    assert body["fragments"][0]["fragment_type"] == "tool_call"


def test_stop_returns_summary_message():
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "it-sess-2"}).encode()
    req = urllib.request.Request(f"{DAEMON}/api/fragment", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    assert body["fragment_type"] == "session_summary"
    assert "碎片" in body["message"]
```

- [ ] **Step 2: 提交（测试本身）**

```bash
git add tests/integration/test_fragment_capture_flow.py
git commit -m "test(fragment): add end-to-end capture flow (integration, user-run)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 3: 给用户的手动验收清单**

不在本任务自动执行。把下面这段贴给用户跑：

```bash
# 1. 确认 daemon 在跑（cuda/bge-m3）
uv run jfox daemon status

# 2. 跑集成 smoke
uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration

# 3.（可选）真实 CC 验证：装好插件后，在 CC 里发一句"不对，应该..."
#    然后看：uv run jfox fragments list --limit 5
```

Expected（用户反馈）: 3 个集成测试通过；`jfox fragments list` 能看到刚采集的碎片。

---

## Task 9: 收尾 — 回归 + 文档

依赖：Task 1–7 全部完成。

- [ ] **Step 1: 跑全部碎片相关单测**

Run: `uv run pytest tests/unit/test_fragment_config.py tests/unit/test_fragment_detector.py tests/unit/test_fragment_store.py tests/unit/test_fragment_service.py tests/unit/test_fragment_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 跑 fast 套件回归（不含 embedding/slow，用户跑或自主跑均可，约数十秒）**

Run: `uv run pytest tests/unit/ -v`
Expected: PASS（确认没破坏既有单测）

- [ ] **Step 3: lint/format**

Run:

```bash
uv run black jfox/fragment/ jfox/daemon/server.py jfox/global_config.py jfox/cli.py tests/unit/test_fragment_*.py tests/integration/test_fragment_capture_flow.py
uv run ruff check jfox/fragment/ jfox/daemon/server.py jfox/global_config.py jfox/cli.py tests/unit/test_fragment_*.py tests/integration/test_fragment_capture_flow.py
```

Expected: black 无改动 / ruff 无报错

- [ ] **Step 4: 更新 CLAUDE.md 模块表（可选但推荐）**

在 `CLAUDE.md` 的「Key Module Map」加一行：

```markdown
| `fragment/` | 碎片采集（Phase 1）：detector 分类 + store SQLite + service 编排；daemon `/api/fragment` |
```

- [ ] **Step 5: 推送分支并开 PR**

```bash
git push -u origin feat/261-fragment-capture
gh pr create --title "feat: Claude Code Hook 碎片采集（#261 Phase 1）" \
  --body "实现 issue #261 Phase 1：CC hook（哑 curl）→ daemon REST API → SQLite。设计见 docs/superpowers/specs/2026-06-21-fragment-capture-design.md，实现计划见 docs/superpowers/plans/2026-06-21-fragment-capture.md。Closes #261。"
```

Expected: PR 创建成功

---

## Self-Review 结果

**1. Spec 覆盖**（对照设计 spec §2 模块表）：

- `FragmentCaptureConfig` → Task 1 ✅
- `detector.py`（classify）→ Task 2 ✅
- `store.py`（FragmentStore）→ Task 3 ✅
- `service.py`（ingest_event，spec 新增的编排文件）→ Task 4 ✅
- daemon `POST/GET` 端点 + lifespan init → Task 5 ✅
- `jfox fragments list/show` → Task 6 ✅
- `hooks.json` + `fragment-capture.sh` + `plugin.json` → Task 7 ✅
- 验收 6 项 → §8 映射表全部覆盖（Task 8 验证）✅
- spec §9 三处偏离（检测服务端 / curl 非 CLI / 首引 SQLite）→ 实现均已落实 ✅

**2. 占位符扫描**：无 TBD/TODO；每步都有完整代码与命令。

**3. 类型/签名一致性**：

- `classify(event, config) -> (str, Optional[str])` Task2 定义，Task4 `ingest_event` 调用一致 ✅
- `FragmentStore(db_path=None)` + `insert(session_id, fragment_type, source_event, content, metadata)` / `get(fid)` / `query(session_id, fragment_type, limit)` / `counts_by_type(session_id)` —— Task3 定义，Task4/5/6 调用参数名一致 ✅
- `ingest_event(event, store=None, config=None) -> dict` + `set_default_store(store)` —— Task4 定义，Task5 端点调用一致 ✅
- `fragments_app`（Task6）→ `cli.py add_typer(fragments_app, name="fragments")` 一致 ✅

**4. 测试分级**：Task 1–4、6 纯逻辑/临时 SQLite 单测（自主跑，秒级）；Task 8 集成（用户跑，需 daemon+模型）—— 符合 CLAUDE.md 测试规则 ✅
