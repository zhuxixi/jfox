# L3 宝石合成（碎裂→破损）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 围绕 session 内高信号锚点，把采集的碎裂碎片 + transcript 上下文 + 永久笔记基准，合成出破损级 `candidate` 笔记（daemon 异步循环驱动）。

**Architecture:** daemon 后台循环（仿 auto_summary）定期扫 `fragments.db` 未处理锚点 → 取 transcript 该轮上下文 → hybrid 检索 permanent 笔记 top-5 → 独立 LLM 调用合成 → 写 `candidate` 笔记 + `synthesis_log` 记账。全程异步，不碰 hook 热路径。

**Tech Stack:** Python 3.10+ / SQLite3（synthesis_log）/ Typer（CLI）/ subprocess（claude -p，独立于 auto_summary）/ 现有 HybridSearchEngine + Note 模型。

**关联文档:** spec 见 `docs/superpowers/specs/2026-06-21-gem-synthesis-design.md`，父 issue #249 Layer 3。

**测试策略:** Phase A-D 的纯逻辑/IO 单测自主跑（秒级，无 LLM/模型）；Phase E（LLM 合成）+ Phase F daemon 装配 + Phase G 的端到端为集成测试，**用户手动跑**（需 daemon + claude 二进制）。符合 CLAUDE.md。

**分阶段（每阶段可独立 merge）：**
- **Phase A** 笔记基础设施（GemLevel + NoteType.candidate + Note 字段 + 存储）
- **Phase B** 合成存储层（synthesis_log 表 + 锚点查询）
- **Phase C** transcript 解析器
- **Phase D** 永久笔记检索
- **Phase E** LLM 合成器
- **Phase F** daemon 循环 + 配置 + 装配
- **Phase G** candidates CLI

---

## 文件结构

新增：
- `jfox/gem_synth/__init__.py`
- `jfox/gem_synth/store.py` — synthesis_log SQLite（建表/记账/查未处理锚点）
- `jfox/gem_synth/anchors.py` — 从 fragments.db 查高信号未处理锚点
- `jfox/gem_synth/transcript.py` — 读 CC transcript.jsonl，按 timestamp 取"一轮"上下文
- `jfox/gem_synth/grounding.py` — hybrid 检索 permanent 笔记 top-K
- `jfox/gem_synth/llm.py` — 独立 claude -p 调用封装
- `jfox/gem_synth/synthesizer.py` — 编排：锚点→上下文→基准→LLM→candidate 笔记
- `jfox/gem_synth/loop.py` — daemon 后台循环（仿 auto_summary/loop.py）
- `jfox/gem_synth/cli.py` — `jfox candidates list`
- `tests/unit/test_gem_synth_store.py`
- `tests/unit/test_gem_synth_anchors.py`
- `tests/unit/test_gem_synth_transcript.py`
- `tests/unit/test_gem_synth_grounding.py`
- `tests/unit/test_gem_synth_synthesizer.py`
- `tests/integration/test_gem_synth_flow.py`（用户跑）

改动：
- `jfox/models.py` — NoteType 加 `CANDIDATE`；新增 `GemLevel` 枚举；Note 加 candidate 专属可选字段 + to_markdown/from_markdown 序列化
- `jfox/note.py` — filename 对 CANDIDATE 的处理（title slug）
- `jfox/global_config.py` — `GemSynthesisConfig` 配置段 + 挂进 GlobalConfig
- `jfox/daemon/server.py` — lifespan 启动 gem_synth 循环（仿 auto_summary）
- `jfox/cli.py` — 挂载 `candidates_app`

---

## Phase A：笔记基础设施

### Task A1: GemLevel 枚举 + NoteType.CANDIDATE

**Files:**
- Modify: `jfox/models.py`
- Test: `tests/unit/test_note_type_candidate.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_note_type_candidate.py`**

```python
"""验证 NoteType.CANDIDATE 与 GemLevel 枚举。"""

from jfox.models import NoteType, GemLevel


def test_candidate_note_type():
    assert NoteType.CANDIDATE.value == "candidate"


def test_gem_level_enum_has_5_levels():
    levels = [g.value for g in GemLevel]
    assert levels == ["chipped", "flawed", "normal", "flawless", "perfect"]


def test_gem_level_flawed():
    assert GemLevel.FLAWED.value == "flawed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_type_candidate.py -v`
Expected: FAIL — `ImportError: cannot import name 'GemLevel'`

- [ ] **Step 3: 改 `jfox/models.py`**

在 `class NoteType(Enum)` 加一行：
```python
    SESSION = "session"  # AI Agent 会话记录
    CANDIDATE = "candidate"  # AI 合成的候选知识宝石（破损级，待 L5 审阅）
```

在 NoteType 之后、Note 之前加 GemLevel：
```python
class GemLevel(str, Enum):
    """知识宝石等级（碎裂→破损→完整→完美→无暇）。L3 仅产出 FLAWED。"""

    CHIPPED = "chipped"  # 碎裂 — raw 碎片（fragments.db，非笔记）
    FLAWED = "flawed"  # 破损 — L3 合成的 candidate
    NORMAL = "normal"  # 完整 — L4/L5 成熟后
    FLAWLESS = "flawless"  # 完美
    PERFECT = "perfect"  # 无暇 — 晋升 permanent 的候选终态
```

（确认文件顶部已 `from enum import Enum`；若 `str, Enum` 需要额外导入无需改动。）

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_type_candidate.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add jfox/models.py tests/unit/test_note_type_candidate.py
git commit -m "feat(models): add NoteType.CANDIDATE + GemLevel enum (5 levels)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A2: Note 加 candidate 专属字段 + 序列化

**Files:**
- Modify: `jfox/models.py`（Note dataclass + to_markdown/from_markdown）
- Test: `tests/unit/test_note_candidate_fields.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_note_candidate_fields.py`**

```python
"""验证 candidate 笔记的专属字段序列化往返。"""

from datetime import datetime

from jfox.models import Note, NoteType, GemLevel


def _candidate_note():
    return Note(
        id="20260621143000",
        title="测试候选宝石",
        content="# 测试\n正文",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
        tags=[],
        gem_level=GemLevel.FLAWED.value,
        confidence=0.82,
        source_fragments=[12, 15],
        grounded_by=["已有永久笔记A"],
        knowledge_type="procedural",
        status="pending",
    )


def test_candidate_to_markdown_has_fields():
    md = _candidate_note().to_markdown()
    assert "gem_level: flawed" in md
    assert "confidence: 0.82" in md
    assert "source_fragments:" in md
    assert "grounded_by:" in md
    assert "knowledge_type: procedural" in md
    assert "status: pending" in md


def test_candidate_roundtrip_preserves_fields():
    note = _candidate_note()
    md = note.to_markdown()
    restored = Note.from_markdown(md)
    assert restored.type == NoteType.CANDIDATE
    assert restored.gem_level == "flawed"
    assert restored.confidence == 0.82
    assert restored.source_fragments == [12, 15]
    assert restored.grounded_by == ["已有永久笔记A"]
    assert restored.knowledge_type == "procedural"
    assert restored.status == "pending"


def test_non_candidate_note_has_no_candidate_fields():
    from datetime import datetime
    note = Note(
        id="20260621143001",
        title="普通永久",
        content="x",
        type=NoteType.PERMANENT,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
    )
    md = note.to_markdown()
    assert "gem_level" not in md
    assert "confidence" not in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_candidate_fields.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'gem_level'`

- [ ] **Step 3: 改 `jfox/models.py` Note dataclass**

在 Note 现有字段之后（`archived` 之后、运行时字段之前）加 candidate 专属可选字段：
```python
    archived: bool = False  # 是否已归档（软删除标记）

    # candidate 专属字段（仅 type=CANDIDATE 时序列化；其它类型忽略）
    gem_level: Optional[str] = None
    confidence: Optional[float] = None
    source_fragments: List[int] = field(default_factory=list)
    grounded_by: List[str] = field(default_factory=list)
    knowledge_type: Optional[str] = None  # factual/procedural/preference/constraint
    status: Optional[str] = None  # pending → (L5) promoted/rejected
```

