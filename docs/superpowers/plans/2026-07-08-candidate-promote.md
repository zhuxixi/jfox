# L5 候选晋升（candidate → permanent）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 candidate 笔记的人工晋升闭环——`jfox candidates promote/reject` CLI + `promote` skill，跑通 #249 五层 Loop Engineering 的最后一层。

**Architecture:** `promote_note`/`reject_note` 原子函数在 `jfox/note.py`（note 层，可独立测试）；`candidates promote/reject` 子命令挂在 `jfox/gem_synth/cli.py` 的 `candidates_app`；`promote` skill 在 `packages/cc-plugin/skills/promote/` 编排过审对话（三档分流 triage）。backlinks 增量回填复用 `note_index` 的标题解析能力，避免循环 import。

**Tech Stack:** Python 3.10+ / Typer CLI / SQLite(已有) / pytest。纯逻辑任务（不涉 embedding）用 `mock_embedding_backend`。

---

## 关键实现决策（对 spec §2.1 的细化）

`Note.to_markdown`（`models.py:141`）规定 candidate 专属字段（`source_fragments`/`grounded_by`/`status`/`gem_level`/`confidence`/`knowledge_type`）**只在 `type==CANDIDATE` 时写入 frontmatter**。因此 promote 改 `type→PERMANENT` 后，这些 frontmatter 字段**自动不再写入**（无需手动剔除）。

- spec §2.1「保留 source_fragments/grounded_by 做溯源」→ 实现上 **frontmatter 不保留**（随 type 自动清除），**溯源由正文「## 来源」「## 参考的永久笔记」段承载**（candidate 正文已有，skill 改写时保留）。
- dataclass 字段也一并清空（避免 `to_dict` 残留）。

这样不动 `to_markdown` 的类型绑定设计，最干净。

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `jfox/models.py` | `Note` 数据模型 | 加 `reject_reason` 字段 + 三处序列化 |
| `jfox/note.py` | 笔记 CRUD | 加 `promote_note` / `reject_note` 原子函数 |
| `jfox/gem_synth/cli.py` | `candidates` 子命令组 | 加 `promote` / `reject` 子命令 |
| `tests/unit/test_note_promote.py` | promote/reject 单元测试 | 新建 |
| `tests/unit/test_gem_synth_cli.py` | candidates CLI 测试 | 加 promote/reject 用例 |
| `tests/integration/test_candidate_promote_flow.py` | 端到端流程 | 新建 |
| `packages/cc-plugin/skills/promote/SKILL.md` | 过审 skill | 新建 |
| `packages/cc-plugin/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` | plugin 版本 | bump（加 skill） |

---

## Task 1: Note 模型加 `reject_reason` 字段

**Files:**
- Modify: `jfox/models.py`（`Note` dataclass + `to_markdown` + `from_markdown` + `to_dict`）
- Test: `tests/unit/test_note_promote.py`（新建）

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_note_promote.py`）

```python
"""candidate promote/reject 单元测试。目标模块: jfox.note"""
import pytest
from utils.temp_kb import temp_kb_registered
from jfox.config import use_kb
from jfox.models import Note, NoteType
from jfox.note import create_note, save_note

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_reject_reason_roundtrip():
    """reject_reason 字段可序列化与反序列化"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    n.reject_reason = "知识不准确"
    md = n.to_markdown()
    assert "reject_reason: 知识不准确" in md
    restored = Note.from_markdown(md, n.filepath)
    assert restored.reject_reason == "知识不准确"


def test_reject_reason_not_written_when_none():
    """无 reject_reason 时不写入 frontmatter"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    assert "reject_reason" not in n.to_markdown()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_promote.py::test_reject_reason_roundtrip -v`
Expected: FAIL with `AttributeError: 'Note' object has no attribute 'reject_reason'`

- [ ] **Step 3: 加字段 + 序列化**（`jfox/models.py`）

