# add --content-file Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox add` 支持 `--content-file` 选项，从文件或 stdin 读取笔记内容。

**Architecture:** 在 `add` 命令中将 `content` 从必需位置参数改为可选参数，新增 `--content-file` 选项。文件读取逻辑复用 `edit` 命令已有的模式（`cli.py` L975-986），两者互斥校验。stdin 支持通过 `--content-file -` 实现。`_add_note_impl` 签名不变。

**Tech Stack:** Python, Typer, pathlib

---

### Task 1: 文件读取逻辑提取为公共函数

**Files:**
- Modify: `jfox/cli.py` (在 `_edit_impl` 之前添加公共函数)
- Modify: `jfox/cli.py:970-986` (`_edit_impl` 调用改为使用公共函数)

**为什么先做：** `add` 和 `edit` 都需要读取 `--content-file`，提取公共函数避免重复代码，也方便单独测试。

- [ ] **Step 1: 在 `_edit_impl` 之前添加 `_read_content_file()` 函数**

在 `jfox/cli.py` 约第 958 行（`_edit_impl` 定义之前）插入：

```python
def _read_content_file(content_file: str) -> str:
    """从文件或 stdin 读取内容（--content-file 共用逻辑）"""
    if content_file == "-":
        import sys

        return sys.stdin.read()

    p = Path(content_file)
    if not p.exists():
        raise ValueError(f"文件不存在: {content_file}")
    if not p.is_file():
        raise ValueError(f"路径不是文件: {content_file}")
    try:
        return p.read_text(encoding="utf-8")
    except PermissionError:
        raise ValueError(f"无权限读取文件: {content_file}")
    except UnicodeDecodeError:
        raise ValueError(f"文件编码错误（需要 UTF-8）: {content_file}")
```

- [ ] **Step 2: 重构 `_edit_impl` 使用公共函数**

将 `jfox/cli.py` L974-986（`_edit_impl` 中的文件读取代码）：

```python
    # 从文件读取内容
    if content_file is not None:
        p = Path(content_file)
        if not p.exists():
            raise ValueError(f"文件不存在: {content_file}")
        if not p.is_file():
            raise ValueError(f"路径不是文件: {content_file}")
        try:
            content = p.read_text(encoding="utf-8")
        except PermissionError:
            raise ValueError(f"无权限读取文件: {content_file}")
        except UnicodeDecodeError:
            raise ValueError(f"文件编码错误（需要 UTF-8）: {content_file}")
```

替换为：

```python
    # 从文件读取内容
    if content_file is not None:
        content = _read_content_file(content_file)
```

- [ ] **Step 3: 运行快速回归测试，确认 edit 功能不变**

Run: `uv run pytest tests/test_cli_format.py::TestAddAndDeleteFormat -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add jfox/cli.py
git commit -m "refactor: extract _read_content_file() for shared --content-file logic"
```

---

### Task 2: add 命令支持 --content-file 选项

**Files:**
- Modify: `jfox/cli.py:366-383` (`add` 函数签名和调用)

- [ ] **Step 1: 修改 `add()` 函数签名**

将 `jfox/cli.py` L367-368：

```python
@app.command()
def add(
    content: str = typer.Argument(..., help="笔记内容（支持 [[笔记标题]] 格式链接）"),
```

改为：

```python
@app.command()
def add(
    content: Optional[str] = typer.Argument(None, help="笔记内容（支持 [[笔记标题]] 格式链接）"),
```

- [ ] **Step 2: 在 `--template` 选项之后添加 `--content-file` 参数**

在 `jfox/cli.py` L375-377（`template` 参数定义之后）插入：

```python
    content_file: Optional[str] = typer.Option(
        None, "--content-file", help="从文件读取内容（用 - 表示 stdin）"
    ),
```

- [ ] **Step 3: 在 `add()` 函数体中添加互斥校验和文件读取逻辑**

将 `jfox/cli.py` L384-397：

```python
    """添加新笔记（内容中可用 [[笔记标题]] 引用其他笔记）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _add_note_impl(content, title, note_type, tags, source, output_format, template)
        else:
            _add_note_impl(content, title, note_type, tags, source, output_format, template)
```

改为：

```python
    """添加新笔记（内容中可用 [[笔记标题]] 引用其他笔记）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        # content 和 --content-file 互斥
        if content is not None and content_file is not None:
            raise ValueError("不能同时指定内容参数和 --content-file，请选择其一")

        # 从文件读取内容
        if content_file is not None:
            content = _read_content_file(content_file)

        # 至少提供一种内容来源
        if not content:
            raise ValueError("请提供笔记内容（位置参数或 --content-file）")

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _add_note_impl(content, title, note_type, tags, source, output_format, template)
        else:
            _add_note_impl(content, title, note_type, tags, source, output_format, template)
```