- [ ] **Step 4: 改 `to_markdown` —— 仅 CANDIDATE 时输出这些字段**

定位 `to_markdown` 里写 frontmatter 的部分（按现有代码风格，是拼 YAML）。在写入 `archived` 之后、frontmatter 结束之前，加：
```python
        if self.type == NoteType.CANDIDATE:
            lines.append(f"gem_level: {self.gem_level or 'flawed'}")
            if self.confidence is not None:
                lines.append(f"confidence: {self.confidence}")
            if self.source_fragments:
                lines.append(f"source_fragments: {self.source_fragments}")
            if self.grounded_by:
                lines.append(f"grounded_by: {self.grounded_by}")
            if self.knowledge_type:
                lines.append(f"knowledge_type: {self.knowledge_type}")
            if self.status:
                lines.append(f"status: {self.status}")
```
（具体 frontmatter 拼接方式以现有 `to_markdown` 为准 —— 用同样的 list-append + join 风格；若现有用的是 yaml.dump 则把 candidate 字段塞进同一个 dict。**实现前先 Read models.py 的 to_markdown 看它怎么写 frontmatter，照它的方式。**）

- [ ] **Step 5: 改 `from_markdown` —— 解析这些字段**

在 `from_markdown` 里解析 frontmatter dict 的地方，加（仅当解析到的 type==candidate 时读取，找不到则用默认）：
```python
    gem_level=frontmatter.get("gem_level"),
    confidence=frontmatter.get("confidence"),
    source_fragments=list(frontmatter.get("source_fragments") or []),
    grounded_by=list(frontmatter.get("grounded_by") or []),
    knowledge_type=frontmatter.get("knowledge_type"),
    status=frontmatter.get("status"),
```
（`confidence` 从 YAML 读回可能是 int/float，测试用 0.82，YAML 解析为 float，OK。**实现前 Read from_markdown 确认 frontmatter dict 变量名。**）

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_candidate_fields.py tests/unit/test_note_type_candidate.py -v`
Expected: PASS

- [ ] **Step 7: 回归既有 Note 测试**

Run: `uv run pytest tests/unit/ -k "note or models" -v 2>&1 | tail -15`
Expected: PASS（确认 to_markdown/from_markdown 改动没破坏既有笔记）

- [ ] **Step 8: 提交**

```bash
git add jfox/models.py tests/unit/test_note_candidate_fields.py
git commit -m "feat(models): candidate note fields (gem_level/confidence/source/grounding/status)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A3: note.py filename 对 CANDIDATE 的处理

**Files:**
- Modify: `jfox/note.py`
- Test: `tests/unit/test_note_candidate_filename.py`

- [ ] **Step 1: 写失败测试**

```python
"""candidate 笔记文件名 = id + title slug（同 permanent 风格）。"""

from datetime import datetime

from jfox.models import Note, NoteType


def test_candidate_filename_uses_title_slug():
    note = Note(
        id="20260621143000",
        title="Gem Synthesis Design",
        content="x",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
    )
    assert note.filename == "20260621143000-gem-synthesis-design.md"
```

- [ ] **Step 2: 跑确认失败**（若 Note.filename 的 else 分支已覆盖则可能直接通过；先跑看）

Run: `uv run pytest tests/unit/test_note_candidate_filename.py -v`

- [ ] **Step 3: 改 `jfox/models.py` 的 `filename` property**

当前 `filename` 只对 FLEETING / SESSION 特判，else 分支（literature/permanent）用 title slug。CANDIDATE 走 else 即可（title slug）。**若 Step 2 已通过则跳过本步**；若失败，确认 else 分支逻辑，无需新增 case（CANDIDATE 天然走 else）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_candidate_filename.py -v`
Expected: PASS

- [ ] **Step 5: 提交（若有改动）**

```bash
git add jfox/models.py tests/unit/test_note_candidate_filename.py
git commit -m "test(models): candidate note filename uses title slug

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase B：合成存储层（synthesis_log + 锚点查询）

### Task B1: GemSynthesisConfig

**Files:**
- Modify: `jfox/global_config.py`
- Test: `tests/unit/test_gem_synth_config.py`

- [ ] **Step 1: 写失败测试**

```python
from jfox.global_config import GemSynthesisConfig


def test_defaults():
    cfg = GemSynthesisConfig()
    assert cfg.enabled is False  # 默认关闭，opt-in
    assert cfg.interval_minutes == 30
    assert cfg.anchor_types == ["correction", "decision", "ask_user_question"]
    assert cfg.grounding_top_k == 5
    assert cfg.target_kb is None


def test_from_dict_empty():
    cfg = GemSynthesisConfig.from_dict({})
    assert cfg.enabled is False


def test_from_dict_explicit():
    cfg = GemSynthesisConfig.from_dict({"enabled": True, "grounding_top_k": 8})
    assert cfg.enabled is True
    assert cfg.grounding_top_k == 8


def test_roundtrip():
    cfg = GemSynthesisConfig(grounding_top_k=7)
    assert GemSynthesisConfig.from_dict(cfg.to_dict()).grounding_top_k == 7
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_config.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 在 `jfox/global_config.py` 加 dataclass**（仿 `AutoSummaryConfig`/`FragmentCaptureConfig`）

```python
@dataclass
class GemSynthesisConfig:
    """L3 宝石合成配置（opt-in，默认关闭）"""

    enabled: bool = False
    interval_minutes: int = 30  # daemon 循环周期
    anchor_types: List[str] = field(
        default_factory=lambda: ["correction", "decision", "ask_user_question"]
    )
    grounding_top_k: int = 5  # 检索多少条 permanent 笔记做基准
    target_kb: Optional[str] = None  # candidate 写入哪个 KB；None 用 default
    claude_timeout_seconds: int = 180
    claude_binary: Optional[str] = None  # None → 从 PATH 解析

    def __post_init__(self) -> None:
        if self.interval_minutes < 1:
            self.interval_minutes = 30
        if self.grounding_top_k < 1:
            self.grounding_top_k = 5
        if self.claude_timeout_seconds < 30:
            self.claude_timeout_seconds = 180

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "GemSynthesisConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            interval_minutes=int(data.get("interval_minutes", 30)),
            anchor_types=(
                list(data["anchor_types"])
                if isinstance(data.get("anchor_types"), list)
                else cls().anchor_types
            ),
            grounding_top_k=int(data.get("grounding_top_k", 5)),
            target_kb=data.get("target_kb"),
            claude_timeout_seconds=int(data.get("claude_timeout_seconds", 180)),
            claude_binary=data.get("claude_binary"),
        )
```

挂进 `GlobalConfig`（field + to_dict + from_dict）+ manager 加 `get_gem_synthesis_config()` / `update_gem_synthesis_config(**changes)`，**完全照搬 FragmentCaptureConfig 的挂法**（见 `jfox/global_config.py` 里 fragment_capture 的三处）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_config.py tests/unit/test_global_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add jfox/global_config.py tests/unit/test_gem_synth_config.py
git commit -m "feat(gem-synth): add GemSynthesisConfig (opt-in, default off)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B2: synthesis_log store

**Files:**
- Create: `jfox/gem_synth/__init__.py`, `jfox/gem_synth/store.py`
- Test: `tests/unit/test_gem_synth_store.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_store.py`**

```python
"""SynthesisLog SQLite 测试（临时库，无 daemon/模型）。"""

import jfox.gem_synth.store as store_mod
from jfox.gem_synth.store import SynthesisLog


def _log(tmp_path):
    return SynthesisLog(db_path=tmp_path / "synthesis.db")


def test_is_processed_false_initially(tmp_path):
    log = _log(tmp_path)
    assert log.is_processed(42) is False


