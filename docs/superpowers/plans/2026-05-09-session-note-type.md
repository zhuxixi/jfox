# Session Note Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `session` note type to jfox for storing AI Agent conversation records, with a built-in template, `--topic` CLI parameter, and updated session-summary skill.

**Architecture:** Extend the existing `NoteType` enum and `Note` dataclass to support session notes. Add `--topic` as a required parameter when `--type session`. The session template becomes the 4th built-in template. The `inbox` command shows both fleeting and session notes.

**Tech Stack:** Python 3.10+, Typer CLI, Pydantic dataclasses, Jinja2 templates, PyYAML

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `jfox/models.py` | Add `SESSION` to `NoteType`, add `topic` field to `Note`, update `filename`/`to_markdown`/`from_markdown`/`to_dict` |
| Modify | `jfox/config.py` | Add `session` to `ensure_dirs()` |
| Modify | `jfox/cli.py` | Add `--topic` param to `add`, update `_add_note_impl`, update `_inbox_impl`, update error messages |
| Modify | `jfox/template.py` | Add `session` to `BUILTIN_TEMPLATES` |
| Modify | `jfox/template_cli.py` | Add `session` to note_type validation whitelist |
| Modify | `skills-recommend/claude-code/jfox-session-summary/SKILL.md` | Default to `session` type, add `--topic` |
| Modify | `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md` | Same changes as claude-code version |
| Create | `tests/unit/test_session_note.py` | Unit tests for session type |

---

### Task 1: NoteType enum + Note model changes

**Files:**

- Modify: `jfox/models.py`

- [ ] **Step 1: Write failing tests for NoteType.SESSION and Note.topic**

Create `tests/unit/test_session_note.py`:

```python
"""
测试类型: 单元测试
目标模块: jfox.models (session note type)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from datetime import datetime

from jfox.models import Note, NoteType


class TestSessionNoteType:
    """Test session note type support"""

    def test_session_enum_value(self):
        assert NoteType.SESSION.value == "session"

    def test_session_note_creation(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write",
            content="Fixed atomic write bug",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            tags=["session"],
            topic="atomic-write",
        )
        assert n.topic == "atomic-write"
        assert n.type == NoteType.SESSION

    def test_session_filename_uses_topic(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write bug",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="atomic-write",
        )
        assert n.filename == "202605091430221234-atomic-write.md"

    def test_session_filename_falls_back_to_title(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write bug",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        # Without topic, slug comes from title
        assert n.filename == "202605091430221234-session-fix-atomic-write-bug.md"

    def test_session_topic_persisted_to_frontmatter(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="my-topic",
        )
        md = n.to_markdown()
        assert "topic: my-topic" in md

    def test_session_topic_absent_when_none(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        md = n.to_markdown()
        assert "topic:" not in md

    def test_session_topic_parsed_from_markdown(self):
        from pathlib import Path
        import tempfile

        md_content = """---
id: "202605091430221234"
title: "Session: test"
type: session
created: "2026-05-09T14:30:22"
updated: "2026-05-09T14:30:22"
tags:
  - session
links: []
backlinks: []
topic: my-topic
---

# Session: test

content here
"""
        n = Note.from_markdown(md_content, Path("test.md"))
        assert n.type == NoteType.SESSION
        assert n.topic == "my-topic"

    def test_session_to_dict_includes_topic(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="my-topic",
        )
        d = n.to_dict()
        assert d["topic"] == "my-topic"

    def test_non_session_note_topic_is_none(self):
        n = Note(
            id="202605091430221234",
            title="Some title",
            content="content",
            type=NoteType.FLEETING,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        assert n.topic is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_session_note.py -v`
Expected: FAIL — `NoteType.SESSION` does not exist, `Note` has no `topic` field

- [ ] **Step 3: Add `SESSION` to `NoteType` enum**

In `jfox/models.py`, add after line 18 (`PERMANENT = "permanent"`):

