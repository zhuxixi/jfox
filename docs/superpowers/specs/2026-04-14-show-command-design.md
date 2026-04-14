# `jfox show` 命令设计

## 问题

jfox 缺少只读查看单条笔记完整内容的命令。现有命令要么只显示摘要（search），要么只列标题（list），要么会触发修改流程（edit）。

## 方案

新增 `jfox show <note_id_or_title> [--kb <name>]` 命令，直接输出原始 Markdown 文件内容。

### 输入

- 必选参数：笔记 ID 或标题
- 复用 `find_note_id_by_title_or_id` 定位逻辑，优先级：精确 ID → 精确标题 → 标题包含
- 可选 `--kb` 切换知识库

### 输出

- 直接 `print` 原始 Markdown 文件内容（frontmatter + body）
- 不做任何格式化、高亮或截断
- 找不到笔记时报错并 `exit(1)`

### 不支持

- 不支持 `--format`，纯 Markdown 输出
- 不支持 `--json`

## 实现

仅修改 `cli.py`：

1. 新增 `show` command 函数，参数：`note_ref: str`（必选）、`--kb`
2. 新增 `_show_impl(note_ref)` helper：
   - 调用 `find_note_id_by_title_or_id` 定位笔记
   - 调用 `note.load_note_by_id` 加载笔记
   - `note.filepath.read_text(encoding='utf-8')` → `print`
3. 遵循现有命令模式（`@app.command()` → `_xxx_impl` helper + `--kb` 支持）

不涉及 `note.py`、`models.py`、`formatters.py` 的修改。

## 测试

- 快速单元测试：mock `load_note_by_id`，验证正确输出 Markdown 内容
- 边界情况：笔记不存在时的错误处理