在 `archived: bool = False`（第 75 行）后加一行：

```python
    archived: bool = False  # 是否已归档（软删除标记）
    reject_reason: Optional[str] = None  # candidate reject 原因（供复盘）
```

在 `to_markdown` 的 `if self.archived:` 块（第 137-138 行）后加：

```python
        if self.archived:
            frontmatter["archived"] = self.archived
        if self.reject_reason:
            frontmatter["reject_reason"] = self.reject_reason
```

在 `from_markdown` 的 `archived=_to_bool(...)`（第 202 行）后加参数：

```python
            archived=_to_bool(fm.get("archived", False)),
            reject_reason=fm.get("reject_reason"),
```

在 `to_dict` 的 `"archived": self.archived,`（第 223 行）后加：

```python
        "archived": self.archived,
        "reject_reason": self.reject_reason,
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_promote.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add jfox/models.py tests/unit/test_note_promote.py
git commit -m "feat(models): Note 加 reject_reason 字段（candidate reject 复盘用）"
```

---

## Task 2: `note.py` 加 `promote_note` 原子函数

**Files:**
- Modify: `jfox/note.py`（新增 `promote_note`）
- Test: `tests/unit/test_note_promote.py`（追加）

- [ ] **Step 1: 追加失败测试**（`tests/unit/test_note_promote.py` 末尾）

```python
from jfox.note import load_note_by_id, promote_note


def _make_candidate(title, content, grounded_by=None):
    """构造并保存一条 candidate 笔记。"""
    n = create_note(content, title=title, note_type=NoteType.CANDIDATE)
    n.gem_level = "flawed"
    n.confidence = 0.8
    n.status = "pending"
    n.source_fragments = [1, 2]
    n.grounded_by = grounded_by or []
    n.knowledge_type = "factual"
    save_note(n, add_to_index=False)
    return n


def test_promote_changes_type_to_permanent():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容 [[目标笔记]]")
            assert promote_note(c.id) is True
            assert load_note_by_id(c.id).type == NoteType.PERMANENT


def test_promote_moves_file_to_permanent_dir():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            from jfox.config import config
            c = _make_candidate("测试候选", "内容")
            candidate_path = config.notes_dir / "candidate" / c.filename
            assert candidate_path.exists()
            promote_note(c.id)
            assert (config.notes_dir / "permanent" / c.filename).exists()
            assert not candidate_path.exists()


def test_promote_clears_candidate_frontmatter_fields():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("测试候选", "内容")
            promote_note(c.id)
            md = load_note_by_id(c.id).filepath.read_text(encoding="utf-8")
            for field in ("gem_level", "confidence", "status", "source_fragments", "grounded_by"):
                assert field not in md


def test_promote_backfills_backlinks_to_targets():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")
            promote_note(c.id)
            assert c.id in load_note_by_id(target.id).backlinks


def test_promote_sets_forward_links():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")
            promote_note(c.id)
            assert target.id in load_note_by_id(c.id).links


def test_promote_rejects_non_candidate():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            p = create_note("永久", title="永久笔记", note_type=NoteType.PERMANENT)
            save_note(p, add_to_index=False)
            assert promote_note(p.id) is False


def test_promote_nonexistent_returns_false():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            assert promote_note("999999999999999") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_promote.py -k promote -v`
Expected: FAIL with `ImportError: cannot import name 'promote_note'`

- [ ] **Step 3: 实现 `promote_note`**（`jfox/note.py`，加在 `unarchive_note` 函数后、`update_note` 前）