- [ ] **Step 4: Commit**

```bash
git add jfox/cli.py
git commit -m "feat: add --content-file option to jfox add command"
```

---

### Task 3: 测试 --content-file 功能

**Files:**
- Modify: `tests/test_cli_format.py` (在 `TestAddAndDeleteFormat` 类中添加测试)

- [ ] **Step 1: 在 `test_add_format_json` 之前添加 --content-file 测试**

在 `tests/test_cli_format.py` 的 `TestAddAndDeleteFormat` 类中，`test_add_format_json` (L327) 之前插入：

```python
    def test_add_content_file(self, cli, tmp_path):
        """测试 add 命令 --content-file 从文件读取内容"""
        content_file = tmp_path / "note.md"
        content_file.write_text("从文件读取的笔记内容", encoding="utf-8")

        result = cli.run("add", "--content-file", str(content_file), "--title", "FileContent")

        assert result.success
        data = result.data
        assert data["success"] is True
        assert data["note"]["title"] == "FileContent"

    def test_add_content_file_mutual_exclusive(self, cli, tmp_path):
        """测试 add 命令 content 参数和 --content-file 不能同时指定"""
        content_file = tmp_path / "note.md"
        content_file.write_text("file content", encoding="utf-8")

        result = cli.run("add", "直接内容", "--content-file", str(content_file))

        assert not result.success
        assert "不能同时指定" in result.stderr or "不能同时指定" in result.stdout

    def test_add_content_file_not_found(self, cli):
        """测试 add 命令 --content-file 文件不存在时报错"""
        result = cli.run("add", "--content-file", "/nonexistent/file.md")

        assert not result.success
        assert "文件不存在" in result.stderr or "文件不存在" in result.stdout

    def test_add_content_file_empty(self, cli, tmp_path):
        """测试 add 命令不提供内容时报错"""
        result = cli.run("add")

        assert not result.success

    def test_add_content_file_with_wiki_links(self, cli, tmp_path):
        """测试 add 命令 --content-file 内容中的 [[wiki链接]] 正常解析"""
        # 先创建一个目标笔记
        cli.add("目标笔记内容", title="目标笔记")

        content_file = tmp_path / "linked.md"
        content_file.write_text("引用 [[目标笔记]] 的内容", encoding="utf-8")

        result = cli.run("add", "--content-file", str(content_file), "--title", "带链接的笔记")

        assert result.success
        data = result.data
        assert data["note"]["links"]
```

- [ ] **Step 2: 运行测试确认全部通过**

Run: `uv run pytest tests/test_cli_format.py::TestAddAndDeleteFormat -v`
Expected: 全部 PASS（包括新增的 5 个测试）

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli_format.py
git commit -m "test: add --content-file tests for jfox add command"
```

---

### Task 4: 验证 edit --content-file 回归

**Files:** 无修改

- [ ] **Step 1: 确认 edit 的 --content-file 仍然正常工作**

检查现有 edit 测试是否覆盖 --content-file：

```bash
uv run pytest tests/test_cli_format.py -v -k "edit"
```

如果 edit 的 --content-file 没有现有测试，手动验证：

```bash
uv run jfox add "原始内容" --title "编辑测试" --json
# 记录返回的 note_id
echo "新内容" > /tmp/test_edit.md
uv run jfox edit <note_id> --content-file /tmp/test_edit.md --json
```

Expected: edit 成功，内容更新为 "新内容"

- [ ] **Step 2: 确认 add 的原有行为不受影响**

```bash
uv run jfox add "直接输入的内容" --title "位置参数测试" --json
```

Expected: add 成功，内容为 "直接输入的内容"

---

## Self-Review Checklist

| 检查项 | 状态 |
|--------|------|
| `_read_content_file` 覆盖文件不存在/非文件/权限/编码错误 | Done (Task 1) |
| stdin 支持 (`--content-file -`) | Done (Task 1, `content_file == "-"` 分支) |
| `content` 和 `--content-file` 互斥校验 | Done (Task 2) |
| 都不指定时报错提示 | Done (Task 2) |
| `--content-file` 与 `--template` 交互正确（内容作为 `{{content}}` 变量） | Done (Task 2, `_add_note_impl` 未修改，`content` 变量直接传入) |
| `-f` 短选项不被占用 | Done (Task 2, `--content-file` 无短选项) |
| `wiki_links` 提取仍正常工作 | Done (Task 3 测试覆盖) |
| `edit` 命令回归安全 | Done (Task 1 提取公共函数，Task 4 验证) |
| `_add_note_impl` 签名未修改 | Done (Task 2 只在 `add()` 中读取文件后传入 `content: str`) |