def test_mark_and_check(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(anchor_fragment_id=42, candidate_note_id="candidate_20260621143000")
    assert log.is_processed(42) is True


def test_get_unprocessed_returns_missing(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(1, "c1")
    log.mark_processed(3, "c3")
    # 传 [1,2,3,4]，返回未处理的
    unprocessed = log.filter_unprocessed([1, 2, 3, 4])
    assert unprocessed == [2, 4]


def test_idempotent_mark(tmp_path):
    log = _log(tmp_path)
    log.mark_processed(1, "c1")
    log.mark_processed(1, "c1b")  # 重复，不应崩
    assert log.is_processed(1) is True
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_store.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/__init__.py`**

```python
"""L3 宝石合成子包：碎裂碎片 → 破损级 candidate 笔记。"""
```

- [ ] **Step 4: 创建 `jfox/gem_synth/store.py`**（仿 `jfox/fragment/store.py` 的 SQLite/WAL 模式）

```python
"""合成记账：哪些锚点碎片已合成过，避免重复。SQLite（WAL）。"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT NOT NULL,
    synthesized_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class SynthesisLog:
    """合成记账表。daemon 持有常驻实例；测试传临时路径。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        from .paths import default_synthesis_db_path

        self.db_path: Path = Path(db_path) if db_path is not None else default_synthesis_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._closed = False

    def is_processed(self, anchor_fragment_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM synthesis_log WHERE anchor_fragment_id = ?",
                (anchor_fragment_id,),
            ).fetchone()
        return row is not None

    def filter_unprocessed(self, fragment_ids: List[int]) -> List[int]:
        if not fragment_ids:
            return []
        placeholders = ",".join("?" * len(fragment_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT anchor_fragment_id FROM synthesis_log WHERE anchor_fragment_id IN ({placeholders})",
                fragment_ids,
            ).fetchall()
        done = {r[0] for r in rows}
        return [fid for fid in fragment_ids if fid not in done]

    def mark_processed(self, anchor_fragment_id: int, candidate_note_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log (anchor_fragment_id, candidate_note_id) VALUES (?, ?)",
                (anchor_fragment_id, candidate_note_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True


__all__ = ["SynthesisLog"]
```

- [ ] **Step 5: 创建 `jfox/gem_synth/paths.py`**

```python
"""gem_synth 默认路径。"""

import os
from pathlib import Path


def default_synthesis_db_path() -> Path:
    """合成记账库路径，可被 JFOX_SYNTHESIS_DB 覆盖（测试用）。"""
    env = os.environ.get("JFOX_SYNTHESIS_DB")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".zettelkasten" / "synthesis_log.db"
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_store.py -v`
Expected: PASS（4 tests）

- [ ] **Step 7: 提交**

```bash
git add jfox/gem_synth/__init__.py jfox/gem_synth/store.py jfox/gem_synth/paths.py tests/unit/test_gem_synth_store.py
git commit -m "feat(gem-synth): add SynthesisLog (dedup table, SQLite WAL)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B3: 锚点查询（anchors.py）

**Files:**
- Create: `jfox/gem_synth/anchors.py`
- Test: `tests/unit/test_gem_synth_anchors.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_anchors.py`**

```python
"""锚点查询：从 fragments.db 取高信号未处理锚点。"""

from jfox.fragment.store import FragmentStore
from jfox.gem_synth.anchors import find_anchors
from jfox.gem_synth.store import SynthesisLog


def _seed_fragments(tmp_path):
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    # 高信号锚点
    correction = store.insert("s1", "correction", "UserPromptSubmit", "不对，应该用 patch", {})
    decision = store.insert("s1", "decision", "UserPromptSubmit", "我决定用方案 A", {})
    ask = store.insert(
        "s1",
        "user_input",  # AskUserQuestion 的 PostToolUse 暂记为 user_input 类型 + 特殊 source_event
        "PostToolUse",
        "AskUserQuestion",
        {"tool_name": "AskUserQuestion"},
    )
    # 非锚点
    store.insert("s1", "user_input", "UserPromptSubmit", "继续", {})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.close()
    return correction, decision, ask


def test_find_anchors_returns_high_signal(tmp_path):
    correction, decision, ask = _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    anchors = find_anchors(
        fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["correction", "decision", "ask_user_question"]
    )
    ids = [a["fragment_id"] for a in anchors]
    assert correction in ids
    assert decision in ids
    assert ask in ids  # AskUserQuestion PostToolUse 命中 ask_user_question


def test_find_anchors_excludes_processed(tmp_path):
    correction, decision, ask = _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    log.mark_processed(correction, "c1")
    anchors = find_anchors(
        fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["correction", "decision", "ask_user_question"]
    )
    ids = [a["fragment_id"] for a in anchors]
    assert correction not in ids
    assert decision in ids


def test_find_anchors_has_transcript_path(tmp_path):
    _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    # 给 correction 补 transcript_path 到 metadata
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    store.insert(
        "s1",
        "correction",
        "UserPromptSubmit",
        "x",
        {"transcript_path": "/tmp/t.jsonl", "session_id": "s1"},
    )
    store.close()
    anchors = find_anchors(
        fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["correction"]
    )
    # 至少一条带 transcript_path
    assert any(a.get("transcript_path") for a in anchors)
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_anchors.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/anchors.py`**

```python
"""锚点查询：从 fragments.db 取高信号、未处理的锚点碎片。

锚点类型（配置项 anchor_types）：
- correction / decision：fragment_type 命中
- ask_user_question：PostToolUse 且 metadata.tool_name == 'AskUserQuestion'
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


def _anchor_sql(anchor_types: List[str]) -> tuple:
    """构造查锚点的 SQL + params。"""
    clauses = []
    params: List = []
    if "correction" in anchor_types:
        clauses.append("fragment_type = 'correction'")
    if "decision" in anchor_types:
        clauses.append("fragment_type = 'decision'")
    if "ask_user_question" in anchor_types:
        # AskUserQuestion 走 PostToolUse；fragment_type 可能是 tool_call/user_input，
        # 用 metadata_json LIKE 粗筛（精确判断在 Python 里做）
        clauses.append("(source_event = 'PostToolUse' AND metadata_json LIKE '%AskUserQuestion%')")
    if not clauses:
        return "", params
    where = " OR ".join(clauses)
    return f"WHERE {where}", params


def find_anchors(
    fragments_db: Path,
    log,
    anchor_types: List[str],
    session_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """返回未处理的高信号锚点（dict 含 fragment_id/session_id/timestamp/content/transcript_path/metadata）。"""
    where, params = _anchor_sql(anchor_types)
    if not where:
        return []
    session_clause = ""
    if session_id:
        session_clause = f"{'AND' if where else 'WHERE'} session_id = ?"
        params.append(session_id)
    sql = (
        f"SELECT fragment_id, session_id, timestamp, content, metadata_json "
        f"FROM session_fragments {where} {session_clause} "
        f"ORDER BY fragment_id LIMIT ?"
    )
    params.append(limit * 3)  # 多取一些，过滤掉已处理/AskUserQuestion 误命中后仍够

    conn = sqlite3.connect(str(fragments_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    all_ids = [r["fragment_id"] for r in rows]
    unprocessed_set = set(log.filter_unprocessed(all_ids))

    result = []
    for r in rows:
        if r["fragment_id"] not in unprocessed_set:
            continue
        md = json.loads(r["metadata_json"] or "{}")
        # ask_user_question 精确二次确认（避免 LIKE 误命中正文含 AskUserQuestion 的）
        if (
            r["fragment_type"] not in ("correction", "decision")
            and md.get("tool_name") != "AskUserQuestion"
            and "ask_user_question"
            in [t for t in anchor_types if r["fragment_type"] not in ("correction", "decision")]
        ):
            # 落到这条仅当它是 AskUserQuestion
            if md.get("tool_name") != "AskUserQuestion":
                continue
        result.append(
            {
                "fragment_id": r["fragment_id"],
                "session_id": r["session_id"],
                "timestamp": r["timestamp"],
                "content": r["content"],
                "transcript_path": md.get("transcript_path"),
                "metadata": md,
            }
        )
        if len(result) >= limit:
            break
    return result


__all__ = ["find_anchors"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_anchors.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/anchors.py tests/unit/test_gem_synth_anchors.py
git commit -m "feat(gem-synth): anchor query from fragments.db (correction/decision/AskUserQuestion)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase C：transcript 解析器

### Task C1: transcript "一轮"上下文提取

**Files:**
- Create: `jfox/gem_synth/transcript.py`
- Test: `tests/unit/test_gem_synth_transcript.py`

**格式备忘**（实地确认，见 spec §9）：transcript 每行一个 JSON：`{type, message:{role, content}, timestamp, uuid, parentUuid, sessionId, ...}`。user 的 content 是 **string**；assistant 的 content 是 **list of blocks**（block.type ∈ thinking/text/tool_use/tool_result）。

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_transcript.py`**

```python
"""transcript 一轮上下文提取测试（用临时 jsonl 文件）。"""

import json
from pathlib import Path

from jfox.gem_synth.transcript import extract_turn_around, _iter_messages


def _write_transcript(path: Path, messages):
    with open(path, "w") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")


def _user(text, ts):
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts, "uuid": f"u-{ts}"}


def _assistant(text, ts, thinking="思考"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": thinking},
                {"type": "text", "text": text},
            ],
        },
        "timestamp": ts,
        "uuid": f"a-{ts}",
    }


def test_extract_turn_includes_anchor_and_response(tmp_path):
    p = tmp_path / "t.jsonl"
    _write_transcript(
        p,
        [
            _user("第一条", "2026-06-21T06:25:00"),
            _assistant("回复1", "2026-06-21T06:25:10"),
            _user("锚点这条", "2026-06-21T06:26:00"),  # ← 锚点
            _assistant("回复锚点", "2026-06-21T06:26:10"),
            _user("下一条", "2026-06-21T06:27:00"),
        ],
    )
    turn = extract_turn_around(p, anchor_user_text="锚点这条")
    assert "锚点这条" in turn
    assert "回复锚点" in turn
    assert "下一条" not in turn  # 下一轮不应包含
    assert "第一条" not in turn  # 上一轮不应包含


def test_extract_turn_returns_empty_if_anchor_not_found(tmp_path):
    p = tmp_path / "t.jsonl"
    _write_transcript(p, [_user("x", "2026-06-21T06:25:00")])
    assert extract_turn_around(p, anchor_user_text="不存在") == ""


def test_extract_turn_handles_missing_file(tmp_path):
    assert extract_turn_around(tmp_path / "nope.jsonl", anchor_user_text="x") == ""
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_transcript.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/transcript.py`**

```python
"""读 CC transcript.jsonl，提取锚点那一"轮"的完整上下文。

一轮 = 锚点 user 消息 + 其后的 assistant 回复（thinking/text/tool_use），
到下一条 user 消息为止。
"""

import json
import logging
from pathlib import Path
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)


def _iter_messages(transcript_path: Path) -> Iterator[dict]:
    """逐行 yield transcript 消息（跳过非 user/assistant 的元数据行）。"""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") in ("user", "assistant"):
                    yield d
    except FileNotFoundError:
        logger.warning("transcript 不存在: %s", transcript_path)
        return
    except Exception as e:
        logger.exception("读 transcript 异常 %s: %s", transcript_path, e)
        return


def _block_to_text(block: dict) -> str:
    """把 assistant content block 转成可读文本。"""
    btype = block.get("type")
    if btype == "text":
        return block.get("text", "")
    if btype == "thinking":
        return f"[思考] {block.get('thinking', '')}"
    if btype == "tool_use":
        return f"[工具调用: {block.get('name')}] {json.dumps(block.get('input', {}), ensure_ascii=False)[:300]}"
    if btype == "tool_result":
        c = block.get("content")
        if isinstance(c, list):
            c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
        return f"[工具结果] {str(c)[:300]}"
    return ""


def _user_text(msg: dict) -> str:
    content = msg.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_block_to_text(b) for b in content if isinstance(b, dict))
    return ""


def _assistant_text(msg: dict) -> str:
    content = msg.get("message", {}).get("content")
    if isinstance(content, list):
        return "\n".join(_block_to_text(b) for b in content if isinstance(b, dict))
    return str(content or "")


def extract_turn_around(transcript_path: Path, anchor_user_text: str) -> str:
    """返回锚点那一轮的文本：锚点 user 消息 + 后续 assistant 回复（到下一条 user）。

    用锚点 user 消息的文本前缀匹配（锚点 content 可能被碎片截断过，用 startsWith 反向：
    transcript 里的完整文本以锚点文本为子串，或锚点文本是 transcript 文本前缀）。
    """
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    transcript_path = Path(transcript_path)
    anchor = (anchor_user_text or "").strip()
    if not anchor:
        return ""

    msgs = list(_iter_messages(transcript_path))
    # 找锚点 user 消息：transcript 文本包含锚点文本（锚点可能被截断，故用子串）
    anchor_idx = None
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        full = _user_text(m)
        if anchor in full or full.startswith(anchor[:40]):
            anchor_idx = i
            break
    if anchor_idx is None:
        return ""

    parts: List[str] = [f"[用户] {_user_text(msgs[anchor_idx])}"]
    for m in msgs[anchor_idx + 1 :]:
        if m.get("type") == "user":
            break  # 下一轮开始
        parts.append(f"[助手] {_assistant_text(m)}")
    return "\n\n".join(parts).strip()


__all__ = ["extract_turn_around", "_iter_messages"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_transcript.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/transcript.py tests/unit/test_gem_synth_transcript.py
git commit -m "feat(gem-synth): transcript turn extraction around anchor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase D：永久笔记检索（grounding）

### Task D1: grounding 检索 permanent 笔记

**Files:**
- Create: `jfox/gem_synth/grounding.py`
- Test: `tests/unit/test_gem_synth_grounding.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_grounding.py`**

```python
"""grounding：检索 permanent 笔记 top-K（用 mocked search 避免加载模型）。"""

from unittest.mock import MagicMock, patch

from jfox.gem_synth.grounding import fetch_grounding


def test_fetch_grounding_returns_top_k_titles_and_snippets():
    fake_results = [
        {"title": "笔记A", "content": "内容A", "id": "1", "score": 0.9},
        {"title": "笔记B", "content": "内容B", "id": "2", "score": 0.7},
    ]
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as MockEngine:
        instance = MockEngine.return_value
        instance.search.return_value = fake_results
        grounding = fetch_grounding("锚点内容", top_k=2, kb="default")
    titles = [g["title"] for g in grounding]
    assert titles == ["笔记A", "笔记B"]
    # 确认 search 被调用时限定了 note_type=permanent
    instance.search.assert_called_once()
    args, kwargs = instance.search.call_args
    assert kwargs.get("note_type") == "permanent" or (args and "permanent" in str(args))


def test_fetch_grounding_empty_query_returns_empty():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine"):
        assert fetch_grounding("", top_k=5, kb="default") == []


def test_fetch_grounding_handles_search_exception():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as MockEngine:
        MockEngine.return_value.search.side_effect = RuntimeError("boom")
        assert fetch_grounding("x", top_k=5, kb="default") == []
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_grounding.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/grounding.py`**

```python
"""检索 permanent 笔记 top-K，作为合成基准（防幻觉佐证）。"""

import logging
from typing import Dict, List, Optional

from ..search_engine import HybridSearchEngine, SearchMode

logger = logging.getLogger(__name__)


def fetch_grounding(
    query: str, top_k: int = 5, kb: Optional[str] = None
) -> List[Dict]:
    """返回 [{title, content, id, score}]，仅 permanent 笔记。查询为空或异常返回 []。"""
    if not (query or "").strip():
        return []
    try:
        engine = HybridSearchEngine(kb=kb) if kb else HybridSearchEngine()
        results = engine.search(
            query=query,
            mode=SearchMode.HYBRID,
            note_type="permanent",
            top_k=top_k,
        )
    except Exception as e:
        logger.exception("grounding 检索失败: %s", e)
        return []
    # results 元素结构以 HybridSearchEngine.search 实际返回为准（dict 含 title/content/id/score）
    grounding = []
    for r in results:
        grounding.append(
            {
                "title": r.get("title") or r.get("metadata", {}).get("title", ""),
                "content": (r.get("content") or r.get("document") or "")[:500],
                "id": r.get("id") or r.get("metadata", {}).get("id", ""),
                "score": r.get("score"),
            }
        )
    return grounding


__all__ = ["fetch_grounding"]
```

> **实现注意**：`HybridSearchEngine.search` 的返回元素结构需在实现时实地核对（运行 `uv run python -c "from jfox.search_engine import HybridSearchEngine; ..."` 看一条结果的 keys）。上面的 `.get()` 兼容了 `title`/`metadata.title`、`content`/`document` 两种常见结构。若实际结构不同，调整字段名。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_grounding.py -v`
Expected: PASS（3 tests，全用 mock，不加载模型）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/grounding.py tests/unit/test_gem_synth_grounding.py
git commit -m "feat(gem-synth): grounding retrieval (permanent notes top-K)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase E：LLM 合成器

### Task E1: 独立 LLM 调用封装（claude -p）

**Files:**
- Create: `jfox/gem_synth/llm.py`
- Test: `tests/unit/test_gem_synth_llm.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_llm.py`**

```python
"""LLM 调用封装测试（mock subprocess，不真调 claude）。"""

import json
from unittest.mock import patch, MagicMock

from jfox.gem_synth.llm import synthesize_with_llm, _build_prompt


def test_build_prompt_contains_context_and_grounding():
    prompt = _build_prompt(
        turn_context="用户说：不对，应该用 patch",
        grounding=[{"title": "补丁规范", "content": "优先用 patch"}],
    )
    assert "不对，应该用 patch" in prompt
    assert "补丁规范" in prompt
    assert "优先用 patch" in prompt


def test_synthesize_returns_parsed_dict():
    fake_output = json.dumps(
        {
            "title": "应优先用 patch 而非 sed",
            "content": "## 知识\n修改文件优先用 patch...",
            "confidence": 0.85,
            "knowledge_type": "procedural",
            "grounded_by": ["补丁规范"],
        }
    )
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(
            turn_context="x", grounding=[{"title": "补丁规范", "content": "y"}], cfg=MagicMock()
        )
    assert result["title"] == "应优先用 patch 而非 sed"
    assert result["confidence"] == 0.85
    assert result["knowledge_type"] == "procedural"


def test_synthesize_returns_none_on_invalid_json():
    with patch("jfox.gem_synth.llm._invoke_claude", return_value="not json"):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is None


def test_synthesize_returns_none_on_exception():
    with patch("jfox.gem_synth.llm._invoke_claude", side_effect=RuntimeError("boom")):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is None
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_llm.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/llm.py`**（独立调用，不耦合 auto_summary；参考其 `_invoke_claude` 的 subprocess + env 隔离模式）

```python
"""独立 LLM 调用：claude -p 合成破损宝石。不耦合 auto_summary。

参考 auto_summary/runner.py 的 _invoke_claude（subprocess + env 隔离），但独立实现。
"""

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from ..global_config import GemSynthesisConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是知识合成器。给定一段对话上下文和若干已有永久笔记（事实基准），
从中合成出一条可复用的知识宝石（破损级）。严格输出 JSON：
{
  "title": "简洁标题",
  "content": "Markdown 正文，结构化知识",
  "confidence": 0.0-1.0 的浮点（与基准一致性、信号强度、上下文完整度），
  "knowledge_type": "factual|procedural|preference|constraint",
  "grounded_by": ["引用的永久笔记标题列表"]
}
若上下文不足以合成有效知识，confidence 给低分（<0.3）并简述原因。不要编造基准里没有的事实。"""


def _resolve_claude_binary(cfg: GemSynthesisConfig) -> str:
    if cfg.claude_binary:
        return cfg.claude_binary
    found = shutil.which("claude")
    if not found:
        raise RuntimeError("找不到 claude 二进制（PATH 无 claude，且 cfg.claude_binary 未设）")
    return found


def _build_prompt(turn_context: str, grounding: List[Dict[str, Any]]) -> str:
    grounding_md = (
        "\n".join(f"- ### {g['title']}\n{g['content']}" for g in grounding)
        if grounding
        else "（无相关永久笔记）"
    )
    return f"""## 对话上下文（待合成的锚点一轮）
{turn_context}

## 已有永久笔记（事实基准，防幻觉）
{grounding_md}

请合成一条知识宝石。只输出 JSON。"""


def _invoke_claude(prompt: str, cfg: GemSynthesisConfig) -> str:
    """调用 claude -p，返回 stdout。"""
    binary = _resolve_claude_binary(cfg)
    cmd = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--append-system-prompt",
        SYSTEM_PROMPT,
        "--permission-mode",
        "bypassPermissions",
    ]
    env = os.environ.copy()
    # 隔离：避免继承影响子 claude 行为的变量
    for noisy in ("JFOX_KB", "JFOX_DAEMON_PROCESS"):
        env.pop(noisy, None)
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=cfg.claude_timeout_seconds,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 退出码 {proc.returncode}: {proc.stderr[:300]}")
    return proc.stdout


def synthesize_with_llm(
    turn_context: str, grounding: List[Dict[str, Any]], cfg: GemSynthesisConfig
) -> Optional[Dict[str, Any]]:
    """返回合成结果 dict（title/content/confidence/knowledge_type/grounded_by），失败返回 None。"""
    try:
        prompt = _build_prompt(turn_context, grounding)
        raw = _invoke_claude(prompt, cfg)
        # claude --output-format json 返回的是 {result: "..."} 包装，result 内才是模型输出
        wrapper = json.loads(raw)
        inner = wrapper.get("result", raw) if isinstance(wrapper, dict) else raw
        parsed = json.loads(inner) if isinstance(inner, str) else inner
        if not isinstance(parsed, dict) or "title" not in parsed:
            logger.warning("LLM 输出缺 title: %r", parsed)
            return None
        return parsed
    except Exception as e:
        logger.exception("LLM 合成失败: %s", e)
        return None


__all__ = ["synthesize_with_llm", "_build_prompt"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_llm.py -v`
Expected: PASS（4 tests，全 mock subprocess）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/llm.py tests/unit/test_gem_synth_llm.py
git commit -m "feat(gem-synth): standalone LLM call (claude -p, decoupled from auto_summary)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task E2: synthesizer 编排（锚点→candidate 笔记）

**Files:**
- Create: `jfox/gem_synth/synthesizer.py`
- Test: `tests/unit/test_gem_synth_synthesizer.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_synthesizer.py`**

```python
"""synthesizer 编排测试（mock transcript/grounding/llm）。"""

from pathlib import Path
from unittest.mock import patch, MagicMock

from jfox.gem_synth.synthesizer import synthesize_anchor
from jfox.gem_synth.store import SynthesisLog


def test_synthesize_anchor_produces_candidate_note(tmp_path):
    anchor = {
        "fragment_id": 42,
        "session_id": "s1",
        "timestamp": "2026-06-21 14:30:00",
        "content": "不对，应该用 patch",
        "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {"session_id": "s1"},
    }
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    fake_llm = {
        "title": "用 patch 而非 sed",
        "content": "## 知识\n改文件优先 patch",
        "confidence": 0.85,
        "knowledge_type": "procedural",
        "grounded_by": ["补丁规范"],
    }
    with patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文X"), \
         patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[{"title": "补丁规范", "content": "y"}]), \
         patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=fake_llm), \
         patch("jfox.gem_synth.synthesizer._save_candidate_note", return_value="candidate_20260621143000"):
        result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), kb="default")
    assert result is not None
    assert result["candidate_note_id"] == "candidate_20260621143000"
    assert result["title"] == "用 patch 而非 sed"
    # 已记账
    assert log.is_processed(42) is True


def test_synthesize_anchor_skips_when_llm_returns_none(tmp_path):
    anchor = {
        "fragment_id": 43,
        "session_id": "s1",
        "timestamp": "2026-06-21 14:30:00",
        "content": "x",
        "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {},
    }
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    with patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"), \
         patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]), \
         patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=None):
        result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), kb="default")
    assert result is None
    assert log.is_processed(43) is False  # 失败不记账，下轮可重试


def test_synthesize_anchor_skips_when_no_transcript(tmp_path):
    anchor = {
        "fragment_id": 44,
        "session_id": "s1",
        "timestamp": "2026-06-21 14:30:00",
        "content": "x",
        "transcript_path": None,
        "metadata": {},
    }
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), kb="default")
    assert result is None
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/synthesizer.py`**

```python
"""合成编排：单个锚点 → transcript 上下文 → grounding → LLM → candidate 笔记 + 记账。"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..global_config import GemSynthesisConfig
from ..models import GemLevel, Note, NoteType
from ..note import save_note
from .grounding import fetch_grounding
from .llm import synthesize_with_llm
from .transcript import extract_turn_around

logger = logging.getLogger(__name__)


def _save_candidate_note(
    llm_result: Dict[str, Any],
    anchor: Dict[str, Any],
    kb: Optional[str],
) -> Optional[str]:
    """把 LLM 结果存成 candidate 笔记，返回 note id。"""
    from datetime import datetime
    import re

    now = datetime.now()
    note_id = now.strftime("%Y%m%d%H%M%S")
    title = llm_result.get("title", "未命名候选宝石")
    content = llm_result.get("content", "")
    # 追加来源碎片段（可读性）
    source_section = (
        f"\n\n## 来源\n- 碎片 #{anchor['fragment_id']} @ {anchor['timestamp']}\n"
        f"- session `{anchor['session_id']}`\n"
    )
    grounding_section = ""
    if llm_result.get("grounded_by"):
        links = ", ".join(f"[[{g}]]" for g in llm_result["grounded_by"])
        grounding_section = f"\n## 参考的永久笔记\n{links}\n"
    conf_section = f"\n## 置信度\n{llm_result.get('confidence', '?')}\n"

    note = Note(
        id=note_id,
        title=title,
        content=content + source_section + grounding_section + conf_section,
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        gem_level=GemLevel.FLAWED.value,
        confidence=float(llm_result.get("confidence") or 0),
        source_fragments=[anchor["fragment_id"]],
        grounded_by=list(llm_result.get("grounded_by") or []),
        knowledge_type=llm_result.get("knowledge_type"),
        status="pending",
    )
    try:
        save_note(note, kb=kb)  # save_note 的签名以 note.py 实际为准
        return note_id
    except Exception as e:
        logger.exception("保存 candidate 笔记失败: %s", e)
        return None


def synthesize_anchor(
    anchor: Dict[str, Any], log, cfg: GemSynthesisConfig, kb: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """合成单个锚点。成功返回 {candidate_note_id, title, confidence}，跳过/失败返回 None。"""
    transcript_path = anchor.get("transcript_path")
    if not transcript_path:
        logger.info("锚点 #%s 无 transcript_path，跳过", anchor["fragment_id"])
        return None

    turn = extract_turn_around(Path(transcript_path), anchor.get("content") or "")
    if not turn.strip():
        logger.info("锚点 #%s 提取不到上下文，跳过", anchor["fragment_id"])
        return None

    grounding = fetch_grounding(anchor.get("content") or "", top_k=cfg.grounding_top_k, kb=kb)

    llm_result = synthesize_with_llm(turn_context=turn, grounding=grounding, cfg=cfg)
    if llm_result is None:
        logger.info("锚点 #%s LLM 合成失败/无效，跳过（不记账，下轮重试）", anchor["fragment_id"])
        return None

    note_id = _save_candidate_note(llm_result, anchor, kb)
    if note_id is None:
        return None

    # 成功才记账
    log.mark_processed(anchor_fragment_id=anchor["fragment_id"], candidate_note_id=note_id)
    return {
        "candidate_note_id": note_id,
        "title": llm_result.get("title"),
        "confidence": llm_result.get("confidence"),
    }


__all__ = ["synthesize_anchor"]
```

> **实现注意**：`save_note` 的签名（是否接受 `kb=`、note 对象传法）需在实现时核对 `jfox/note.py`。若 `save_note(note, kb=...)` 不匹配，调整为实际签名（可能是 `save_note(note, config=...)` 或 `note.save()`）。`from ..note import save_note` 的导入名也以 note.py 实际导出为准。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_synthesizer.py
git commit -m "feat(gem-synth): synthesizer orchestration (anchor -> candidate note)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase F：daemon 循环 + 装配

### Task F1: daemon 后台循环

**Files:**
- Create: `jfox/gem_synth/loop.py`
- Modify: `jfox/daemon/server.py`（lifespan 启动循环）
- Test: `tests/unit/test_gem_synth_loop.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_loop.py`**

```python
"""gem_synth 循环：_tick_once 编排（mock 各组件）。"""

import threading
from unittest.mock import patch, MagicMock

from jfox.gem_synth.loop import _tick_once


def test_tick_disabled_returns_skip():
    cfg = MagicMock()
    cfg.enabled = False
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm:
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "禁用" in msg or "跳过" in msg


def test_tick_enabled_processes_anchors():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm, \
         patch("jfox.gem_synth.loop.find_anchors", return_value=[{"fragment_id": 1, "session_id": "s", "timestamp": "t", "content": "c", "transcript_path": "/x", "metadata": {}}]) as fa, \
         patch("jfox.gem_synth.loop.synthesize_anchor", return_value={"candidate_note_id": "c1", "title": "T", "confidence": 0.8}) as sa:
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "1" in msg  # 处理了 1 个
    sa.assert_called_once()


def test_tick_synthesize_exception_does_not_crash():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm, \
         patch("jfox.gem_synth.loop.find_anchors", return_value=[{"fragment_id": 1, "session_id": "s", "timestamp": "t", "content": "c", "transcript_path": "/x", "metadata": {}}]), \
         patch("jfox.gem_synth.loop.synthesize_anchor", side_effect=RuntimeError("boom")):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())  # 不应抛
    assert isinstance(msg, str)
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_loop.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/loop.py`**（仿 `jfox/auto_summary/loop.py` 的 `_tick_once` + async loop 模式）

```python
"""daemon 后台循环：每 interval_minutes 处理一批未合成锚点。

提供：
- gem_synth_loop(stop_event): async task body
- _tick_once(stop_event): 同步 wrapper（在 executor 中执行）
"""

from __future__ import annotations

import asyncio
import logging
import threading

from ..global_config import get_global_config_manager
from .anchors import find_anchors
from .paths import default_synthesis_db_path
from .store import SynthesisLog
from .synthesizer import synthesize_anchor

logger = logging.getLogger(__name__)


def _tick_once(stop_event: threading.Event) -> str:
    """同步执行一轮：找未处理锚点 → 逐个合成。返回简短日志行。"""
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_gem_synthesis_config()
    if not cfg.enabled:
        return "gem-synth 已禁用，跳过本轮"

    log = SynthesisLog()
    try:
        from .paths import default_synthesis_db_path as _dp
        from jfox.fragment.store import default_db_path

        anchors = find_anchors(
            fragments_db=default_db_path(),
            log=log,
            anchor_types=cfg.anchor_types,
        )
    except Exception as e:
        logger.exception("gem-synth 找锚点失败: %s", e)
        return f"找锚点异常: {e}"

    if not anchors:
        return "无待合成锚点"

    success = 0
    for anchor in anchors:
        if stop_event.is_set():
            break
        try:
            result = synthesize_anchor(anchor, log=log, cfg=cfg, kb=cfg.target_kb)
            if result is not None:
                success += 1
        except Exception as e:
            logger.exception("gem-synth 合成锚点 #%s 异常: %s", anchor.get("fragment_id"), e)

    return f"待合成 {len(anchors)}, 成功 {success}"


async def gem_synth_loop(stop_event: threading.Event, interval_minutes: int = 30) -> None:
    """async 循环：每 interval_minutes 跑一次 _tick_once（在 executor 中）。"""
    import asyncio as _asyncio

    loop = _asyncio.get_running_loop()
    sleep_secs = max(60, interval_minutes * 60)
    while not stop_event.is_set():
        try:
            msg = await loop.run_in_executor(None, _tick_once, stop_event)
            logger.info("gem-synth tick: %s", msg)
        except Exception as e:
            logger.exception("gem-synth tick 异常: %s", e)
        # 分段 sleep 以便及时响应 stop
        slept = 0
        while slept < sleep_secs and not stop_event.is_set():
            await _asyncio.sleep(min(10, sleep_secs - slept))
            slept += 10


__all__ = ["gem_synth_loop", "_tick_once"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_loop.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: 在 `jfox/daemon/server.py` 装配循环**

在模块级加全局变量（仿 auto_summary 的 `_auto_summary_task`/`_auto_summary_stop_event`）：
```python
# auto-summary 后台 task 与停止信号 之后，加：
_gem_synth_task: Optional[asyncio.Task] = None
_gem_synth_stop_event: Optional[threading.Event] = None
```

加启动/停止函数（仿 `_maybe_start_auto_summary`/`_maybe_stop_auto_summary`）：
```python
def _maybe_start_gem_synth() -> None:
    """如果用户启用了 gem-synthesis，启动后台循环 task"""
    global _gem_synth_task, _gem_synth_stop_event
    try:
        from ..global_config import get_global_config_manager

        cfg = get_global_config_manager().get_gem_synthesis_config()
        if not cfg.enabled:
            logger.info("Daemon: gem-synthesis 未启用（config.gem_synthesis.enabled=false）")
            return
        from ..gem_synth.loop import gem_synth_loop

        _gem_synth_stop_event = threading.Event()
        _gem_synth_task = asyncio.create_task(
            gem_synth_loop(_gem_synth_stop_event, cfg.interval_minutes)
        )
        logger.info("Daemon: gem-synthesis 循环已启动 (interval=%dm)", cfg.interval_minutes)
    except Exception as e:
        logger.exception("Daemon: 启动 gem-synthesis 循环失败: %s", e)


async def _maybe_stop_gem_synth() -> None:
    """关闭 gem-synthesis 后台循环"""
    global _gem_synth_task, _gem_synth_stop_event
    if _gem_synth_stop_event is not None:
        _gem_synth_stop_event.set()
    if _gem_synth_task is not None:
        try:
            await asyncio.wait_for(_gem_synth_task, timeout=10)
        except asyncio.TimeoutError:
            _gem_synth_task.cancel()
    _gem_synth_task = None
    _gem_synth_stop_event = None
```

在 `lifespan` 里接线（紧跟 auto_summary 之后）：
```python
@asynccontextmanager
async def lifespan(app):
    _load_model()
    _maybe_start_auto_summary()
    _maybe_start_gem_synth()
    try:
        yield
    finally:
        await _maybe_stop_gem_synth()
        await _maybe_stop_auto_summary()
        _maybe_close_fragment_store()
```

- [ ] **Step 6: 验证装配（不启动 daemon/模型）**

Run: `uv run python -c "import jfox.daemon.server as s; print('ok', hasattr(s,'_maybe_start_gem_synth'))"`
Expected: `ok True`

- [ ] **Step 7: 提交**

```bash
git add jfox/gem_synth/loop.py jfox/daemon/server.py tests/unit/test_gem_synth_loop.py
git commit -m "feat(gem-synth): daemon background loop + lifespan wiring

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase G：candidates CLI

### Task G1: jfox candidates list

**Files:**
- Create: `jfox/gem_synth/cli.py`
- Modify: `jfox/cli.py`（挂载）
- Test: `tests/unit/test_gem_synth_cli.py`

- [ ] **Step 1: 写失败测试 `tests/unit/test_gem_synth_cli.py`**

```python
"""jfox candidates list CLI 测试（用临时 KB + 真 candidate 笔记文件）。"""

import json
from typer.testing import CliRunner

from jfox.gem_synth.cli import candidates_app


def test_list_empty_kb(tmp_path, monkeypatch):
    # 指向空 KB
    monkeypatch.setenv("ZETTELKASTEN_ROOT", str(tmp_path))
    result = CliRunner().invoke(candidates_app, ["list"])
    # 没 candidate 也应正常退出（可能 exit 0 空表，或提示无）
    assert result.exit_code == 0


def test_list_shows_candidate(tmp_path, monkeypatch):
    # 这里只验证命令能跑（真建 candidate 笔记较重，留给集成测试）
    monkeypatch.setenv("ZETTELKASTEN_ROOT", str(tmp_path))
    result = CliRunner().invoke(candidates_app, ["list", "--format", "json"])
    assert result.exit_code == 0
```

> **说明**：candidate 笔记的完整建/读依赖 KB 初始化（较重）。单元测试只验证 CLI 能挂载、空库不崩。真实 candidate 列表验证放集成测试（Phase H）。

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 创建 `jfox/gem_synth/cli.py`**（仿 `jfox/fragment/cli.py` 的 subapp + `_json_console` 模式）

```python
"""CLI 子命令组：jfox candidates list"""

from __future__ import annotations

import json as _json

import typer
from rich.console import Console
from rich.table import Table

console = Console(legacy_windows=False)
_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)

candidates_app = typer.Typer(
    name="candidates",
    help="查看 L3 合成的候选知识宝石（破损级，待 L5 审阅）",
    no_args_is_help=True,
)


@candidates_app.command("list")
def list_cmd(
    status: str = typer.Option("pending", "--status", help="按 status 过滤 (pending/promoted/rejected)"),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="最低置信度"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """列出 candidate 笔记"""
    from ..note import list_notes
    from ..models import NoteType

    try:
        notes = list_notes(note_type=NoteType.CANDIDATE, limit=limit * 3)  # 多取以过滤
    except Exception as e:
        console.print(f"[red]读取 candidate 失败：{e}[/red]")
        raise typer.Exit(code=1)

    # 过滤 status / min_confidence
    rows = []
    for n in notes:
        if status and getattr(n, "status", None) != status and status != "all":
            continue
        conf = getattr(n, "confidence", None) or 0
        if conf < min_confidence:
            continue
        rows.append(
            {
                "id": n.id,
                "title": n.title,
                "confidence": conf,
                "knowledge_type": getattr(n, "knowledge_type", ""),
                "status": getattr(n, "status", ""),
                "gem_level": getattr(n, "gem_level", ""),
            }
        )
        if len(rows) >= limit:
            break

    if output_format == "json":
        _json_console.print(_json.dumps({"candidates": rows, "total": len(rows)}, ensure_ascii=False, indent=2))
        return

    table = Table(title=f"候选宝石（共 {len(rows)} 条）")
    for col in ("ID", "标题", "置信度", "类型", "状态", "等级"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["id"], r["title"], f"{r['confidence']:.2f}", r["knowledge_type"], r["status"], r["gem_level"])
    console.print(table)


__all__ = ["candidates_app"]
```

> **实现注意**：`list_notes` 的签名/返回（是否接受 `note_type=` + `limit=`，返回 Note 列表）需核对 `jfox/note.py`。若实际是 `list_notes(config, note_type)` 或别的，调整。candidate 字段（status/confidence/gem_level）从 Note 对象读 —— 这些字段在 Task A2 已加到 Note。

- [ ] **Step 4: 挂载到 `jfox/cli.py`**

在 `fragments_app` 挂载旁边（约第 106-108 行）加：
```python
from .gem_synth.cli import candidates_app  # noqa: E402
```
和
```python
app.add_typer(candidates_app, name="candidates", help="查看 L3 合成的候选知识宝石")
```

- [ ] **Step 5: 跑测试 + 验证挂载**

Run:
```bash
uv run pytest tests/unit/test_gem_synth_cli.py -v
uv run jfox candidates --help
```
Expected: 测试 PASS；help 显示 `list` 子命令

- [ ] **Step 6: 提交**

```bash
git add jfox/gem_synth/cli.py jfox/cli.py tests/unit/test_gem_synth_cli.py
git commit -m "feat(cli): add 'jfox candidates list' subcommand

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase H：集成 smoke test（用户手动跑）

### Task H1: 端到端合成流程

**Files:**
- Create: `tests/integration/test_gem_synth_flow.py`

- [ ] **Step 1: 写集成测试 `tests/integration/test_gem_synth_flow.py`**

```python
"""端到端：真实 transcript + fragments → 合成 → candidate 笔记。

标记 integration：依赖真实 daemon + claude 二进制 + 模型。
用户手动跑：uv run pytest tests/integration/test_gem_synth_flow.py -v -m integration
前置：jfox config set gem_synthesis.enabled true；daemon restart。
"""

import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_synthesize_one_anchor Produces_candidate(tmp_path, monkeypatch):
    """用真实 fragment + 临时 transcript，跑 synthesizer 全链路（含真 claude 调用）。"""
    from jfox.fragment.store import FragmentStore, default_db_path
    from jfox.gem_synth.synthesizer import synthesize_anchor
    from jfox.gem_synth.store import SynthesisLog
    from jfox.global_config import get_global_config_manager

    # 造一条 transcript
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        '{"type":"user","message":{"role":"user","content":"不对，这里应该用 patch 而不是 sed"},"timestamp":"2026-06-21T06:25:00","uuid":"u1"}\n'
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"好的，改用 patch"}]},"timestamp":"2026-06-21T06:25:10","uuid":"a1"}\n',
        encoding="utf-8",
    )
    # 造 fragment
    fstore = FragmentStore(db_path=tmp_path / "frag.db")
    fid = fstore.insert(
        "s-test", "correction", "UserPromptSubmit", "不对，这里应该用 patch 而不是 sed",
        {"transcript_path": str(transcript), "session_id": "s-test"},
    )
    fstore.close()

    anchor = {
        "fragment_id": fid,
        "session_id": "s-test",
        "timestamp": "2026-06-21 06:25:00",
        "content": "不对，这里应该用 patch 而不是 sed",
        "transcript_path": str(transcript),
        "metadata": {"transcript_path": str(transcript)},
    }
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    cfg = get_global_config_manager().get_gem_synthesis_config()
    if not cfg.enabled:
        pytest.skip("gem_synthesis 未启用；先 `jfox config set gem_synthesis.enabled true` 并 daemon restart")

    result = synthesize_anchor(anchor, log=log, cfg=cfg, kb=None)
    assert result is not None
    assert result["candidate_note_id"]
    assert log.is_processed(fid)
