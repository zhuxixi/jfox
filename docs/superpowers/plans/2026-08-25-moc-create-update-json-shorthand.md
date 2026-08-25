# moc create/update --json 简写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `jfox moc create` / `jfox moc update` 补 `--json` 简写，与 `diagnose` 及 jfox-common §4.1 约定对齐。

**Architecture:** 纯模式复制——范本是 `jfox/moc/cli.py` 中 `diagnose_cmd` 的 `json_output` 参数（与主 `cli.py` 10+ 命令同一模式）。每个命令加一个 `json_output: bool` 参数，函数体开头置位 `output_format`，其余逻辑零改动。

**Tech Stack:** Python 3.10+ / Typer / pytest / typer.testing.CliRunner

## Global Constraints

- 参数 help 文案逐字一致：`"JSON 输出（快捷方式，等同于 --format json）"`
- 置位逻辑逐字一致：`if json_output: output_format = "json"`（放在 `_fail` 校验之前）
- 所有改动在 worktree `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand` 内进行
- 测试命令：`cd <worktree> && .venv/bin/python -m pytest tests/unit/test_xxx.py -v`（用 worktree 自带的 .venv）
- commit 按文件 `git add <file>`，禁止 `git add -A`
- 测试以单进程运行（pytest.ini 已配置）

---

### Task 1: create_cmd 加 --json 简写