```python
def promote_note(note_id: str, cfg: Optional[ZKConfig] = None) -> bool:
    """candidate → permanent：改 type、清 candidate 字段、移文件、回填 links/backlinks。

    frontmatter 的 candidate 专属字段随 type 改变自动不再写入（to_markdown 类型绑定）；
    溯源由正文「## 来源」段承载。backlinks 增量回填：解析正文 [[...]] → 精确标题匹配
    → 设本笔记 links + 把本笔记加进各 target 的 backlinks。
    """
    from .note_index import extract_wiki_links_from_text, get_note_index

    n = load_note_by_id(note_id, cfg=cfg)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False
    if n.type != NoteType.CANDIDATE:
        logger.warning(f"Note {note_id} is not a candidate (type={n.type.value})")
        return False

    # 解析正文 wiki links → target ids（精确标题匹配，避免子串误匹配）
    idx = get_note_index(cfg)
    target_ids: List[str] = []
    for link_text in extract_wiki_links_from_text(n.content):
        tm = idx.find_by_title(link_text)
        if tm and tm.id != n.id and tm.id not in target_ids:
            target_ids.append(tm.id)

    # 改 type + 清 candidate 生命周期字段（frontmatter 随 type 自动清；dataclass 同步清）
    n.type = NoteType.PERMANENT
    n.status = None
    n.gem_level = None
    n.confidence = None
    n.knowledge_type = None
    n.source_fragments = []
    n.grounded_by = []
    n.links = sorted(set(n.links + target_ids))

    # update_note：filepath 随 type 变 → 写 permanent/ + 删 candidate/ 旧文件 + 更新索引
    if not update_note(n):
        return False

    # 增量回填：把本笔记加进每个 target 的 backlinks（target 内容未变，只改 frontmatter + 同步索引缓存）
    for tid in target_ids:
        t = load_note_by_id(tid, cfg=cfg)
        if t and n.id not in t.backlinks:
            t.backlinks = sorted(set(t.backlinks + [n.id]))
            _atomic_write(t.filepath, t.to_markdown())
            try:
                get_note_index(cfg).update_note_meta(t)
            except Exception as e:
                logger.warning(f"Failed to sync index meta for target {tid}: {e}")
    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_promote.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_note_promote.py
git commit -m "feat(note): promote_note 原子函数（candidate→permanent + backlinks 回填）"
```

---

## Task 3: `note.py` 加 `reject_note` 函数

**Files:**
- Modify: `jfox/note.py`（新增 `reject_note`）
- Test: `tests/unit/test_note_promote.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
from jfox.note import reject_note


def test_reject_archives_and_records_reason():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("要拒的", "内容")
            assert reject_note(c.id, reason="不准确") is True
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准确"


def test_reject_without_reason_still_archives():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            c = _make_candidate("要拒的", "内容")
            assert reject_note(c.id) is True
            assert load_note_by_id(c.id).archived is True
            assert load_note_by_id(c.id).reject_reason is None


def test_reject_nonexistent_returns_false():
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            assert reject_note("999999999999999") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_promote.py -k reject -v`
Expected: FAIL with `ImportError: cannot import name 'reject_note'`

- [ ] **Step 3: 实现 `reject_note`**（`jfox/note.py`，加在 `promote_note` 后）

```python
def reject_note(note_id: str, reason: Optional[str] = None, cfg: Optional[ZKConfig] = None) -> bool:
    """candidate 归档丢弃（软删除），可选记 reject_reason。复用归档逻辑，可 unarchive 恢复。"""
    n = load_note_by_id(note_id, cfg=cfg)
    if not n:
        logger.warning(f"Note {note_id} not found")
        return False
    n.archived = True
    if reason:
        n.reject_reason = reason
    return update_note(n)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_promote.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_note_promote.py
git commit -m "feat(note): reject_note（candidate 归档丢弃 + reason）"
```

---

## Task 4: `candidates promote` CLI 子命令

**Files:**
- Modify: `jfox/gem_synth/cli.py`（`candidates_app` 加 `promote`）
- Test: `tests/unit/test_gem_synth_cli.py`（追加）

- [ ] **Step 1: 追加失败测试**（`tests/unit/test_gem_synth_cli.py`，参考该文件现有 `CliRunner` + `app` import 模式；若文件顶部无则补）