```

- [ ] **Step 2: 提交**

```bash
git add tests/integration/test_gem_synth_flow.py
git commit -m "test(gem-synth): end-to-end synthesis flow (integration, user-run)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 3: 给用户的手动验收清单**

不自动执行。贴给用户：

```bash
# 1. 启用 gem-synthesis
jfox config set gem_synthesis.enabled true   # 或编辑 ~/.zk_config.json
# 2. 重启 daemon（加载新循环 + 模型）
jfox daemon restart
# 3. 跑集成 smoke（真调 claude）
uv run pytest tests/integration/test_gem_synth_flow.py -v -m integration
# 4. 等一个 cycle（默认 30min）或手动触发后看产出
jfox candidates list
```

---

## Task I：收尾 — 回归 + lint + PR

- [ ] **Step 1: 全部 gem_synth 单测**

Run: `uv run pytest tests/unit/test_gem_synth_*.py tests/unit/test_note_type_candidate.py tests/unit/test_note_candidate_fields.py -v`
Expected: PASS

- [ ] **Step 2: fast 套件回归**

Run: `uv run pytest tests/unit/ -v 2>&1 | tail -20`
Expected: PASS（确认没破坏既有，尤其 models/note/search 改动）

- [ ] **Step 3: lint/format**

Run:
```bash
uv run black jfox/gem_synth/ jfox/models.py jfox/note.py jfox/global_config.py jfox/daemon/server.py jfox/cli.py tests/unit/test_gem_synth_*.py tests/unit/test_note_candidate*.py
uv run ruff check jfox/gem_synth/ jfox/models.py jfox/note.py jfox/global_config.py jfox/daemon/server.py jfox/cli.py tests/unit/test_gem_synth_*.py
```

