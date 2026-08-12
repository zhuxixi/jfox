# Plan: NoteIndex frontmatter 行数上限静默丢弃（#380）

对应 spec：`specs/2026-08-12-noteindex-frontmatter-limit-drop-design.md`

## Task 1 — 回归测试（先红）

文件：`tests/unit/test_note_index.py`，新增 class `TestNoteIndexLargeFrontmatter`（或并入
`TestNoteIndexInvalidFiles`）。

- fixture/inline：构造一条 frontmatter 行数 > 旧上限 200（取 245：240 条 backlinks + 5 行其它字段）
  的 permanent 笔记，写入 `cfg.notes_dir/permanent/`。
- 断言：
  - `find_by_title(...)` 命中（非 None），`id` 正确 —— 直接回归 #380。
  - `_parse_frontmatter_only(filepath)` 非 None。
- 另加一条：超限（构造远超 50000 行的病理 frontmatter 不现实，改为直接 monkeypatch
  `_MAX_FRONTMATTER_LINES` 到小值如 5，构造 >5 行 frontmatter，断言返回 None 且
  `caplog` 捕获到 `WARNING` 级日志、日志含文件名 —— 锁定「超限不再静默」）。

验证：`uv run pytest tests/unit/test_note_index.py -v`（新测试红，旧测试绿）。

## Task 2 — 修复（转绿）

文件：`jfox/note_index.py`

- `_MAX_FRONTMATTER_LINES = 200` → `50000`，注释更新为「防御性 guard：frontmatter 不闭合时
  避免读全文件；远超现实 backlinks 上限，正常笔记读到闭合 `---` 即 break，无性能影响」。
- 超限分支：`return None` 前加 `logger.warning(f"frontmatter 超过 {_MAX_FRONTMATTER_LINES} 行上限，
  已跳过：{filepath}")`。

验证：Task 1 测试转绿；`uv run pytest tests/unit/test_note_index.py -v` 全绿。

## Task 3 — 全量校验 + lint

- `uv run pytest tests/unit/ -q`（快速单测全过，不触发 embedding/slow）。
- `uv run ruff check jfox/note_index.py tests/unit/test_note_index.py`。
- `uv run black --check jfox/note_index.py tests/unit/test_note_index.py`
  （用 `uv run --with black==26.3.1 black --check ...` 若缺，见 memory `run-black-not-just-ruff`）。

## Task 4 — 提交 + CR + PR

- `git add` 按文件 stage（note_index.py、test_note_index.py、spec、plan）。
- 本地 CR（`feature-dev:code-reviewer` 或 `/code-review`，深度自定）。
- push + `gh pr create --head`，PR body 含根因/修复/测试/复现链接，关 #380。
- 打 `zima:needs-review`，走 zima-pr-monitor babysit。

## 非任务（确认不做）

- index verify 接入 NoteIndex invalid files。
- backlinks 截断策略。