在文件顶部确认有（没有则加）：
```python
from unittest.mock import patch
from typer.testing import CliRunner
from jfox.cli import app
runner = CliRunner()
```

追加测试：
```python
def test_candidates_promote_command(temp_kb, mock_embedding_backend):
    """jfox candidates promote <id> 把 candidate 改成 permanent"""
    from jfox.config import use_kb
    from jfox.models import NoteType
    from jfox.note import create_note, save_note, load_note_by_id

    kb_name = "test_promote_cli"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        init_res = runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)])
        assert init_res.exit_code == 0, init_res.output

        with use_kb(kb_name):
            c = create_note("内容", title="候选A", note_type=NoteType.CANDIDATE)
            c.status = "pending"
            save_note(c, add_to_index=False)

        res = runner.invoke(app, ["candidates", "promote", c.id, "--kb", kb_name, "--format", "json"])
        assert res.exit_code == 0, res.output
        import json
        assert json.loads(res.output)["promoted"] == c.id

        with use_kb(kb_name):
            assert load_note_by_id(c.id).type == NoteType.PERMANENT


def test_candidates_promote_nonexistent_exits_nonzero(temp_kb, mock_embedding_backend):
    kb_name = "test_promote_404"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)])
        res = runner.invoke(app, ["candidates", "promote", "999999999999999", "--kb", kb_name])
        assert res.exit_code == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -k promote -v`
Expected: FAIL（命令不存在）

- [ ] **Step 3: 实现 `promote` 子命令**（`jfox/gem_synth/cli.py`，加在 `list_cmd` 后）

```python
@candidates_app.command("promote")
def promote_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """晋升 candidate → permanent（改 type + 移文件 + 回填 backlinks）"""
    from ..config import use_kb
    from ..note import promote_note

    with use_kb(kb):
        ok = promote_note(note_id)
        if output_format == "json":
            typer.echo(_json.dumps({"promoted": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 晋升 {note_id} → permanent")
        else:
            console.print(f"[red]✗ 晋升失败：{note_id}（非 candidate 或不存在）[/red]")
        if not ok:
            raise typer.Exit(code=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -k promote -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add jfox/gem_synth/cli.py tests/unit/test_gem_synth_cli.py
git commit -m "feat(gem-synth): candidates promote 子命令"
```

---

## Task 5: `candidates reject` CLI 子命令

**Files:**
- Modify: `jfox/gem_synth/cli.py`（`candidates_app` 加 `reject`）
- Test: `tests/unit/test_gem_synth_cli.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_candidates_reject_command(temp_kb, mock_embedding_backend):
    """jfox candidates reject <id> 归档 + 记 reason"""
    from jfox.config import use_kb
    from jfox.models import NoteType
    from jfox.note import create_note, save_note, load_note_by_id

    kb_name = "test_reject_cli"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        runner.invoke(app, ["init", "--name", kb_name, "--path", str(temp_kb)])
        with use_kb(kb_name):
            c = create_note("内容", title="候选B", note_type=NoteType.CANDIDATE)
            save_note(c, add_to_index=False)

        res = runner.invoke(
            app, ["candidates", "reject", c.id, "--reason", "不准", "--kb", kb_name, "--format", "json"]
        )
        assert res.exit_code == 0, res.output
        with use_kb(kb_name):
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -k reject -v`
Expected: FAIL（命令不存在）

- [ ] **Step 3: 实现 `reject` 子命令**（`jfox/gem_synth/cli.py`，加在 `promote_cmd` 后）

```python
@candidates_app.command("reject")
def reject_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="拒绝原因（记入 frontmatter）"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """拒绝 candidate（归档丢弃，可记原因，可 jfox unarchive 恢复）"""
    from ..config import use_kb
    from ..note import reject_note

    with use_kb(kb):
        ok = reject_note(note_id, reason=reason)
        if output_format == "json":
            typer.echo(_json.dumps({"rejected": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 拒绝 {note_id}（已归档）")
        else:
            console.print(f"[red]✗ 拒绝失败：{note_id} 不存在[/red]")
        if not ok:
            raise typer.Exit(code=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -k "promote or reject" -v`