- [ ] **Step 4: 更新 CLAUDE.md / AGENTS.md 模块表（加 gem_synth/）**

- [ ] **Step 5: 推送 + 开 PR**

```bash
git push -u origin feat/l3-gem-synthesis
gh pr create --title "feat: L3 宝石合成（碎裂→破损 candidate 笔记，#249 Layer 3）" \
  --body "实现 #249 Layer 3：daemon 异步循环围绕高信号锚点（correction/decision/AskUserQuestion），用 transcript 上下文 + permanent 笔记基准 + 独立 LLM 调用合成破损级 candidate 笔记。设计见 docs/superpowers/specs/2026-06-21-gem-synthesis-design.md，计划见 docs/superpowers/plans/2026-06-21-gem-synthesis.md。5 级 GemLevel 枚举预先建模（L3 仅产出 flawed）；置信度记录不丢弃；L4/L5 成熟与晋升留待后续。"
```

---

## Self-Review 结果

**1. Spec 覆盖**（对照 spec §1-9）：
- 三输入模型（fragments/transcript/permanent）→ Task B3/C1/D1/E2 ✅
- 锚点定义（correction/decision/AskUserQuestion）→ Task B3 ✅
- 合成管线 5 步 → Task E2 synthesizer ✅
- candidate 类型 + GemLevel 5 级 → Task A1/A2 ✅
- synthesis_log 去重 → Task B2 ✅
- daemon 循环触发 → Task F1 ✅
- 置信度记录不丢弃 → Task E2（confidence 存 frontmatter，无丢弃逻辑）✅
- L3 范围（不做 L4/L5）→ 未含 candidates review/promote ✅
- 独立 LLM（不耦合 auto_summary）→ Task E1 ✅

