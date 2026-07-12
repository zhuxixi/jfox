# 设计：jfox show 支持 --json 输出

- **Issue**: [#278](https://github.com/zhuxixi/jfox/issues/278)
- **日期**: 2026-07-12
- **类型**: 功能增强（enhancement）
- **分支**: `feat/show-json-278`

## 背景

`jfox show` 当前只输出原始 Markdown（含 YAML frontmatter），不支持 `--json`。LLM 工具调用、Python 脚本、jq 难以程序化消费笔记内容，且需手动解析 frontmatter。其他命令（`list` / `search` / `graph` / `refs`）已支持 `--format json`，`show` 是一致性缺口。

## 目标

1. `jfox show <id_or_title> --json`（及 `--format json`）输出单个结构化 JSON 对象。
2. 默认行为（输出原始 Markdown）**严格不变**，向后兼容。
3. schema 与 `list --json` 等保持一致风格，复用现有 `output_json()`。

## 既有资产（复用 WIP）

git stash commit `d2df418`（2026-06-23, "WIP: jfox show --json (issue #278)"）已有完整实现，schema 与本设计一致且含 candidate 专属字段。本设计**完全复用其方案**。依赖在当前 main 全部满足：

- `NoteType.CANDIDATE`（models.py:47）
- `GemLevel` + `GemLevel.FLAWED`（models.py:50）
- `filepath` property（models.py:112）
- `re` 已 import（models.py:3）

## 设计

### 架构（3 文件改动，全复用现有模式）

**1. `jfox/models.py` — 新增 `Note.to_show_dict(raw_markdown=None) -> Dict[str, Any]`**

与 `to_markdown` 同级的新方法。返回结构化字典：

- **基础字段**（所有类型）：`id`、`title`、`type`(`.value`)、`created`(`.isoformat()`)、`updated`(`.isoformat()`)、`tags`、`links`、`backlinks`、`topic`、`path`(`str(filepath)`)、`content`、`content_body`
- **`content`**：原始 Markdown（含 frontmatter）。优先用传入的 `raw_markdown`，未提供则 `to_markdown()` 重新生成。
- **`content_body`**：去 frontmatter 的正文，用 `re.match(r"^---\n.*?\n---\n+(.*)", content, re.DOTALL)` 提取；无 frontmatter 时等于 `content`。
- **可选字段**：`source`（非 None 时输出）、`archived`（True 时输出）。
- **candidate 专属**（`type == NoteType.CANDIDATE`）：`gem_level`（默认 `GemLevel.FLAWED.value`）、`confidence`（非 None）、`source_fragments`（非空）、`grounded_by`（非空）、`knowledge_type`（非 None）、`status`（非 None）。

**2. `jfox/cli.py` — `_show_impl(note_ref, output_format="markdown")`**

增 `output_format` 参数。逻辑：

```
定位 + 加载笔记（不变）：find_note_id_by_title_or_id → load_note_by_id
raw = n.filepath.read_text(encoding="utf-8")
output_format == "json" ? print(output_json(n.to_show_dict(raw_markdown=raw)))
                        : print(raw)        # 默认行为不变
```

**3. `jfox/cli.py` — `show` 命令签名**

增两个参数：

- `output_format: str = typer.Option("markdown", "--format", "-f", help="输出格式: markdown, json")`
- `json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）")`

向后兼容：`if json_output: output_format = "json"`，然后 `_show_impl(note_ref, output_format)`。

### 数据流

```
show <ref> [--format json | --json] [--kb X]
  → use_kb(kb) → _show_impl(note_ref, output_format)
    → find_note_id_by_title_or_id(note_ref) → load_note_by_id
    → raw = n.filepath.read_text(encoding="utf-8")
    → output_format == "json" → print(output_json(n.to_show_dict(raw_markdown=raw)))
    → 否则                       → print(raw)
```

### 错误处理

笔记不存在 → `raise ValueError` → `show` 捕获 → `Exit(1)`。错误输出按模式分流：

- **默认（markdown）模式**：`console.print("[red]✗[/red] Error: {e}")`（不变）。
- **JSON 模式**：`print(output_json({"success": False, "error": str(e)}))`——结构化错误，便于程序化消费（否则调用方 `json.loads` 会炸）。

`--format` 取值不显式校验：非 `"json"` 一律走默认 markdown 分支（等价 raw 输出）。保持简单，避免引入不必要的报错路径。

### 测试（`tests/unit/test_show.py`）

- **修** `test_show_calls_impl`：`_show_impl` 多了 `output_format` 参数，断言改用 `assert_called_once()` 或匹配新签名。
- **新增**：
  - `test_show_json_output`：`show --json <id>` 输出合法 JSON，含全部基础字段。
  - `test_show_content_body_strips_frontmatter`：`content_body` 不含 frontmatter。
  - `test_show_json_candidate_fields`：candidate 笔记含 `gem_level` / `status` 等专属字段。
  - `test_show_default_raw_markdown`：无 flag 时输出原始 Markdown（回归保护）。

## 验收标准

- [ ] `jfox show <ref> --json` 与 `--format json` 输出等价的结构化 JSON。
- [ ] JSON 含 issue schema 的全部基础字段；`type == candidate` 时含 candidate 专属字段。
- [ ] `content_body` 正确去除 frontmatter。
- [ ] 默认（无 flag）输出与改动前完全一致（raw Markdown）。
- [ ] JSON 模式下错误返回结构化 `{"success": false, "error": ...}`。
- [ ] `jfox show --help` 列出新选项。
- [ ] 单元测试通过（含回归）。

## 不做（scope 边界）

- 不改 `show` 的非 JSON 输出格式。
- 不加 `--format yaml/csv`（YAGNI，issue 只要 json）。
- 不校验 `--format` 取值（非 json 走默认，简单优先）。
- 不动其他命令。

## 风险

- 现有 `test_show.py` 断言因签名变化失效 → 测试一并更新（已纳入计划）。
- `content_body` 正则在无 frontmatter / 多种 frontmatter 风格下的健壮性 → 测试覆盖。
