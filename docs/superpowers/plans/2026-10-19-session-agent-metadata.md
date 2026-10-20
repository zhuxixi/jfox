# Session Agent Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** session 笔记记录 `agent` / `session_file` / `agent_model` 三个字段，并把 pi 作为第三种 auto-summary 来源接入（覆盖官方目录与 agent-board 目录）。

**Architecture:** 笔记层加三个可选 frontmatter 字段（与 `source` 同构）；来源层复用既有 `SessionSource` 协议新增 `PiCodeSource`，pi 的解析拆成「纯函数（header / 活跃分支 / 对话 / 模型）+ 薄 I/O」两层；定位一律读首行 `id`，禁止文件名解析。

**Tech Stack:** Python 3.10+、Typer CLI、pytest、pi v3 JSONL session 格式。

## Global Constraints

- canonical agent 值：`claude-code` / `kimi-code` / `pi-coding-agent`；`--agent` 不校验枚举。
- 三字段只在非空时写入 frontmatter / JSON 输出。
- `session_file` 必须是绝对路径；不校验存在性（历史指针）。
- pi 的 session id 只从首行 `{"type":"session","id":...}` 读取，禁止从文件名推断。
- `session_sources` 默认 `["claude", "kimi", "pi"]`，`from_dict` 的 fallback 必须同步。
- 不扫 `~/.zima/temp/pjobs/*/pi-sessions/`。
- 不回填历史笔记。
- 每次 commit 用 conventional commits，按文件 stage，禁止 `git add -A`。

---

### Task 1: Note 三字段与序列化（A1）

**Files:**

- Modify: `jfox/models.py`（字段定义 + `to_markdown` / `from_markdown` / `to_dict` / `to_show_dict`）
- Test: `tests/unit/test_note_agent_fields.py`（新建）

**Interfaces:**

- Produces: `Note.agent: Optional[str]`、`Note.session_file: Optional[str]`、`Note.agent_model: Optional[str]`，由 Task 2 / Task 6 填充。

- [ ] **Step 1: 写失败测试**

```python
"""Note 的 agent / session_file / agent_model 三字段序列化。"""

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _note(**kwargs) -> Note:
    from datetime import datetime

    now = datetime(2026, 10, 19, 9, 0, 0)
    return Note(
        id="202610190900000001",
        title="会话",
        content="正文",
        type=NoteType.SESSION,
        created=now,
        updated=now,
        topic="demo",
        **kwargs,
    )


def test_roundtrip_keeps_agent_fields():
    note = _note(agent="pi-coding-agent", session_file="/tmp/s.jsonl", agent_model="p/m")
    parsed = Note.from_markdown(note.to_markdown())
    assert parsed.agent == "pi-coding-agent"
    assert parsed.session_file == "/tmp/s.jsonl"
    assert parsed.agent_model == "p/m"


def test_empty_fields_not_serialized():
    md = _note().to_markdown()
    assert "agent:" not in md
    assert "session_file:" not in md
    assert "agent_model:" not in md


def test_legacy_note_parses_as_none():
    note = _note()
    md = note.to_markdown()
    parsed = Note.from_markdown(md)
    assert parsed.agent is None and parsed.session_file is None and parsed.agent_model is None


def test_json_outputs_include_optional_fields():
    note = _note(agent="claude-code", session_file="/tmp/c.jsonl", agent_model="x/y")
    assert note.to_dict()["agent"] == "claude-code"
    assert note.to_show_dict()["session_file"] == "/tmp/c.jsonl"


def test_json_outputs_omit_empty_fields():
    d = _note().to_dict()
    assert "agent" not in d and "session_file" not in d and "agent_model" not in d
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_note_agent_fields.py -q`
Expected: FAIL（`Note` 不接受 `agent` 关键字）

- [ ] **Step 3: 实现**

`jfox/models.py` 字段区（`topic` 之后）：

```python
    agent: Optional[str] = None  # 产生会话的 coding agent（claude-code / kimi-code / pi-coding-agent）
    session_file: Optional[str] = None  # agent 原始 session 文件绝对路径
    agent_model: Optional[str] = None  # 会话使用的模型（provider/modelId）
```

`to_markdown()` 在 `if self.topic:` 之后追加：

```python
        if self.agent:
            frontmatter["agent"] = self.agent
        if self.session_file:
            frontmatter["session_file"] = self.session_file
        if self.agent_model:
            frontmatter["agent_model"] = self.agent_model
```

`from_markdown()` 构造参数追加：

```python
            agent=fm.get("agent"),
            session_file=fm.get("session_file"),
            agent_model=fm.get("agent_model"),
```

`to_dict()` 在 `return d` 前追加：

```python
        if self.agent:
            d["agent"] = self.agent
        if self.session_file:
            d["session_file"] = self.session_file
        if self.agent_model:
            d["agent_model"] = self.agent_model
```

`to_show_dict()` 在 `return d` 前追加同样的三行判断。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/unit/test_note_agent_fields.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add jfox/models.py tests/unit/test_note_agent_fields.py
git commit -m "feat(note): 新增 agent / session_file / agent_model 三个可选字段（#578）"
```

---

### Task 2: `jfox add` 三参数与 JSON 输出（A2）

**Files:**

- Modify: `jfox/utils.py`（两个纯函数）
- Modify: `jfox/note.py`（`create_note` 签名）
- Modify: `jfox/cli.py`（`add` / `_add_note_impl`）
- Test: `tests/unit/test_add_agent_fields.py`（新建）

**Interfaces:**

- Consumes: Task 1 的 `Note.agent` / `session_file` / `agent_model`。
- Produces: `normalize_agent(value) -> str`、`resolve_session_path(value) -> str`；`create_note(..., agent=, session_file=, agent_model=)`。

- [ ] **Step 1: 写失败测试**

```python
"""jfox add --agent / --session-path / --agent-model 行为。"""

