# Markdownlint 引入设计（issue #411）

> 2026-08-22。统一 jfox 全仓 Markdown 风格，消除 pi-lens autofix 冲突类噪声，CI 获得对 md 文件的真实执行力。

## 1. 背景

- jfox 无 Markdown 风格约定：无 markdownlint 配置、CI lint 只跑 ruff+black。
- pi-lens（pi-coding-agent 代码智能层）默认规则集启用 markdownlint 且 dispatch autofix 会改 agent 编辑过的 md 文件：README 表格分隔行被反复改成对齐风格（MD055/MD056），产生 20+ 行无意义 diff 噪声（PR #408），`git checkout` 恢复动作又被视为编辑再次触发，形成死循环。
- pi-lens 已于 2026-08-21 卸载，autofix 冲突的直接来源已消除；本设计剩下两个目标：**全仓风格统一** + **CI 执行力**（不依赖任何单方 agent 工具）。

## 2. 决策表

| 决策点 | 选择 | 依据 |
| --- | --- | --- |
| 工具 | markdownlint-cli2 v0.23.2（Node，markdownlint v0.41.1） | issue 提案指定 Node 版；v0.23.2 支持 MD060 等新规则与 per-file overrides |
| 规则基线 | markdownlint 默认规则集 | 与 pi-lens core.json 同源（默认集），风格权威性足够 |
| MD013 行宽 | 禁用 | 表格长行与长 URL 无法折行，README 现状即超宽（2636 处） |
| MD024 重复标题 | `siblings_only` | 同级内允许重复（docs 中「示例」类标题常见），父级仍禁止 |
| MD060/MD055 表格样式 | 禁用 | 分隔行两侧空格对渲染零差别；强制统一产生 1442 处改动、即 PR #408 的噪声源头 |
| MD040 fence 语言 | 禁用 | 纯文本 fence（无语言可标）大量存在 |
| MD036 粗体标题 | 禁用 | `**粗体标题**` 是 docs 常见习惯 |
| MD033 内联 HTML | 禁用 | 个别文档需要 |
| MD001 标题跳级 | 禁用 | docs/superpowers/plans 生成模板固定 `# → ###` 跳级（13 文件），模板在外部 skill 不可改 |
| MD041 首行标题 | 仅对 `.github/PULL_REQUEST_TEMPLATE.md` override 禁用 | PR 模板以 `##` 开头是 GitHub 惯例（H1 会重复 PR 标题） |
| MD031/MD032 | 仅对 `jessica-jones-static-cable.md` override 禁用 | 对话记录式文档：fence 嵌在列表项内，插空行破坏列表语义 |
| 其余规则 | 全部启用 | --fix 后剩余 13 处人工修，规模可控 |
| 检查范围 | 全部 git 跟踪 md（183 个，含 docs/superpowers、skills-recommend） | 一次性对齐后 CI 全仓执行，无边界特例 |
| CI 形态 | 现有 integration-test.yml lint job 加 markdownlint 步骤 + paths 扩展 | 主分支保护要求 `quality-gate` check（该 workflow 产物）；独立 workflow 的 check 过不了保护 |

## 3. CI 集成设计

- `integration-test.yml` 的 lint job 增加 `actions/setup-node@v4`（node 22）+ `npx --yes markdownlint-cli2@0.23.2` 步骤（Ubuntu 单跑）。
- workflow 级 paths 过滤增加 `**/*.md` 与 `.markdownlint-cli2.jsonc`，保证 md-only PR 也触发 lint + quality-gate。
- 代价：md-only PR 会连带跑 test-fast（Ubuntu+Windows ~25min）。这是分支保护（quality-gate = lint+test-fast 全过）的固有成本，md-only PR 频率低，可接受。
- markdownlint-cli2 自动发现根目录 `.markdownlint-cli2.jsonc` 并遵循 .gitignore，无需额外 glob 配置。

## 4. 非目标

- 不改 docs/superpowers/plans+specs 的生成模板（模板在外部 superpowers skill，不在本仓）。
- 不引入 prettier 等其他 md 格式化工具（保持单一 lint 工具）。
- 不强制表格对齐风格（MD060 禁用是有意为之：避免噪声）。
- 不处理 pi-lens 本身（已卸载，见 KB 永久笔记）。

## 5. 验收标准

- 配置 `.markdownlint-cli2.jsonc` 落盘，禁用/override 均有注释说明理由。
- 全仓对齐为独立 PR（纯 style diff，不混功能改动）。
- CI lint job 含 markdownlint 步骤且通过（`gh pr checks` 全绿含 quality-gate）。
- 幂等验证：对齐后连续 lint 两遍，第二遍 0 issues。
- 表格完整性：fix 后所有表格行/列数与 fix 前一致（MD032 全在表格外，实测 0 处表格内插行）。
- AGENTS.md 记录 Markdown 风格约定（工具、命令、CI 门禁）。