Expected: all passed

- [ ] **Step 5: 跑全量 gem_synth CLI 回归**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -v`
Expected: 无回归（原有 show/list 用例仍通过）

- [ ] **Step 6: Commit**

```bash
git add jfox/gem_synth/cli.py tests/unit/test_gem_synth_cli.py
git commit -m "feat(gem-synth): candidates reject 子命令"
```

---

## Task 6: `promote` skill

**Files:**
- Create: `packages/cc-plugin/skills/promote/SKILL.md`
- Modify: `packages/cc-plugin/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`（version bump，三处一致）

> 本任务非 TDD（skill 是 markdown 文档）。验收 = 手动过审一条真实 candidate。

- [ ] **Step 1: 创建 `packages/cc-plugin/skills/promote/SKILL.md`**

```markdown
---
name: promote
description: 过审 gem-synth 产出的 candidate 笔记，分流 triage（准确/半准/不准），改写并晋升为 permanent 或归档拒绝。Triggers on "过审 candidate", "晋升候选笔记", "审阅候选宝石", "promote candidate", "review candidate".
---

# 过审 candidate（破损→完整）

把 L3 合成产出的 candidate（pending/flawed）逐条过审，晋升为 permanent 或拒绝归档。
对应 #249 五层 Loop Engineering 的 L5 晋升层。

## 过审流程（三档分流 triage）

取下一条 pending candidate（`jfox candidates list --status pending`，按 confidence 降序），
然后按**准确度**分流：

### 档 A：准确（无实质错误）
1. 读 candidate 全文 + 其 `grounded_by` 指向的 permanent（`jfox show <id>`）
2. 微调：清 candidate 专属段落（「待人工审阅」「置信度说明」），整理成 permanent 风格
3. wiki link：验证已有 `[[参考笔记]]` 链对 + 用 `jfox suggest-links "<正文>"` 补漏链
4. 展示改写后正文 + wiki link 报告，请用户确认
5. 确认 → 改写回文件后 `jfox candidates promote <id>`

### 档 B：大部分对、局部有问题（澄清）
1. 列出问题点（哪条事实待定 / 哪处二选一 / 缺什么信息），一次性给出，请用户批量回答
2. 据回答改写（含 §A 的微调 + 补链）
3. 可能多轮澄清；完成后展示 → 确认 → `jfox candidates promote <id>`

### 档 C：整体不可信
1. 给出依据（与哪条 permanent 冲突 / grounding 崩了）
2. 请用户确认拒绝 → `jfox candidates reject <id> --reason "<原因>"`

## 边界原则
- **能确信改对的**（格式、candidate 元段落、明显缺链）→ 微调，直接改，不问用户
- **需要用户判断的**（事实对错、语义二选一、关键信息缺失）→ 澄清
- **整体不可信的**（冲突/grounding 崩）→ reject