```python
    SESSION = "session"  # AI Agent 会话记录
```

- [ ] **Step 4: Add `topic` field to `Note` dataclass**

In `jfox/models.py`, add after line 34 (`source: Optional[str] = None`):

```python
    topic: Optional[str] = None  # 会话主题（session 类型）
```

- [ ] **Step 5: Update `filename` property for session type**

Replace the `filename` property (lines 46-55) with:

```python
    @property
    def filename(self) -> str:
        """生成文件名"""
        if self.type == NoteType.FLEETING:
            return f"{self.id[:8]}-{self.id[8:]}.md"
        elif self.type == NoteType.SESSION:
            source = self.topic or self.title
            slug = re.sub(r"[^\w\-]", "", source.lower().replace(" ", "-"))[:50]
            return f"{self.id}-{slug}.md"
        else:
            slug = self.title.lower().replace(" ", "-")[:50]
            slug = re.sub(r"[^\w\-]", "", slug)
            return f"{self.id}-{slug}.md"
```

- [ ] **Step 6: Update `to_markdown` to persist `topic`**

In `to_markdown()`, after the `if self.source:` block (line 82), add:

```python
        if self.topic:
            frontmatter["topic"] = self.topic
```

- [ ] **Step 7: Update `from_markdown` to parse `topic`**

In `from_markdown()`, add `topic=fm.get("topic"),` to the return statement (after `source=fm.get("source"),` at line 130):

```python
            source=fm.get("source"),
            topic=fm.get("topic"),
```

- [ ] **Step 8: Update `to_dict` to include `topic`**

In `to_dict()`, add after the `"source"` line (or after `"hop"` line at ~146):

```python
            "topic": self.topic,
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_session_note.py -v`
Expected: All 9 tests PASS

- [ ] **Step 10: Commit**

```bash
git add jfox/models.py tests/unit/test_session_note.py
git commit -m "feat: add SESSION to NoteType and topic field to Note model"
```

---

### Task 2: Config — ensure_dirs includes session

**Files:**

- Modify: `jfox/config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_session_note.py`:

```python
    def test_config_ensure_dirs_creates_session_dir(self):
        from jfox.config import ZKConfig
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = ZKConfig(base_dir=Path(tmpdir))
            cfg.ensure_dirs()
            assert (cfg.notes_dir / "session").exists()
            assert (cfg.notes_dir / "session").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_session_note.py::TestSessionNoteType::test_config_ensure_dirs_creates_session_dir -v`
Expected: FAIL — `session` directory not created

- [ ] **Step 3: Add `session` to `ensure_dirs`**

In `jfox/config.py`, add `self.notes_dir / "session",` after line 60 (`self.notes_dir / "permanent",`):

```python
            self.notes_dir / "fleeting",
            self.notes_dir / "literature",
            self.notes_dir / "permanent",
            self.notes_dir / "session",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_session_note.py::TestSessionNoteType::test_config_ensure_dirs_creates_session_dir -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/config.py tests/unit/test_session_note.py
git commit -m "feat: add session directory to ensure_dirs"
```

---

### Task 3: CLI — add `--topic` parameter to `add` command

**Files:**

- Modify: `jfox/cli.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_session_note.py`:

```python
class TestSessionCLI:
    """Test session CLI integration"""

    def test_add_session_requires_topic(self):
        """--type session without --topic should raise error"""
        from jfox.cli import _add_note_impl
        with pytest.raises(ValueError, match="--topic"):
            _add_note_impl(
                content="test content",
                title="Session: test",
                note_type="session",
                tags=None,
                source=None,
                output_format="json",
                topic=None,
            )

    def test_add_session_with_topic(self):
        """--type session with --topic should succeed"""
        from jfox.cli import _add_note_impl
        import tempfile
        from pathlib import Path
        from jfox.config import config

        with tempfile.TemporaryDirectory() as tmpdir:
            old_base = config.base_dir
            config.base_dir = Path(tmpdir)
            config.notes_dir = Path(tmpdir) / "notes"
            config.zk_dir = Path(tmpdir) / ".zk"
            (config.notes_dir / "session").mkdir(parents=True, exist_ok=True)

            try:
                _add_note_impl(
                    content="test content",
                    title="Session: test",
                    note_type="session",
                    tags=["session"],
                    source=None,
                    output_format="json",
                    topic="my-topic",
                )
                # Verify file was created in session directory
                session_files = list((config.notes_dir / "session").glob("*.md"))
                assert len(session_files) == 1
                assert "my-topic" in session_files[0].name
            finally:
                config.base_dir = old_base
                config.notes_dir = old_base / "notes"
                config.zk_dir = old_base / ".zk"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_session_note.py::TestSessionCLI -v`
Expected: FAIL — `_add_note_impl` does not accept `topic` parameter

- [ ] **Step 3: Add `--topic` parameter to `add` command**

In `jfox/cli.py`, add a new parameter to the `add` function (after line 423, before `kb`):

```python
    topic: Optional[str] = typer.Option(
        None, "--topic", help="会话主题（session 类型必填）"
    ),
```

- [ ] **Step 4: Pass `topic` to `_add_note_impl`**

Update the call at line 450 to include `topic`:

```python
            _add_note_impl(content, title, note_type, tags, source, output_format, template, topic)
```

- [ ] **Step 5: Add `topic` parameter to `_add_note_impl`**

Update `_add_note_impl` signature (line 287) to include `topic`:

```python
def _add_note_impl(
    content: str,
    title: Optional[str],
    note_type: str,
    tags: Optional[List[str]],
    source: Optional[str],
    output_format: str,
    template: Optional[str] = None,
    topic: Optional[str] = None,
):
```

- [ ] **Step 6: Add session+topic validation and pass topic to create_note**

After the `NoteType` parsing block (after line 334), add:

```python
    # session 类型必须提供 --topic
    if nt == NoteType.SESSION and not topic:
        raise ValueError("--type session 需要 --topic 参数")
```

Update the `create_note` call (around line 349) to pass `topic`:

```python
    new_note = note.create_note(
        content=content,
        title=title,
        note_type=nt,
        tags=tags or [],
        links=resolved_links,
        source=source,
        topic=topic,
    )
```

- [ ] **Step 7: Update `create_note` in `note.py` to accept and pass `topic`**

Find the `create_note` function in `jfox/note.py` and add `topic: Optional[str] = None` to its parameters, then pass it to the `Note` constructor.

- [ ] **Step 8: Update error messages**

Update the three error messages in `cli.py` that list note types:

Line 334:

```python
raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session")
```

Line 786:

```python
raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session")
```

Line 1237:

```python
f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session"
```

- [ ] **Step 9: Update `--type` help text in `add` command**

Update line 413:

```python
    note_type: str = typer.Option(
        "fleeting", "--type", help="笔记类型 (fleeting/literature/permanent/session)"
    ),
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_session_note.py -v`
Expected: All tests PASS

- [ ] **Step 11: Commit**

```bash
git add jfox/cli.py jfox/note.py tests/unit/test_session_note.py
git commit -m "feat: add --topic parameter to add command for session type"
```

---

### Task 4: Built-in session template

**Files:**

- Modify: `jfox/template.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_session_note.py`:

```python
class TestSessionTemplate:
    """Test session built-in template"""

    def test_session_builtin_template_exists(self):
        import tempfile
        from pathlib import Path
        from jfox.template import TemplateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = TemplateManager(Path(tmpdir))
            tmpl = mgr.get_template("session")
            assert tmpl is not None
            assert tmpl.note_type == "session"

    def test_session_template_renders(self):
        import tempfile
        from pathlib import Path
        from jfox.template import TemplateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = TemplateManager(Path(tmpdir))
            result = mgr.render("session", {
                "title": "Session: test",
                "content": "did some work",
                "source": "",
                "topic": "my-topic",
            })
            assert result["note_type"] == "session"
            assert "my-topic" in result["title"]
            assert "完成的工作" in result["content"]
            assert "session" in result["tags"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_session_note.py::TestSessionTemplate -v`
