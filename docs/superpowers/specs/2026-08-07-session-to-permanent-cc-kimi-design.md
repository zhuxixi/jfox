# session-to-permanent skill —— CC + Kimi 平台适配设计

- **issue**: #317（pi 已在 #366 合入，本设计覆盖剩余 CC + Kimi 两平台）
- **日期**: 2026-08-06
- **PR 粒度**: 一个 PR 同时做两平台，合并后关闭 #317

## 目标

把 pi 平台已实现的 `jfox-session-to-permanent` skill（#366）适配到 CC 和 Kimi 两平台。核心 SKILL.md 的五步流程（提取 → 去重 → 起草 → 审阅 → 落库，去重和审阅两条硬约束）三平台一致，差异集中在三处。

## 设计基线

以 pi `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` 为内容范本。三平台交叉引用约定不同（#366 已论证无法共用同一份模板），故各自维护一份 SKILL.md。

## 三个差异维度

### 1. 交叉引用前缀（pi 版的 `/skill:jfox-xxx` 按平台替换）

| 引用对象 | CC | Kimi | pi（已实现，不改） |
|---------|----|----|----|
| 共享约定（`--kb`/`--json`/`--content-file`） | `/jfox:manage` §4.1 | `/skill:jfox-manage` §4.1 | `/skill:jfox-common` §4.1 |
| `jfox add` 通用参数 | `/jfox:manage` §4.2 | `/skill:jfox-manage` §4.2 | `/skill:jfox-common` §4.2 |
| suggest-links 误命中坑 | `/jfox:promote` §6 | `/skill:jfox-promote` §6 | `/skill:jfox-promote` §6 |
| organize（图谱健康度目标） | `/jfox:organize` Step 3 | `/skill:jfox-organize` Step 3 | `/skill:jfox-organize` Step 3 |
| 写入后验证 | `/jfox:manage` §4.5 | `/skill:jfox-manage` §4.5 | `/skill:jfox-common` §4.5 |
| daemon 启动 | `/jfox:manage` §6 | `/skill:jfox-manage` §6 | `/skill:jfox-common` §6 |

### 2. 审阅交互（Step 4）

pi 版用 pi 的 `question` 工具出四选项选择题（#367）。**CC 和 Kimi 均有 AskUserQuestion 工具**（用户确认），两平台都改用 AskUserQuestion 出同样四选项：

- 全部写入 → 进 Step 5 落库
- 跳过某条 → 二次选择列出草稿编号，选中即跳过
- 改某条 → 二次选择列出草稿编号，按反馈改完重新展示后回到本选择题
- 其他 → 请用户自由说明（混合处置、调标题/标签等）

保留 pi 版的分批规则（每批 ≤ 5 条）、批次间继续确认的结构。伪代码从 pi 的 `question(...)` 改写为 AskUserQuestion 的概念描述（`question` + `options[{label, description}]`），**不绑定具体平台 API 签名**——两平台 AskUserQuestion 细节若有差异，用概念描述规避。

### 3. `--kb` 处理

pi 版写死默认知识库（不带 `--kb`，呼应原 #365）。**CC/Kimi 不沿用**——参照两平台 session-summary 的约定，显式 `--kb <kb-name>`，走 manage §4.1 共享约定。前置条件改为「确认目标知识库（通过 `--kb` 或当前默认）」，与 session-summary 一致。

## 文件改动清单

### 新增（2 个 SKILL.md）

1. **`packages/cc-plugin/skills/session-to-permanent/SKILL.md`**
   - frontmatter `name: session-to-permanent`（无前缀，与 CC 现有 skill 命名一致）
   - description 与 pi 对齐（英文 + 触发词），交叉引用改 `/jfox:xxx`
   - 审阅交互改 AskUserQuestion，`--kb` 显式

2. **`packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`**
   - frontmatter `name: jfox-session-to-permanent`（`jfox-` 前缀，与 Kimi 现有 skill 一致）
   - description 与 pi 对齐，交叉引用改 `/skill:jfox-xxx`
   - 审阅交互改 AskUserQuestion，`--kb` 显式

### 同步入口文件（3 处）

3. **`packages/cc-plugin/skills/using-jfox/SKILL.md`**
   - 路由表「我该用哪个 skill」加一行：会话提炼永久笔记 → `session-to-permanent`
   - 职责列表（当前 5 条）加一条 session-to-permanent 一句话职责（5 → 6）
   - 复合工作流「会话沉淀」改为按需分流（summary 存档 / session-to-permanent 提炼）

4. **`packages/kimi-plugin/README.md`**
   - 功能表（9 行）加 `jfox-session-to-permanent` 行；标题「9 个核心 skill」→「10 个」
   - 文件结构树加 `jfox-session-to-permanent/` 目录
   - 「与 Claude Code 插件的差异」表核心技能清单两端各加 session-to-permanent

5. **`packages/kimi-plugin/skills/using-jfox/SKILL.md`**
   - 术语映射表加一行：会话提炼永久笔记 → `/skill:jfox-session-to-permanent`
   - 跨 skill 引用语法列表加 `/skill:jfox-session-to-permanent`

### 不改

- 两平台 manifest（`plugin.json` / `kimi.plugin.json` 均目录自动发现 skills，grep 确认不枚举 skill 列表）
- pi 版文件（#366 已合，不动）
- jfox CLI 代码（纯文档 skill）

## 验收标准对照（#317）

- [x] pi SKILL.md（#366 已做）
- [ ] CC `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- [ ] Kimi `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- [x] 三平台核心内容一致（五步流程 + 两硬约束 + clear-reports 写作规范），仅交叉引用/交互/`--kb` 按平台适配
- [ ] 触发词覆盖（`session to permanent` / `提炼到永久笔记` / `会话沉淀永久笔记`）
- [ ] 强制 `jfox search` / `suggest-links` 去重和关联
- [ ] 落库前展示草稿 + 用户确认（AskUserQuestion）
- [ ] 正确嵌入 `[[wiki links]]`（精确标题，引 promote §6 悬空坑）

## 非目标

- 不改 pi 版 SKILL.md（#366 已合）
- 不改 manifest / marketplace 版本号（纯加 skill，非发版轨道）
- 不做 issue 建议的「共享模板」机械抽取（#366 已论证三平台引用约定不同，各自适配更稳）

## 风险与对策

- **Kimi AskUserQuestion 能力/语法与 CC 的差异** → SKILL.md 用概念描述（`label` + `description` 四选项），不写死 API 签名
- **Zima 双 Bot 对文档严格**（memory：改 skill 文档易多轮挑 drift）→ 走完整 spec + plan；三平台交叉引用逐条核对；同步文件全量 grep 不漏副本