import json

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _add(cli, *extra):
    return cli.run(
        "add",
        "正文",
        "--title",
        "会话",
        "--type",
        "session",
        "--topic",
        "t",
        *extra,
    )


def test_fields_written_to_frontmatter(cli):
    res = _add(
        cli,
        "--agent",
        "pi-coding-agent",
        "--session-path",
        "/tmp/x.jsonl",
        "--agent-model",
        "p/m",
    )
    assert res.returncode == 0, res.stderr
    from pathlib import Path

    path = Path(res.json()["note"]["filepath"])
    text = path.read_text(encoding="utf-8")
    assert "agent: pi-coding-agent" in text
    assert "session_file: /tmp/x.jsonl" in text
    assert "agent_model: p/m" in text


def test_fields_in_add_json(cli):
    res = _add(cli, "--agent", "kimi-code", "--session-path", "/tmp/k.jsonl")
    note = res.json()["note"]
    assert note["agent"] == "kimi-code"
    assert note["session_file"] == "/tmp/k.jsonl"


def test_empty_agent_rejected(cli):
    res = _add(cli, "--agent", "  ")
    assert res.returncode == 1


def test_relative_session_path_rejected(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "rel/path.jsonl")
    assert res.returncode == 1


def test_tilde_expanded(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "~/x.jsonl")
    assert res.json()["note"]["session_file"].startswith("/")


def test_nonexistent_absolute_path_accepted(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "/nope/gone.jsonl")
    assert res.returncode == 0
    assert res.json()["note"]["session_file"] == "/nope/gone.jsonl"


def test_show_json_exposes_fields(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "/tmp/s.jsonl")
    note_id = res.json()["id"]
    shown = cli.run("show", note_id)
    assert shown.json()["agent"] == "pi-coding-agent"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_add_agent_fields.py -q`
Expected: FAIL（`No such option: --agent`）

- [ ] **Step 3: 实现纯函数（`jfox/utils.py`）**

```python
def normalize_agent(value: str) -> str:
    """trim 后必须非空；不做枚举校验，允许未来 agent。"""
    agent = (value or "").strip()
    if not agent:
        raise ValueError("--agent 不能为空")
    return agent


def resolve_session_path(value: str) -> str:
    """展开 ~ 并要求绝对路径；不校验存在性（历史指针，文件可能已删除）。"""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("--session-path 必须是绝对路径")
    return str(path)
```

- [ ] **Step 4: 实现 `create_note` 透传（`jfox/note.py`）**

签名追加三个关键字参数，并在 `Note(...)` 构造里透传：

```python
def create_note(
    content: str,
    title: Optional[str] = None,
    note_type: NoteType = NoteType.FLEETING,
    tags: Optional[List[str]] = None,
    links: Optional[List[str]] = None,
    source: Optional[str] = None,
    topic: Optional[str] = None,
    agent: Optional[str] = None,
    session_file: Optional[str] = None,
    agent_model: Optional[str] = None,
) -> Note:
```

```python
        source=source,
        topic=topic,
        agent=agent,
        session_file=session_file,
        agent_model=agent_model,
```

- [ ] **Step 5: 实现 CLI 选项（`jfox/cli.py`）**

`add()` 参数区（`topic` 之后）加：

```python
    agent: Optional[str] = typer.Option(
        None, "--agent", help="产生该会话的 coding agent（claude-code / kimi-code / pi-coding-agent）"
    ),
    session_path: Optional[str] = typer.Option(
        None, "--session-path", help="agent 原始 session 文件绝对路径"
    ),
    agent_model: Optional[str] = typer.Option(
        None, "--agent-model", help="该会话使用的模型（provider/modelId）"
    ),
```

调用处传入 `_add_note_impl(..., agent=agent, session_file=session_path, agent_model=agent_model)`；`_add_note_impl` 签名同步加三个参数，开头做校验：

```python
    from .utils import normalize_agent, resolve_session_path

    if agent is not None:
        agent = normalize_agent(agent)
    if session_path is not None:
        session_file = resolve_session_path(session_path)
    else:
        session_file = None
    if agent_model is not None:
        agent_model = agent_model.strip() or None
```

`create_note(...)` 调用追加 `agent=agent, session_file=session_file, agent_model=agent_model`。

`result["note"]` 构造后按非空追加：

```python
        if agent:
            result["note"]["agent"] = agent
        if session_file:
            result["note"]["session_file"] = session_file
        if agent_model:
            result["note"]["agent_model"] = agent_model
```

- [ ] **Step 6: 运行确认通过**

Run: `uv run pytest tests/unit/test_add_agent_fields.py -q`
Expected: PASS（7 passed）

- [ ] **Step 7: Commit**

```bash
git add jfox/utils.py jfox/note.py jfox/cli.py tests/unit/test_add_agent_fields.py
git commit -m "feat(cli): jfox add 支持 --agent / --session-path / --agent-model（#578）"
```

---

### Task 3: pi 提取器纯函数（A3）

**Files:**

- Modify: `jfox/auto_summary/extractor.py`（`ExtractedDialog.agent_model`）
- Create: `jfox/auto_summary/pi_extractor.py`
- Test: `tests/unit/test_pi_extractor.py`（新建）

**Interfaces:**

- Consumes: `extractor.DEFAULT_MAX_DIALOG_CHARS`、`extractor._truncate`、`ExtractedDialog`。
- Produces: `parse_pi_header(line)`、`active_branch(entries)`、`dialog_from_branch(branch, max_chars)`、`model_from_branch(branch)`、`extract_pi_dialog(path)`。

- [ ] **Step 1: 写失败测试**

```python
"""pi session 解析纯函数。"""

import json

import pytest

