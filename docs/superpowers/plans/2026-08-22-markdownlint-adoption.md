# Markdownlint 引入实施计划（issue #411）

> 对应设计：`docs/superpowers/specs/2026-08-22-markdownlint-adoption-design.md`。
> 所有改动在 worktree `issue-411-markdownlint-style` 内进行，纯 style diff，不混功能改动。

### Task 1: 落盘 markdownlint 配置

- 新增 `.markdownlint-cli2.jsonc`：规则集（默认集 + 7 条禁用 + 2 处 per-file override），每条禁用带注释理由。
- 验证：`npx --yes markdownlint-cli2 --no-globs <md列表>` 违规数从 ~6000 降到 ~1535（禁用规则生效）。

### Task 2: CI 集成

- 修改 `.github/workflows/integration-test.yml`：
  - lint job 增加 setup-node（node 22）+ `npx --yes markdownlint-cli2@0.23.2` 步骤。
  - push/pull_request 的 paths 过滤增加 `**/*.md`、`.markdownlint-cli2.jsonc`。
- 验证：本地跑 markdownlint-cli2 通过；PR 提交后 `gh pr checks` 出现 lint job 且 markdownlint 步骤通过。

### Task 3: 全仓一次性对齐

- 对 183 个 git 跟踪 md 跑 `npx --yes markdownlint-cli2 --fix`（预期 ~144 个文件变动，单文件最大 diff ~73 行）。
- 13 处人工修复（--fix 无法安全处理的）：
  - `DEVELOPMENT_PLAN.md`：MD029 有序列表编号 1..6 重排（3 处）。
  - `docs/superpowers/specs/2026-08-11-permanent-note-template-design.md`：blockquote 空行补 `>`（1 处）。
  - `packages/kimi-plugin/skills/jfox-manage/SKILL.md`、`jfox-promote/SKILL.md`：blockquote 空行补 `>`（2 处）。
  - `docs/superpowers/specs/2026-08-20-bm25-clear-orphan-followup-design.md`：`#396` 行首变 H1 假标题 → 前缀 `PR `（同时消 MD025+MD026）。
  - `docs/superpowers/specs/2026-07-26-kb-backup-restore-design.md`：MD056 表格缺列行修复（1 处）。
  - `README.md`：Platform badge 空链接 `](#)` → 去掉链接包裹（1 处）。
  - `SESSION_SUMMARY.md`：4 处标题前补空行（MD022）。
- 验证：再次 lint 全仓 = 0 issues。

### Task 4: 幂等 + 表格完整性验证

- 连续 lint 两遍，第二遍 0 issues（幂等）。
- 表格完整性：对比 fix 前后所有含 `|` 行的行数与列数（MD032 实测 754 处全在表格外，0 处表格内插行）。

### Task 5: AGENTS.md 约定

- 增加「Markdown 风格约定」节：工具与版本、配置文件位置、本地命令（lint / fix）、CI 门禁、禁用规则速览。

### Task 6: PR + Zima CR + 合并

- 开 PR（base main），打 `zima:needs-review`，前台阻塞等 CR（wait-cr.py helper）。
- 按 CR 收敛判定修 finding（若有），CI 全绿 + quality-gate 通过后 squash 合并。
- 关 issue #411（验收标准逐项核对），清理 worktree，更新 KB 永久笔记。