Expected: FAIL — `session` template does not exist

- [ ] **Step 3: Add session to BUILTIN_TEMPLATES**

In `jfox/template.py`, add to the `BUILTIN_TEMPLATES` dict after the `literature` entry (after line 71):

```python
        "session": {
            "name": "session",
            "description": "AI Agent 会话记录",
            "note_type": "session",
            "title_format": "{{date}}-{{time}}-{{topic}}",
            "content": (
                "## 背景\n<!-- 本次会话的起因/上下文 -->\n\n"
                "## 完成的工作\n<!-- 本轮会话做了什么 -->\n\n"
                "## 我的决策\n<!-- AI Agent 做出的决策 -->\n\n"
                "| 决策 | 状态 | 说明 |\n|------|------|------|\n"
                "|      | 采纳 |      |\n|      | 否决 |      |\n\n"
                "采纳率：采纳 X/N，否决 Y/N\n\n"
                "## 耶稣决策\n<!-- 外部输入的高权重决策，必须以此为准 -->\n\n"
                "## 意外收获\n<!-- 会话中发现的非当前问题的问题 -->\n\n"
                "| 发现 | 是否有跟进 | 跟进方式 |\n|------|-----------|----------|\n"
                "|      | 是/否     | issue / 项目管理 |\n\n"
                "## 待办\n<!-- 后续需要处理的事项 -->\n- [ ] \n\n"
                "{{content}}"
            ),
            "tags": ["session"],
        },
```

- [ ] **Step 4: Update existing template test that checks builtin count**

Read `tests/unit/test_template.py` to see if any test checks the exact count of built-in templates. If so, update it to expect 4 instead of 3. If not, skip this step.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_session_note.py::TestSessionTemplate tests/unit/test_template.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/template.py tests/unit/test_session_note.py
git commit -m "feat: add session built-in template for AI Agent conversation records"
```

---

### Task 5: template_cli.py validation whitelist

**Files:**

- Modify: `jfox/template_cli.py`

- [ ] **Step 1: Update note_type validation**

In `jfox/template_cli.py`, line 195, change:

```python
        if note_type not in ["fleeting", "literature", "permanent"]:
```

to:

```python
        if note_type not in ["fleeting", "literature", "permanent", "session"]:
```

- [ ] **Step 2: Run existing template_cli tests**

Run: `uv run pytest tests/unit/test_template_cli.py -v`
Expected: All existing tests PASS (no test should break from whitelist expansion)

- [ ] **Step 3: Commit**

```bash
git add jfox/template_cli.py
git commit -m "feat: add session to template_cli note_type validation"
```

---

### Task 6: Inbox — show both fleeting and session notes

**Files:**

- Modify: `jfox/cli.py`

- [ ] **Step 1: Update `_inbox_impl`**

Replace the `_inbox_impl` function body (lines 1683-1709) to query both fleeting and session notes:

```python
def _inbox_impl(
    limit: int,
    output_format: str,
    json_output: bool,
):
    """查看临时笔记的内部实现"""
    from .note_index import get_note_index

    idx = get_note_index()
    fleeting_notes = idx.list_meta(note_type=NoteType.FLEETING, limit=limit)
    session_notes = idx.list_meta(note_type=NoteType.SESSION, limit=limit)
    all_notes = fleeting_notes + session_notes
    # Sort by created descending
    all_notes.sort(key=lambda m: m.created or "", reverse=True)
    all_notes = all_notes[:limit]

    result = {
        "total": len(all_notes),
        "notes": [
            {
                "id": m.id,
                "title": m.title,
                "type": m.type.value,
                "created": m.created,
                "filepath": m.filepath if m.filepath else None,
            }
            for m in all_notes
        ],
    }

    if output_format == "json":
        print(output_json(result))
    else:
        console.print(f"[bold]Inbox ({len(all_notes)}):[/bold]\n")
        for m in all_notes:
            time_str = m.created[11:16] if m.created and len(m.created) >= 16 else ""
            type_badge = {"fleeting": "fl", "session": "se"}.get(m.type.value, "??")
            console.print(f"- [{time_str}] [{type_badge}] {m.title}")