from jfox.auto_summary.pi_extractor import (
    active_branch,
    dialog_from_branch,
    extract_pi_dialog,
    model_from_branch,
    parse_pi_header,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

HEADER = {"type": "session", "version": 3, "id": "sess-1", "timestamp": "2026-10-19T00:00:00.000Z", "cwd": "/repo/proj"}


def _msg(mid, parent, role, text, ts="2026-10-19T00:01:00.000Z", model=None):
    msg = {"role": role, "content": [{"type": "text", "text": text}]}
    if model:
        msg["model"] = model
    return {"type": "message", "id": mid, "parentId": parent, "timestamp": ts, "message": msg}


def test_header_requires_session_type_and_id():
    assert parse_pi_header(json.dumps(HEADER))["id"] == "sess-1"
    assert parse_pi_header(json.dumps({"type": "message", "id": "x"})) is None
    assert parse_pi_header("not json") is None


def test_active_branch_follows_parent_chain():
    entries = [
        HEADER,
        _msg("a", None, "user", "hello"),
        _msg("b", "a", "assistant", "hi"),
        _msg("c", "a", "assistant", "abandoned"),
        _msg("d", "b", "user", "next"),
    ]
    ids = [e["id"] for e in active_branch(entries)]
    assert ids == ["sess-1", "a", "b", "d"]


def test_active_branch_falls_back_on_broken_chain():
    entries = [HEADER, _msg("a", None, "user", "hello"), _msg("b", "missing", "assistant", "x")]
    assert active_branch(entries) == entries


def test_dialog_reads_nested_message_and_drops_thinking():
    branch = [
        HEADER,
        _msg("a", None, "user", "hello"),
        {
            "type": "message",
            "id": "b",
            "parentId": "a",
            "timestamp": "2026-10-19T00:02:00.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret"},
                    {"type": "text", "text": "answer"},
                    {"type": "toolCall", "name": "bash"},
                ],
            },
        },
        {"type": "message", "id": "c", "parentId": "b", "message": {"role": "toolResult", "content": "x"}},
    ]
    text, users, assistants, ended, truncated = dialog_from_branch(branch)
    assert "hello" in text and "answer" in text and "secret" not in text
    assert (users, assistants) == (1, 1)
    assert ended == "2026-10-19T00:02:00.000Z"
    assert truncated is False


def test_model_takes_last_model_change():
    branch = [
        HEADER,
        {"type": "model_change", "provider": "a", "modelId": "m1"},
        {"type": "model_change", "provider": "b", "modelId": "m2"},
    ]
    assert model_from_branch(branch) == "b/m2"


def test_extract_dialog_from_file(tmp_path):
    p = tmp_path / "view_abc.jsonl"
    rows = [HEADER, _msg("a", None, "user", "hello"), _msg("b", "a", "assistant", "hi", model="x/y")]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    result = extract_pi_dialog(p)
    assert result.cwd == "/repo/proj"
    assert result.project_dir_name == "proj"
    assert result.user_turn_count == 1 and result.assistant_turn_count == 1
    assert result.started_at == HEADER["timestamp"]
    assert result.ended_at == "2026-10-19T00:01:00.000Z"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_pi_extractor.py -q`
Expected: FAIL（`ModuleNotFoundError: jfox.auto_summary.pi_extractor`）

- [ ] **Step 3: 实现**

`jfox/auto_summary/extractor.py` 的 `ExtractedDialog` 增加字段：

```python
    agent_model: Optional[str] = None  # 会话使用的模型（provider/modelId）