**2. 占位符扫描**：无 TBD；每个 code step 都有完整代码。部分步骤有"实现注意"（save_note/list_notes/HybridSearchEngine.search 返回结构实地核对）—— 这些是**需在实现时用 Read 确认现有签名**的明确指令，不是占位符。

**3. 类型/签名一致性**：
- `SynthesisLog.is_processed/mark_processed/filter_unprocessed` — B2 定义，B3/E2/F1 调用一致 ✅
- `find_anchors(fragments_db, log, anchor_types, ...)` — B3 定义，F1 调用一致 ✅
- `extract_turn_around(transcript_path, anchor_user_text)` — C1 定义，E2 调用一致 ✅
- `fetch_grounding(query, top_k, kb)` — D1 定义，E2 调用一致 ✅
- `synthesize_with_llm(turn_context, grounding, cfg)` — E1 定义，E2 调用一致 ✅
- `synthesize_anchor(anchor, log, cfg, kb)` — E2 定义，F1/H1 调用一致 ✅
- `gem_synth_loop(stop_event, interval_minutes)` / `_tick_once(stop_event)` — F1 定义，server.py 装配一致 ✅
- Note 新字段（gem_level/confidence/source_fragments/grounded_by/knowledge_type/status）— A2 定义，E2/G1 读写一致 ✅