## 关键约束
- 晋升前把改写后的正文写回 candidate 文件（promote 只改 type/移文件/回填 backlinks，不改正文）
- wiki link 补链阈值 ≥ 0.6（与 organize skill 一致）
- 用户始终有最终决定权：agent 判档 + 给依据，用户可 override
```

- [ ] **Step 2: bump plugin 版本（三处）**

`packages/cc-plugin/.claude-plugin/plugin.json` 的 `version`：`0.4.0` → `0.5.0`
`.claude-plugin/marketplace.json` 的 `metadata.version` + `plugins[0].version`：`0.4.0` → `0.5.0`

（CLAUDE.md 约定：三处必须一致，漏改会导致 marketplace 与 plugin 版本不一致）

- [ ] **Step 3: 手动验收**

```bash
# 确认 skill 被识别
uv run jfox candidates list --status pending
# 挑一条真实 candidate，走一遍档 A 流程（读→微调→补链→改写回文件→promote）
jfox candidates show <id>
jfox suggest-links "<正文>"
# 改写后写回文件，再：
jfox candidates promote <id>
# 验证：type 变 permanent、文件移到 permanent/、被引用笔记有了 backlink
```

- [ ] **Step 4: Commit**

```bash
git add packages/cc-plugin/skills/promote/SKILL.md packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat(plugin): promote skill（L5 candidate 过审编排）+ bump 0.5.0"
```

---

## Task 7: 端到端集成测试

**Files:**
- Create: `tests/integration/test_candidate_promote_flow.py`

- [ ] **Step 1: 写集成测试**

```python
"""端到端：candidate → promote → permanent（含 backlinks）；candidate → reject → archived"""
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.config import use_kb
from jfox.models import NoteType
from jfox.note import create_note, save_note, load_note_by_id

pytestmark = [pytest.mark.integration]
runner = CliRunner()


def test_promote_full_flow(temp_kb, mock_embedding_backend):
    """candidate 引用一条 permanent → promote → type 变、文件移动、backlink 建立"""
    kb = "test_promote_e2e"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        assert runner.invoke(app, ["init", "--name", kb, "--path", str(temp_kb)]).exit_code == 0

        with use_kb(kb):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = create_note("讲讲 [[目标笔记]]", title="候选X", note_type=NoteType.CANDIDATE)
            c.status = "pending"
            save_note(c, add_to_index=False)

        res = runner.invoke(app, ["candidates", "promote", c.id, "--kb", kb, "--format", "json"])
        assert res.exit_code == 0
        assert json.loads(res.output)["success"] is True

        with use_kb(kb):
            from jfox.config import config
            p = load_note_by_id(c.id)
            assert p.type == NoteType.PERMANENT
            assert (config.notes_dir / "permanent" / p.filename).exists()
            assert target.id in p.links
            assert c.id in load_note_by_id(target.id).backlinks


def test_reject_full_flow(temp_kb, mock_embedding_backend):
    """candidate → reject → archived + reason，默认 list 不可见"""
    kb = "test_reject_e2e"
    with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
        runner.invoke(app, ["init", "--name", kb, "--path", str(temp_kb)])
        with use_kb(kb):
            c = create_note("内容", title="候选Y", note_type=NoteType.CANDIDATE)
            save_note(c, add_to_index=False)

        res = runner.invoke(
            app, ["candidates", "reject", c.id, "--reason", "不准", "--kb", kb, "--format", "json"]
        )
        assert res.exit_code == 0

        with use_kb(kb):
            r = load_note_by_id(c.id)
            assert r.archived is True
            assert r.reject_reason == "不准"
        # 默认 list 排除归档
        list_res = runner.invoke(app, ["list", "--type", "candidate", "--kb", kb, "--json"])
        assert json.loads(list_res.output)["total"] == 0
```

- [ ] **Step 2: 跑集成测试**

Run: `uv run pytest tests/integration/test_candidate_promote_flow.py -v`
Expected: 2 passed

- [ ] **Step 3: 跑全量快速回归（确认无回归）**

Run: `uv run pytest tests/unit/test_note_promote.py tests/unit/test_gem_synth_cli.py tests/integration/test_candidate_promote_flow.py -v`
Expected: all passed

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_candidate_promote_flow.py
git commit -m "test(integration): candidate promote/reject 端到端流程"
```

---

## 完成后

- 跑 `uv run jfox candidates list --status pending` 确认能逐条过审
- 跑一遍 skill 手动过审一条真实 candidate（档 A/B/C 各试一条）
- PR 合入 main（CI fast job 须绿：`not embedding and not slow`）
- 合入后可关联回 #249（L5 完成）+ 在 #295 独立推进 status 呈现