```

新建 `jfox/auto_summary/pi_extractor.py`：

```python
"""
pi coding agent session 解析：首行 header + v3 树结构活跃分支 + message 抽取。

关键事实（本机实测 + pi docs/session-format.md）：
- 首行 {"type":"session","id":...} 是唯一可靠的 id 来源，文件名不可用（view_<hash>.jsonl）
- message 的角色与内容嵌套在 entry["message"] 下
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from .extractor import DEFAULT_MAX_DIALOG_CHARS, ExtractedDialog, _truncate

logger = logging.getLogger(__name__)


def parse_pi_header(line: str) -> Optional[dict]:
    """解析首行；必须是 type=session 且 id 为非空字符串。"""
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict) or rec.get("type") != "session":
        return None
    sid = rec.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    return rec


def active_branch(entries: list) -> list:
    """从最后一个条目沿 parentId 回溯；断链或成环时回退为文件顺序。"""
    by_id = {e["id"]: e for e in entries if isinstance(e.get("id"), str)}
    if not by_id:
        return entries
    leaf = entries[-1]
    if not isinstance(leaf.get("id"), str):
        return entries
    chain, seen, cur = [], set(), leaf
    while isinstance(cur, dict) and isinstance(cur.get("id"), str):
        cid = cur["id"]
        if cid in seen:
            return entries
        seen.add(cid)
        chain.append(cur)
        parent = cur.get("parentId")
        if parent is None:
            break
        if parent not in by_id:
            return entries
        cur = by_id[parent]
    chain.reverse()
    return chain


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def dialog_from_branch(
    branch: Iterable[dict], max_chars: int = DEFAULT_MAX_DIALOG_CHARS
) -> Tuple[str, int, int, Optional[str], bool]:
    """返回 (dialog_text, user_turns, assistant_turns, ended_at, truncated)。"""
    turns: list = []
    user_n = assistant_n = 0
    ended_at: Optional[str] = None
    for entry in branch:
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        ts = entry.get("timestamp")
        if isinstance(ts, str):
            ended_at = ts
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _text_from_content(msg.get("content"))
        if not text:
            continue
        if role == "user":
            user_n += 1
        else:
            assistant_n += 1
        turns.append(f"## {role}\n\n{text}")
    text, truncated = _truncate("\n\n---\n\n".join(turns), max_chars)
    return text, user_n, assistant_n, ended_at, truncated


def model_from_branch(branch: Iterable[dict]) -> Optional[str]:
    """多模型会话取最后一次 model_change。"""
    model: Optional[str] = None
    for entry in branch:
        if not isinstance(entry, dict) or entry.get("type") != "model_change":
            continue
        provider, model_id = entry.get("provider"), entry.get("modelId")
        if isinstance(provider, str) and isinstance(model_id, str) and provider and model_id:
            model = f"{provider}/{model_id}"
    return model


def extract_pi_dialog(path: Path, max_dialog_chars: int = DEFAULT_MAX_DIALOG_CHARS) -> ExtractedDialog:
    result = ExtractedDialog()
    entries: list = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.debug("pi session 第 %d 行解析失败: %s", line_no, e)
                    continue
                if isinstance(rec, dict):
                    entries.append(rec)
    except OSError as e:
        logger.warning("读取 pi session 失败 %s: %s", path, e)
        return result

    if not entries:
        return result
    header = entries[0]
    cwd = header.get("cwd")
    if isinstance(cwd, str) and cwd:
        result.cwd = cwd
        result.project_dir_name = Path(cwd).name
    ts = header.get("timestamp")
    if isinstance(ts, str):
        result.started_at = ts

    branch = active_branch(entries)
    (
        result.dialog_text,
        result.user_turn_count,
        result.assistant_turn_count,
        ended_at,
        result.truncated,
    ) = dialog_from_branch(branch, max_dialog_chars)
    if ended_at:
        result.ended_at = ended_at
    result.agent_model = model_from_branch(branch)
    if result.project_dir_name is None:
        result.project_dir_name = path.parent.name
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/unit/test_pi_extractor.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add jfox/auto_summary/extractor.py jfox/auto_summary/pi_extractor.py tests/unit/test_pi_extractor.py
git commit -m "feat(auto-summary): pi session 解析纯函数（header/活跃分支/对话/模型）（#578）"
```

---

### Task 4: pi 扫描与来源实现（A4）

**Files:**

- Modify: `jfox/auto_summary/scanner.py`（`SessionFile.agent` / `agent_model`）
- Create: `jfox/auto_summary/pi_source.py`
- Test: `tests/unit/test_pi_source.py`（新建）

**Interfaces:**

- Consumes: `pi_extractor.parse_pi_header` / `extract_pi_dialog`。
- Produces: `PiCodeSource(roots)`、`iter_pi_session_files(roots, cfg, now=None)`。

- [ ] **Step 1: 写失败测试**

```python
"""pi session 扫描：两类根目录、过滤、blocklist、同 id 去重。"""

import json
import os
import time

import pytest

from jfox.auto_summary.pi_source import PiCodeSource, iter_pi_session_files
from jfox.global_config import AutoSummaryConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write(path, sid, cwd="/repo/proj", pad=6000):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"type": "session", "version": 3, "id": sid, "timestamp": "2026-10-19T00:00:00Z", "cwd": cwd}
    msg = {
        "type": "message",
        "id": "m1",
        "parentId": None,
        "timestamp": "2026-10-19T00:01:00Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }
    path.write_text(json.dumps(header) + "\n" + json.dumps(msg) + "\n" + "x" * pad, encoding="utf-8")
    old = time.time() - 3600
    os.utime(path, (old, old))


def test_scans_official_two_level_layout(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "--repo-proj--" / "t1_uuid-1.jsonl", "uuid-1")
    cfg = AutoSummaryConfig()
    found = list(iter_pi_session_files([root], cfg))
    assert [s.session_id for s in found] == ["uuid-1"]
    assert found[0].agent == "pi-coding-agent"
    assert found[0].project_dir_name == "proj"


def test_scans_agent_board_flat_layout_with_view_names(tmp_path):
    root = tmp_path / "agent-board" / "sessions"
    _write(root / "view_abc.jsonl", "uuid-2", cwd="/repo/jfox")
    found = list(iter_pi_session_files([root], AutoSummaryConfig()))
    assert found[0].session_id == "uuid-2"
    assert found[0].project_dir_name == "jfox"


def test_skips_blocklisted_cwd(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid3.jsonl", "uuid-3", cwd="/tmp/jfox-auto-summary-runs/x")
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_skips_small_files(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid4.jsonl", "uuid-4", pad=10)
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_skips_non_header_files(tmp_path):
    root = tmp_path / "sessions"
    p = root / "a" / "bad.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("x" * 6000, encoding="utf-8")
    assert list(iter_pi_session_files([root], AutoSummaryConfig())) == []


def test_dedupes_same_id_keeping_newest(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_new.jsonl", "uuid-5")
    _write(root / "b" / "t_old.jsonl", "uuid-5")
    old = time.time() - 7200
    os.utime(root / "b" / "t_old.jsonl", (old, old))
    found = list(iter_pi_session_files([root], AutoSummaryConfig()))
    assert len(found) == 1 and found[0].path.name == "t_new.jsonl"


def test_extract_dialog_delegates(tmp_path):
    root = tmp_path / "sessions"
    _write(root / "a" / "t_uuid6.jsonl", "uuid-6")
    source = PiCodeSource([root])
    sf = list(source.iter_sessions(AutoSummaryConfig()))[0]
    result = source.extract_dialog(sf)
    assert result.cwd == "/repo/proj"
    assert result.user_turn_count == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_pi_source.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`jfox/auto_summary/scanner.py` 的 `SessionFile` 追加字段（保持默认值不变）：

```python
    agent: str = "claude-code"  # 产生会话的 coding agent
    agent_model: Optional[str] = None  # 会话使用的模型（provider/modelId）
```

新建 `jfox/auto_summary/pi_source.py`：

```python
"""
pi coding agent session 来源：扫描官方目录（两层）与 agent-board 目录（扁平）。

id 一律读首行 session 记录，不解析文件名（agent-board 的 view_<hash>.jsonl 与 id 无关）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence

from ..global_config import AutoSummaryConfig
from .extractor import ExtractedDialog
from .pi_extractor import extract_pi_dialog, parse_pi_header
from .scanner import DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS, SessionFile, _is_blocked_project

logger = logging.getLogger(__name__)


def _candidate_paths(root: Path) -> list:
    """官方两层（root/<encoded-cwd>/*.jsonl）+ agent-board 扁平（root/*.jsonl）。

    不递归更深层：sessions/<viewId>/<uuid>/run-0/session.jsonl 是 subagent transcript。
    """
    return sorted(root.glob("*.jsonl")) + sorted(root.glob("*/*.jsonl"))


def _read_header(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_pi_header(f.readline().strip())
    except OSError as e:
        logger.debug("读取 pi session 首行失败 %s: %s", path, e)
        return None


def iter_pi_session_files(
    roots: Sequence[Path],
    cfg: AutoSummaryConfig,
    now: Optional[float] = None,
) -> Iterator[SessionFile]:
    now = time.time() if now is None else now
    idle_sec = max(0, cfg.idle_threshold_minutes) * 60
    min_size = max(0, cfg.min_session_size_kb) * 1024
    max_size = max(0, cfg.max_session_size_mb) * 1024 * 1024
    skip_sec = max(0, cfg.skip_after_days) * 86400

    seen: dict = {}
    for root in roots:
        if not root.is_dir():
            logger.info("跳过 pi 根目录：不存在 %s", root)
            continue
        for path in _candidate_paths(root):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError as e:
                logger.debug("stat pi session 失败 %s: %s", path, e)
                continue
            size, mtime = stat.st_size, stat.st_mtime
            age = now - mtime
            if size < min_size:
                continue
            if max_size and size > max_size:
                continue
            if age < idle_sec:
                continue
            if skip_sec and age > skip_sec:
                continue

            header = _read_header(path)
            if header is None:
                continue
            cwd = header.get("cwd")
            if isinstance(cwd, str) and _is_blocked_project(
                cwd, DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS
            ):
                continue

            sid = header["id"]
            project = Path(cwd).name if isinstance(cwd, str) and cwd else path.parent.name
            sf = SessionFile(
                session_id=sid,
                project_dir_name=project,
                path=path,
                mtime=mtime,
                size_bytes=size,
                source="pi",
                agent="pi-coding-agent",
            )
            prev = seen.get(sid)
            if prev is None or sf.mtime > prev.mtime:
                seen[sid] = sf

    yield from seen.values()


class PiCodeSource:
    """pi session 来源：扫描 + 委派给 pi_extractor。"""

    name = "pi"

    def __init__(self, roots: Sequence[Path]):
        self.roots = list(roots)

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        yield from iter_pi_session_files(self.roots, cfg)

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        return extract_pi_dialog(sf.path)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/unit/test_pi_source.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add jfox/auto_summary/scanner.py jfox/auto_summary/pi_source.py tests/unit/test_pi_source.py
git commit -m "feat(auto-summary): PiCodeSource 扫描官方与 agent-board 目录（#578）"
```

---

### Task 5: 配置默认值与来源工厂（A5）

**Files:**

- Modify: `jfox/global_config.py`（字段 + `from_dict` 两处）
- Modify: `jfox/auto_summary/sources.py`（根目录解析 + 工厂分支 + `extract_dialog_for`）
- Test: `tests/unit/test_auto_summary_config_sources.py`（改三处旧默认 + 新增断言）

**Interfaces:**

- Consumes: Task 4 的 `PiCodeSource`。
- Produces: `pi_session_dirs(cfg) -> list[Path]`、`resolve_pi_session_dirs(cfg) -> list[Path]`。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_auto_summary_config_sources.py` 末尾追加：

```python
def test_default_includes_pi_everywhere():
    assert AutoSummaryConfig().session_sources == ["claude", "kimi", "pi"]
    assert AutoSummaryConfig.from_dict({}).session_sources == ["claude", "kimi", "pi"]
    assert AutoSummaryConfig.from_dict({"session_sources": None}).session_sources == [
        "claude",
        "kimi",
        "pi",
    ]


def test_pi_session_dirs_roundtrip():
    cfg = AutoSummaryConfig(pi_session_dirs=["/tmp/pi1", "/tmp/pi2"])
    cfg2 = AutoSummaryConfig.from_dict(cfg.to_dict())
    assert cfg2.pi_session_dirs == ["/tmp/pi1", "/tmp/pi2"]


def test_pi_session_dirs_non_list_becomes_none():
    assert AutoSummaryConfig.from_dict({"pi_session_dirs": "oops"}).pi_session_dirs is None
```

并把三处旧断言（第 6 / 13 / 26 行的 `["claude", "kimi"]`）改为三项。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_auto_summary_config_sources.py -q`
Expected: FAIL（默认仍为两项）

- [ ] **Step 3: 实现配置**

`jfox/global_config.py`：

```python
    session_sources: List[str] = field(default_factory=lambda: ["claude", "kimi", "pi"])  # 启用的扫描来源
    kimi_sessions_dir: Optional[str] = None  # None → ~/.kimi-code/sessions
    pi_session_dirs: Optional[List[str]] = None  # None → 官方目录 + agent-board 目录
```

`from_dict` 的 `session_sources` 分支改为：

```python
            session_sources=(
                list(data["session_sources"])
                if isinstance(data.get("session_sources"), list)
                else ["claude", "kimi", "pi"]
            ),
            kimi_sessions_dir=data.get("kimi_sessions_dir"),
            pi_session_dirs=(
                list(data["pi_session_dirs"])
                if isinstance(data.get("pi_session_dirs"), list)
                else None
            ),
```

- [ ] **Step 4: 实现来源工厂**

`jfox/auto_summary/sources.py` 增加：

```python
import os


def resolve_pi_session_dirs(cfg: AutoSummaryConfig) -> list[Path]:
    """显式配置优先；否则官方根 + agent-board 根，尊重两个 env，去重。"""
    if cfg.pi_session_dirs:
        return [Path(p).expanduser().resolve() for p in cfg.pi_session_dirs]

    official = Path(
        os.environ.get("PI_CODING_AGENT_SESSION_DIR") or Path.home() / ".pi" / "agent" / "sessions"
    ).expanduser().resolve()
    board_root = Path(
        os.environ.get("AGENT_BOARD_ROOT") or Path.home() / ".pi" / "agent" / "agent-board"
    ).expanduser().resolve()
    board = (board_root / "sessions").resolve()

    dirs: list[Path] = []
    for d in (official, board):
        if d not in dirs:
            dirs.append(d)
    return dirs
```

`get_sources()` 的 `elif name == "kimi":` 之后追加：

```python
        elif name == "pi":
            roots = [d for d in resolve_pi_session_dirs(cfg) if d.is_dir()]
            if roots:
                sources.append(PiCodeSource(roots))
            else:
                logger.info("跳过 pi 来源：目录均不存在 %s", resolve_pi_session_dirs(cfg))
```

`extract_dialog_for()` 的 kimi 分支后追加：

```python
    if sf.source == "pi":
        return PiCodeSource([sf.path.parent]).extract_dialog(sf)
```

文件头 import 增加 `from .pi_source import PiCodeSource`。

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/unit/test_auto_summary_config_sources.py tests/unit/test_session_source.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/global_config.py jfox/auto_summary/sources.py tests/unit/test_auto_summary_config_sources.py
git commit -m "feat(auto-summary): pi 来源配置、根目录解析与工厂接入（#578）"
```

---

### Task 6: 三来源模型提取与 runner 落库（A6）

**Files:**

- Modify: `jfox/auto_summary/extractor.py`（claude 模型）
- Modify: `jfox/auto_summary/kimi_source.py`（kimi 模型）
- Modify: `jfox/auto_summary/runner.py`（透传、prompt 措辞、topic 兜底）
- Test: `tests/unit/test_auto_summary_runner.py`（追加）

**Interfaces:**

- Consumes: Task 1 的 Note 字段、Task 4 的 `SessionFile.agent`。
- Produces: 笔记三字段实际写入；`SYSTEM_PROMPT` 与用户 prompt 去 Claude 化；topic 兜底 `f"{sf.agent}-session"`。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_auto_summary_runner.py` 追加（复用文件内既有 `_make_session_jsonl` / `_make_popen_mock` / fixtures）：

```python
from dataclasses import replace


def test_summarize_one_passes_agent_fields(tmp_path, ledger, fake_cfg):
    sf = replace(_make_session_jsonl(tmp_path, sid="agent001"), agent="pi-coding-agent")
    inner = {"skip": False, "title": "T", "topic": "", "summary_md": "S", "tags": []}
    fake_stdout = json.dumps({"result": json.dumps(inner)})

    with (
        patch.object(runner_module, "_resolve_claude_binary", return_value="claude"),
        patch("subprocess.Popen", return_value=_make_popen_mock(stdout=fake_stdout)),
        patch.object(runner_module, "_save_session_note", return_value="n1") as save,
    ):
        result = summarize_one(sf, cfg=fake_cfg, ledger=ledger)

    assert result.outcome == SummaryOutcome.SUCCESS
    kwargs = save.call_args.kwargs
    assert kwargs["agent"] == "pi-coding-agent"
    assert kwargs["session_file"] == str(sf.path)
    assert kwargs["topic"] == "pi-coding-agent-session"  # LLM 未给 topic 时的兜底


def test_save_session_note_writes_fields(cli):
    from jfox.note import load_note_by_id

    note_id = runner_module._save_session_note(
        "正文",
        "T",
        ["session"],
        "t",
        cli.kb_name,
        agent="pi-coding-agent",
        session_file="/tmp/s.jsonl",
        agent_model="p/m",
    )
    note = load_note_by_id(note_id)
    assert note.agent == "pi-coding-agent"
    assert note.session_file == "/tmp/s.jsonl"
    assert note.agent_model == "p/m"


def test_prompts_are_source_neutral():
    from jfox.auto_summary.runner import SYSTEM_PROMPT

    assert "Claude Code" not in SYSTEM_PROMPT
```

说明：`cli` fixture 已初始化并注册临时 KB，因此直接传 `target_kb=cli.kb_name`，不要在测试里再包 `use_kb(None)`（会切回默认库）。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_auto_summary_runner.py -q`
Expected: FAIL（note 无 agent 字段 / SYSTEM_PROMPT 含 Claude Code）

- [ ] **Step 3: 实现模型提取**

`extractor.py` 循环内、`_extract_role_and_text` 之前追加：

```python
                msg = rec.get("message")
                if isinstance(msg, dict):
                    model = msg.get("model")
                    if isinstance(model, str) and model:
                        result.agent_model = model
```

`kimi_source.py` 循环内追加：

```python
                    if t == "llm.request":
                        provider, model = rec.get("provider"), rec.get("model")
                        if isinstance(provider, str) and isinstance(model, str):
                            result.agent_model = f"{provider}/{model}"
                    elif t == "profile.bind" and result.agent_model is None:
                        alias = rec.get("modelAlias")
                        if isinstance(alias, str) and alias:
                            result.agent_model = alias
```

- [ ] **Step 4: 实现 runner**

`runner.py` 的 `_save_session_note` 增加参数并透传：

```python
def _save_session_note(
    content: str,
    title: str,
    tags: list,
    topic: str,
    target_kb: Optional[str],
    agent: Optional[str] = None,
    session_file: Optional[str] = None,
    agent_model: Optional[str] = None,
) -> str:
```

```python
            topic=topic,
            agent=agent,
            session_file=session_file,
            agent_model=agent_model,
```

`summarize_one()` 的 `topic` 兜底改为：

```python
    topic = (parsed.get("topic") or "").strip() or f"{session_file.agent}-session"
```

调用处改为：

```python
            agent=session_file.agent,
            session_file=str(session_file.path),
            agent_model=extracted.agent_model,
```

`SYSTEM_PROMPT` 与 `_build_user_prompt()` 里所有「Claude Code 会话」改为「coding agent 会话」，示例：

```python
SYSTEM_PROMPT = """你是知识库归档助手。我会通过用户消息提供一段 coding agent 会话的对话记录（可能被截断）。
```

```python
        "# coding agent 会话摘要请求\n\n"
```

- [ ] **Step 5: 运行确认通过**

Run: `uv run pytest tests/unit/test_auto_summary_runner.py tests/unit/test_kimi_extractor.py tests/unit/test_auto_summary_extractor.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/auto_summary/extractor.py jfox/auto_summary/kimi_source.py jfox/auto_summary/runner.py tests/unit/test_auto_summary_runner.py
git commit -m "feat(auto-summary): 笔记记录 agent/路径/模型，prompt 去 Claude 化（#578）"
```

---

### Task 7: pi 端到端集成测试（A7）

**Files:**

- Test: `tests/integration/test_auto_summary_pi.py`（新建）

**Interfaces:**

- Consumes: Task 4 / 5 / 6 全部实现。

- [ ] **Step 1: 写测试**

```python
"""集成测试：pi session 端到端 scan → summarize（mock claude）。"""

import json
import os
from pathlib import Path

import pytest

from jfox.auto_summary import runner
from jfox.auto_summary.ledger import Ledger
from jfox.global_config import AutoSummaryConfig

pytestmark = pytest.mark.integration


def _seed(root: Path, sid: str = "uuid-1", age_secs: int = 3600) -> Path:
    path = root / "view_abc.jsonl"
    rows = [
        {"type": "session", "version": 3, "id": sid, "timestamp": "2026-10-19T00:00:00Z", "cwd": "/repo/proj"},
        {"type": "model_change", "provider": "deepseek", "modelId": "deepseek-flash"},
        {
            "type": "message",
            "id": "m1",
            "parentId": None,
            "timestamp": "2026-10-19T00:01:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "fix bug"}]},
        },
        {
            "type": "message",
            "id": "m2",
            "parentId": "m1",
            "timestamp": "2026-10-19T00:02:00Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n" + "x" * 6000, encoding="utf-8")
    old = os.path.getmtime(path) - age_secs
    os.utime(path, (old, old))
    return path


def test_pi_session_end_to_end(tmp_path, cli):
    root = tmp_path / "sessions"
    root.mkdir()
    session_path = _seed(root)
    cfg = AutoSummaryConfig(
        session_sources=["pi"], pi_session_dirs=[str(root)], target_kb=cli.kb_name
    )
    ledger = Ledger(path=tmp_path / "ledger.json")

    pending = runner.scan_pending(cfg=cfg, ledger=ledger)
    assert [p.session_id for p in pending] == ["uuid-1"]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        runner,
        "_invoke_claude",
        lambda extracted_dialog_text, cfg: json.dumps(
            {"skip": False, "title": "Pi 会话", "topic": "", "summary_md": "## 背景\n x", "tags": []}
        ),
    )
    try:
        result = runner.summarize_one(pending[0], cfg=cfg, ledger=ledger)
    finally:
        monkeypatch.undo()
    assert result.outcome == runner.SummaryOutcome.SUCCESS

    from jfox.note import load_note_by_id

    note = load_note_by_id(result.note_id)
    assert note.agent == "pi-coding-agent"
    assert note.session_file == str(session_path)
    assert note.agent_model == "deepseek/deepseek-flash"
    assert note.topic == "pi-coding-agent-session"
    assert ledger.get("pi:uuid-1") is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/integration/test_auto_summary_pi.py -q`
Expected: FAIL（实现缺失；若 Task 1–6 已完成则应直接通过）

- [ ] **Step 3: 运行确认通过**

Run: `uv run pytest tests/integration/test_auto_summary_pi.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_auto_summary_pi.py
git commit -m "test(auto-summary): pi session 端到端集成测试（#578）"
```

---

### Task 8: skills 与文档（A9）

**Files:**

- Modify: `skills-recommend/pi/jfox-session-summary/SKILL.md`
- Modify: `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md`
- Modify: `packages/cc-plugin/skills/session-summary/SKILL.md`
- Modify: `packages/kimi-plugin/skills/jfox-session-summary/SKILL.md`
- Modify: `skills-recommend/pi/jfox-common/SKILL.md`、`skills-recommend/kimi-cli/jfox-common/SKILL.md`
- Modify: `packages/cc-plugin/skills/manage/SKILL.md`、`packages/kimi-plugin/skills/jfox-manage/SKILL.md`
- Modify: `docs/json-schemas.md`、`docs/cli-descriptions.yaml`、`README.md`、`CLAUDE.md`
- Test: `tests/unit/test_session_summary_skill_docs.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""session summary skill / 参数清单 / JSON schema 文档的字段断言。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[2]

SKILLS = [
    ROOT / "skills-recommend/pi/jfox-session-summary/SKILL.md",
    ROOT / "skills-recommend/kimi-cli/jfox-session-summary/SKILL.md",
    ROOT / "packages/cc-plugin/skills/session-summary/SKILL.md",
    ROOT / "packages/kimi-plugin/skills/jfox-session-summary/SKILL.md",
]

PARAM_LISTS = [
    ROOT / "skills-recommend/pi/jfox-common/SKILL.md",
    ROOT / "skills-recommend/kimi-cli/jfox-common/SKILL.md",
    ROOT / "packages/cc-plugin/skills/manage/SKILL.md",
    ROOT / "packages/kimi-plugin/skills/jfox-manage/SKILL.md",
]


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_session_skill_documents_agent_options(path):
    text = path.read_text(encoding="utf-8")
    for flag in ("--agent", "--session-path", "--agent-model"):
        assert flag in text, f"{path} 缺 {flag}"


@pytest.mark.parametrize("path", PARAM_LISTS, ids=lambda p: str(p).split("/")[-2])
def test_param_lists_document_agent_options(path):
    text = path.read_text(encoding="utf-8")
    for flag in ("--agent", "--session-path", "--agent-model"):
        assert flag in text, f"{path} 缺 {flag}"


def test_pi_skill_uses_env_session_file():
    text = SKILLS[0].read_text(encoding="utf-8")
    assert "pi-coding-agent" in text
    assert "PI_SESSION_FILE" in text


def test_json_schema_docs_include_new_fields():
    text = (ROOT / "docs/json-schemas.md").read_text(encoding="utf-8")
    for field in ("agent", "session_file", "agent_model"):
        assert field in text
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_session_summary_skill_docs.py -q`
Expected: FAIL（skill 缺新参数）

- [ ] **Step 3: 更新 skills**

pi skill（`skills-recommend/pi/jfox-session-summary/SKILL.md`）的写入命令改为：

```bash
jfox add --content-file /tmp/session-summary.md \
  --title "Session: <topic>" \
  --type session \
  --topic <short-topic> \
  --tag session \
  --agent pi-coding-agent \
  --session-path "$PI_SESSION_FILE" \
  --agent-model "${PI_PROVIDER}/${PI_MODEL}" \
  --kb <kb-name> \
  --format json
```

并补一段说明：`PI_SESSION_FILE` 是当前 session 文件绝对路径（agent-board 托管会话也指向正确位置）；变量为空时省略后两个参数。

cc / kimi 两个 skill 与 kimi-cli skill 分别加 `--agent claude-code` / `--agent kimi-code`，并注明无法稳定取得 transcript 路径时省略 `--session-path`。

四份参数清单（`jfox-common` ×2、`manage` §4.2、`jfox-manage` §4.2）在 `jfox add` 选项表补三行：

```text
--agent <str>          产生该会话的 coding agent（claude-code / kimi-code / pi-coding-agent）
--session-path <path>  agent 原始 session 文件绝对路径
--agent-model <str>    该会话使用的模型（provider/modelId）
```

`docs/json-schemas.md` 的 `add` 行 `note{...}` 与 `show` 行可选字段补 `agent` / `session_file` / `agent_model`；`docs/cli-descriptions.yaml` 的 auto-summary 描述改为 `Manage automatic summaries of completed coding-agent sessions.`；`README.md` 与 `CLAUDE.md` 的 auto-summary 描述同步为三来源（claude / kimi / pi）。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/unit/test_session_summary_skill_docs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills-recommend/pi/jfox-session-summary/SKILL.md skills-recommend/kimi-cli/jfox-session-summary/SKILL.md packages/cc-plugin/skills/session-summary/SKILL.md packages/kimi-plugin/skills/jfox-session-summary/SKILL.md skills-recommend/pi/jfox-common/SKILL.md skills-recommend/kimi-cli/jfox-common/SKILL.md packages/cc-plugin/skills/manage/SKILL.md packages/kimi-plugin/skills/jfox-manage/SKILL.md docs/json-schemas.md docs/cli-descriptions.yaml README.md CLAUDE.md tests/unit/test_session_summary_skill_docs.py
git commit -m "docs(skills): session-summary 记录 agent/路径/模型，四平台文档同步（#578）"
```

---

### Task 9: 静态门禁与文档生成（A8）

**Files:**

- Modify: `docs/cli-reference.md`、`docs/plugin-inventory.md`（生成物）
- 若有格式问题：对应源文件

- [ ] **Step 1: 跑 lint 与测试**

```bash
uv run ruff check jfox/ tests/
uv run black --check jfox/ tests/
```

- [ ] **Step 2: 修格式**

```bash
uv run black jfox/ tests/
```

- [ ] **Step 3: 重新生成文档并确认无漂移**

```bash
uv run python scripts/generate_docs.py
git diff --stat
```

Expected: 仅 `docs/cli-reference.md` / `docs/plugin-inventory.md` 的预期变更；若产生未跟踪文件，一并 `git add`。

- [ ] **Step 4: 全量相关测试**

```bash
uv run pytest tests/unit/test_note_agent_fields.py tests/unit/test_add_agent_fields.py tests/unit/test_pi_extractor.py tests/unit/test_pi_source.py tests/unit/test_auto_summary_config_sources.py tests/unit/test_session_source.py tests/unit/test_auto_summary_runner.py tests/unit/test_kimi_extractor.py tests/unit/test_auto_summary_extractor.py tests/unit/test_session_summary_skill_docs.py -q
npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"
```

Expected: 全部 PASS / 无 lint 错误。

- [ ] **Step 5: Commit**

```bash
git add docs/cli-reference.md docs/plugin-inventory.md jfox/ tests/
git commit -m "chore(docs): 重新生成 CLI 文档并修复格式（#578）"
```

---

## 验收对照（spec → task）

| 验收 ID | 覆盖任务 |
|---|---|
| A1 | Task 1 |
| A2 | Task 2 |
| A3 | Task 3 |
| A4 | Task 4 |
| A5 | Task 5 |
| A6 | Task 6 |
| A7 | Task 7 |
| A8 | Task 9 |
| A9 | Task 8 |
| U1 | 合并前用户实测（worktree 内，依赖 Task 2 / 8） |
| U2 | 合并前用户实测（worktree 内，依赖 Task 5 / 6；前置改 `~/.zk_config.json`） |
