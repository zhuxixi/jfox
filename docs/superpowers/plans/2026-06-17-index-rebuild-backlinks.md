# Issue #252: `jfox index rebuild` 重新计算 backlinks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `jfox index rebuild` 支持 `--backlinks` 选项，在重建索引时重新解析 wiki links 并计算 backlinks。

**Architecture:** 在 `jfox/cli.py` 中新增 `_rebuild_backlinks_impl()` 内部函数，在 `index rebuild` action 中按用户传入的 `--backlinks` 标志调用；函数全量加载笔记、解析 `[[...]]` 链接、解析目标 ID、重新计算并写回变化的笔记。

**Tech Stack:** Python, Typer, pytest

---

### Task 1: 实现 `_rebuild_backlinks_impl()` 内部函数

**Files:**
- Modify: `jfox/cli.py`（在 `extract_wiki_links` / `find_note_id_by_title_or_id` 附近或 `_add_note_impl` 之后新增函数）

- [ ] **Step 1: 编写核心函数**

  新增函数签名：
  ```python
  def _rebuild_backlinks_impl(output_format: str = "table") -> Dict[str, Any]:
      ...
  ```

  功能：
  1. 调用 `note.list_notes(limit=10000)` 加载所有笔记
  2. 遍历笔记，调用 `extract_wiki_links(note.content)` 提取链接
  3. 调用 `find_note_id_by_title_or_id(link_text)` 解析目标 ID
  4. 构建 `new_links: Dict[str, List[str]]` 和 `new_backlinks: Dict[str, List[str]]`
  5. 对每个笔记，比较现有 `links`/`backlinks` 与新计算结果
  6. 如有变化，更新 Note 对象并调用 `note.save_note(note, add_to_index=False)`
  7. 返回统计信息：`backlinks_rebuilt`, `backlinks_updated`, `backlinks_total`, `unresolved_links`

- [ ] **Step 2: 处理边界情况**

  - 空知识库：返回 `backlinks_total=0`, `backlinks_updated=0`
  - 未解析链接：收集到 `unresolved_links` 列表中用于警告输出
  - 保存失败：记录 warning，不中断流程

---

### Task 2: 在 `index rebuild` action 中集成 `--backlinks` 选项

**Files:**
- Modify: `jfox/cli.py:index()` 命令参数
- Modify: `jfox/cli.py` 中 `action == "rebuild"` 分支

- [ ] **Step 1: 添加 Typer 选项**

  在 `index()` 命令中新增：
  ```python
  backlinks: bool = typer.Option(False, "--backlinks", "-b", help="重建时重新计算 backlinks"),
  ```

- [ ] **Step 2: 在 rebuild action 中调用**

  在 `action == "rebuild"` 分支中，BM25 重建完成后：
  ```python
  if backlinks:
      bl_result = _rebuild_backlinks_impl(output_format)
      result.update(bl_result)
  ```

- [ ] **Step 3: 更新输出**

  JSON 输出：合并 `backlinks_rebuilt`, `backlinks_updated`, `backlinks_total`, `unresolved_links`
  Table 输出：增加对应行，显示 `Backlinks rebuilt: X / Y`，以及未解析链接警告

---

### Task 3: 编写测试

**Files:**
- New: `tests/integration/test_index_rebuild_backlinks.py`
- New: `tests/unit/test_rebuild_backlinks_impl.py`

- [ ] **Step 1: 编写集成测试**

  `tests/integration/test_index_rebuild_backlinks.py`：
  - 使用 `cli` fixture 初始化临时知识库
  - 创建目标笔记 A 和源笔记 B（B 引用 A）
  - 手动修改 A 的 frontmatter，移除其 `backlinks`
  - 执行 `cli.index("rebuild", "--backlinks")`
  - 验证 `refs A` 的 `backward_links` 包含 B
  - 验证 JSON 输出中的 `backlinks_updated > 0`

- [ ] **Step 2: 编写单元测试**

  `tests/unit/test_rebuild_backlinks_impl.py`：
  - Mock `note.list_notes()` 返回若干笔记对象
  - 调用 `_rebuild_backlinks_impl()`
  - 验证统计信息正确
  - 验证 `save_note` 只在变化时调用

- [ ] **Step 3: 验证默认行为不变**

  集成测试增加：
  - 默认 `jfox index rebuild`（无 `--backlinks`）不应修改任何笔记的 backlinks

---

### Task 4: 运行测试与代码检查

- [ ] **Step 1: 运行新增单元测试**

  ```bash
  uv run pytest tests/unit/test_rebuild_backlinks_impl.py -v
  ```

- [ ] **Step 2: 运行新增集成测试**

  ```bash
  uv run pytest tests/integration/test_index_rebuild_backlinks.py -v
  ```

- [ ] **Step 3: 运行快速测试集**

  ```bash
  uv run pytest tests/ -m "not embedding and not slow" -q
  ```

- [ ] **Step 4: 代码风格检查**

  ```bash
  uv run ruff check jfox/cli.py tests/unit/test_rebuild_backlinks_impl.py tests/integration/test_index_rebuild_backlinks.py
  uv run black --check jfox/cli.py tests/unit/test_rebuild_backlinks_impl.py tests/integration/test_index_rebuild_backlinks.py
  ```

---

### Task 5: 提交与 PR

- [ ] **Step 1: 整理提交**

  使用 Conventional Commits：
  ```bash
  git add jfox/cli.py tests/unit/test_rebuild_backlinks_impl.py tests/integration/test_index_rebuild_backlinks.py docs/superpowers/specs/2026-06-17-index-rebuild-backlinks-design.md docs/superpowers/plans/2026-06-17-index-rebuild-backlinks.md
  git commit -m "fix(cli): jfox index rebuild --backlinks recalculates wiki links and backlinks

  - Add --backlinks/-b option to jfox index rebuild
  - Add _rebuild_backlinks_impl() to parse [[...]] links and recompute backlinks
  - Update output JSON/table with backlinks rebuild stats
  - Add unit and integration tests

  Closes #252"
  ```

- [ ] **Step 2: 推送分支**

  ```bash
  git push origin fix/252-index-rebuild-backlinks
  ```

- [ ] **Step 3: 创建 PR**

  PR 标题：`fix(cli): jfox index rebuild --backlinks recalculates wiki links and backlinks`
  PR 描述包含：
  - 问题描述
  - 修改内容
  - 测试说明
  - `Closes #252`

- [ ] **Step 4: 等待 CI 通过**

  在 PR 页面确认 Fast / Core workflow 通过。