```

- [ ] **Step 2: Update `inbox` command docstring**

Change line 1798 from:

```python
    """查看临时笔记 (Fleeting Notes)"""
```

to:

```python
    """查看临时笔记和会话记录 (Fleeting + Session Notes)"""
```

- [ ] **Step 3: NoteMeta uses `type` field (not `note_type`)**

Verified: `NoteMeta` in `jfox/note_index.py` has `type: NoteType` field. The code above uses `m.type.value` to access the string value.

- [ ] **Step 4: Commit**

```bash
git add jfox/cli.py
git commit -m "feat: inbox shows both fleeting and session notes"
```

---

### Task 7: Update jfox-session-summary skill

**Files:**

- Modify: `skills-recommend/claude-code/jfox-session-summary/SKILL.md`
- Modify: `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md`

- [ ] **Step 1: Update claude-code SKILL.md**

In `skills-recommend/claude-code/jfox-session-summary/SKILL.md`:

Update Step 3 options to include `session` as recommended default:

```markdown
### Step 3: 选择笔记类型

用户确认内容后，使用 `AskUserQuestion` 询问笔记类型：

- 问题：`选择笔记类型`
- 选项：
  - `session`（推荐）— AI Agent 会话记录，专为此场景设计
  - `fleeting` — 如果只是快速记录，后续可提炼
  - `literature` — 如果会话有明确的参考资料来源
  - `permanent` — 如果总结已经是成熟的知识
```

Update Step 4 command to include `--topic`:

```bash
jfox add "<markdown-escaped-summary>" \
  --title "Session: <topic>" \
  --type <Step 3 选定的类型> \
  --topic <short-topic> \
  --tag session \
  --kb <kb-name> \
  --format json
```

Add a note about `--topic` being required for session type:

```markdown
**注意**：
- 当类型为 `session` 时，`--topic` 参数必填
- `--topic` 的值应该是简短的英文标识（如 `atomic-write`、`daemon-stop-fix`）
- 标题格式统一为 `Session: <简短主题>`
```

Update Step 5 `--content-file` example to include `--topic`:

```bash
jfox add --content-file /tmp/session-summary.md \
  --title "Session: <topic>" \
  --type <Step 3 选定的类型> \
  --topic <short-topic> \
  --tag session \
  --kb <kb-name> \
  --format json
```

- [ ] **Step 2: Apply same changes to kimi-cli SKILL.md**

Make identical changes to `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md`.

- [ ] **Step 3: Commit**

```bash
git add skills-recommend/claude-code/jfox-session-summary/SKILL.md skills-recommend/kimi-cli/jfox-session-summary/SKILL.md
git commit -m "feat: update jfox-session-summary skill to default to session type with --topic"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run all fast unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All tests PASS (including existing tests — no regressions)

- [ ] **Step 2: Verify CLI help text**

Run: `uv run jfox add --help`
Expected: `--topic` parameter visible in help output, `--type` help mentions `session`

- [ ] **Step 3: Manual smoke test — create a session note**

Run: `uv run jfox add "Test session content" --title "Session: smoke test" --type session --topic smoke-test --tag session`
Expected: Note created successfully in `notes/session/` directory

- [ ] **Step 4: Manual smoke test — verify inbox shows session notes**

Run: `uv run jfox inbox`
Expected: Shows the newly created session note alongside any fleeting notes

- [ ] **Step 5: Manual smoke test — verify template exists**

Run: `uv run jfox template list`
Expected: `session` template listed among built-in templates