**Files:**
- Modify: `jfox/moc/cli.py`（create_cmd，约 338-371 行）
- Test: `tests/unit/test_moc_create_cli.py`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces: `create_cmd(json_output: bool)` —— 后续无任务依赖，纯用户面参数

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_moc_create_cli.py` 末尾追加（复用文件头部已有的 `_report()` / `_mock_meta()` / `runner` / patch imports）：

```python
def test_create_json_shorthand_matches_format_json():
    """--json 简写与 --format json 输出一致（含 created 字段）。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with (
            patch("jfox.moc.cli.get_note_index") as mock_index,
            patch("jfox.moc.cli.write_moc") as mock_write,
            patch("jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2"}, [])),
        ):
            mock_index.return_value.get_all_meta.return_value = _mock_meta()
            fake_moc = Note(
                id="20260822000001",
                title="Zima Hub MOC",
                content="",
                type=NoteType.STRUCTURE,
                created=dt(2026, 8, 22),
                updated=dt(2026, 8, 22),
            )
            mock_write.return_value = fake_moc
            result = runner.invoke(app, ["moc", "create", "--yes", "--json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["created"]["id"] == "20260822000001"
    assert mock_write.call_count == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/test_moc_create_cli.py::test_create_json_shorthand_matches_format_json -v`
Expected: FAIL——typer 报 "No such option: --json"（exit_code 2，exit_code != 0 断言失败）

- [ ] **Step 3: 实现**

在 `jfox/moc/cli.py` 的 `create_cmd` 签名中，`output_format` 参数之后加：

```python
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
```

函数体开头（`if output_format not in {...}` 之前）加：

```python
    if json_output:
        output_format = "json"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/test_moc_create_cli.py -v`
Expected: 全文件 PASS（含原有 8 条测试）

- [ ] **Step 5: Commit**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand
git add jfox/moc/cli.py tests/unit/test_moc_create_cli.py
git commit -m "feat(moc): create supports --json shorthand (#425)"
```

---

### Task 2: update_cmd 加 --json 简写

**Files:**
- Modify: `jfox/moc/cli.py`（update_cmd，约 516-538 行）
- Test: `tests/unit/test_moc_update_cli.py`

**Interfaces:**
- Consumes: Task 1 的置位模式（`if json_output: output_format = "json"`）
- Produces: `update_cmd(json_output: bool)` —— 无后续依赖

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_moc_update_cli.py` 末尾追加（复用文件头部已有的 `_report()` / `_moc_note()` / `_mock_meta()`）：

```python
def test_update_json_shorthand_matches_format_json():
    """--json 简写与 --format json 输出一致（diff add/remove/kept）。"""
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        with patch("jfox.moc.cli.list_notes", return_value=[_moc_note()]):
            with patch("jfox.moc.cli.get_note_index") as mock_index:
                mock_index.return_value.get_all_meta.return_value = _mock_meta()
                with patch(
                    "jfox.moc.cli.verify_members_on_disk", return_value=({"1", "2", "3"}, [])
                ):
                    result = runner.invoke(app, ["moc", "update", "--json"])

    assert result.exit_code == 0
    payload = json.loads(_strip_ansi(result.output))
    assert payload["success"] is True
    first = payload["updates"][0]
    assert first["moc_id"] == "20260822000001"
    assert [m["id"] for m in first["add"]] == ["3"]
    assert first["remove"] == ["99"]
    assert first["kept"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/test_moc_update_cli.py::test_update_json_shorthand_matches_format_json -v`
Expected: FAIL——typer 报 "No such option: --json"

- [ ] **Step 3: 实现**

在 `jfox/moc/cli.py` 的 `update_cmd` 签名中，`output_format` 参数之后加（与 Task 1 逐字一致）：

```python
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
```

函数体开头（`if output_format not in {...}` 之前）加：

```python
    if json_output:
        output_format = "json"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/test_moc_update_cli.py -v`
Expected: 全文件 PASS（含原有 10 条测试）

- [ ] **Step 5: Commit**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand
git add jfox/moc/cli.py tests/unit/test_moc_update_cli.py
git commit -m "feat(moc): update supports --json shorthand (#425)"
```

---

### Task 3: SKILL.md 文档同步 + help 契约断言

**Files:**
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md`
- Test: `tests/unit/test_moc_create_cli.py`、`tests/unit/test_moc_update_cli.py`

**Interfaces:**
- Consumes: Task 1/2 的 `--json` 参数已落地
- Produces: 无

- [ ] **Step 1: 写失败测试（help 契约含 --json）**

在两个文件的 help 契约测试中各加一行断言：

`tests/unit/test_moc_create_cli.py` 的 `test_moc_create_help_registers_exact_contract` 末尾加：

```python
    assert "--json" in " ".join(lines)
```

`tests/unit/test_moc_update_cli.py` 的 `test_moc_update_help_registers_exact_contract` 末尾加：

```python
    assert "--json" in " ".join(lines)
```

（此时 Task 1/2 已完成，这两条应直接 PASS——help 是 typer 自动生成的。若 FAIL 说明 Task 1/2 参数没加对，回去修。）

- [ ] **Step 2: 跑测试确认通过**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py tests/unit/test_moc_cli.py -v`
Expected: 三个文件全 PASS

- [ ] **Step 3: 改 SKILL.md**

`skills-recommend/pi/jfox-moc/SKILL.md` 两处改动：

1. 删除第 18 行（frontmatter 下方）的例外注释整段：

```markdown
> 复用 `/skill:jfox-common` §4.1 共享约定（`--kb` / `--format json`）。注意：moc 命令组中 `diagnose` 支持 `--json` 简写，`create` / `update` 需用 `--format json`。
```

替换为：

```markdown
> 复用 `/skill:jfox-common` §4.1 共享约定（`--kb` / `--json`，等价于 `--format json`）。
```

2. Step 2 示例 `jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --format json` 中 `--format json` → `--json`；Step 4 示例 `jfox moc update --format json` 和 `jfox moc update --id <moc_id> --format json` 中 `--format json` → `--json`。

- [ ] **Step 4: markdownlint 检查**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && npx --yes markdownlint-cli2 skills-recommend/pi/jfox-moc/SKILL.md`
Expected: 无错误（exit 0）

- [ ] **Step 5: Commit**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand
git add skills-recommend/pi/jfox-moc/SKILL.md tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py
git commit -m "docs(skill): jfox-moc uses --json shorthand after CLI alignment (#425)"
```

---

### Task 4: 全量快速测试兜底

**Files:** 无（纯验证）

- [ ] **Step 1: 跑 moc 相关全部测试**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/ -k moc -v`
Expected: 全 PASS

- [ ] **Step 2: 跑更宽的快速单测（不加载 embedding）**

Run: `cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-425-moc-create-update-json-shorthand && .venv/bin/python -m pytest tests/unit/ -m "not embedding" -v`
Expected: 全 PASS（若个别与本次改动无关的测试失败，记录并评估，不阻塞——但要与 main 上同一测试基线对比确认非本次引入）
