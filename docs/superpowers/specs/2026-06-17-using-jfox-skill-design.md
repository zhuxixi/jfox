# Design: using-jfox 总览/路由 skill (cc-plugin)

> Issue: #243
> Branch: `feat/issue-243-using-jfox-skill`
> 方案: **方案 1 — 纯加法**（新增 1 个 skill，不改动现有 5 个 skill）

## 背景

JFox 的 Claude Code 插件（`packages/cc-plugin/`）当前有 5 个**能力型** skill：`search` / `ingest` / `manage` / `organize` / `session-summary`。它们各自 description + 触发词清晰，按 auto-discovery 路由已经很准。

但存在一个真实空白：**总览/元意图没有归属**。「jfox 能做什么」「我该用哪个 jfox 命令」「知识库怎么用」这类问题，5 个 skill 的 description 都不接，目前只能靠 CLAUDE.md 或 agent 自由发挥。

### 关键发现（影响设计的事实）

1. **cc-plugin 是 auto-discovery，无 `sessionStart` 注入机制。** `.claude-plugin/plugin.json` 不声明 skills 列表，也不配 sessionStart。skill 纯粹靠 description 匹配被路由。因此 cc-plugin 的 `using-jfox` **天然就是「按需路由型」**，而不是 superpowers 那种「SessionStart 强制注入的纪律型」。
2. **kimi-plugin 已有 `using-jfox`，但是相反的形态。** `packages/kimi-plugin/kimi.plugin.json` 配了 `"sessionStart": {"skill": "using-jfox"}`，其 description 写明「在新会话开始时自动加载…通过插件的 sessionStart 自动注入」。这正是 #243 论证**不应**照搬到 cc-plugin 的形态。两端会出现 `using-jfox` 语义分化（见 FU-2）。
3. **「共享约定单一来源」已有先例。** `skills-recommend/{kimi-cli,pi}/jfox-common/SKILL.md` 已把跨 skill 的公共约定拆成独立 skill，供非 CC 平台使用。
4. **备选方案 A 有结构性缺陷。** 把元意图触发词塞进 5 个 skill 的 description，会让它们竞争同一个元意图，反而恶化路由。专用 router 在结构上更干净。

## 目标

- 新增 1 个 `using-jfox` skill，**专门承接元/总览意图**，给一张「意图 → skill」能力地图，并把具体动作派发给 5 个 skill。
- 不与 5 个 skill 竞争触发：description 刻意只用元词，不含强动词（搜索/导入/整理/保存/管理）。
- 成为概念（笔记模型）与公共约定的**索引入口**（指向现有 skill，不复制内容）。
- 不引入 `sessionStart` 强制注入。

## 非目标（本期不做）

- ❌ **不编辑现有 5 个 skill 的 body**（方案 1 的核心约束）。
- ❌ **不做「单一权威来源」重构**（即不把 manage/organize 的笔记模型/约定段落改成引用 using-jfox）。该重构记为 FU-1，待 #244–247 合并后再做。
- ❌ **不配 `sessionStart` 注入**（避免纪律型 skill 的副作用与触发竞争）。
- ❌ **不在 using-jfox 内复制完整命令速查表**（命令在各 skill 里已有；复制 = 维护负担，正是 issue 警告的）。
- ❌ **本期不改 kimi-plugin 的 using-jfox**（见 FU-2）。

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 是否新增 skill | **新增** | 元意图无归属；备选 A 会造成触发竞争 |
| 内容范围 | **方案 1 纯加法** | 零风险、避开 #244–247 文件冲突；单一来源重构转 FU-1 |
| 命名 | **`using-jfox`** | 与 kimi-plugin 同名（跨插件心智一致）；符合 cc-plugin 无前缀惯例 |
| 注入方式 | **不注入（按需路由）** | cc-plugin 本就无 sessionStart；路由型无副作用 |
| 命令速查 | **不放** | 避免与各 skill 重复，规避维护负担 |

## Section 1: 文件与命名

- 新增文件：`packages/cc-plugin/skills/using-jfox/SKILL.md`（单文件，无 references 子目录）。
- skill 名：`using-jfox`（frontmatter `name: using-jfox`）。在 cc-plugin 命名空间下对外为 `jfox:using-jfox`，与其余 5 个一致。
- **不**修改 `packages/cc-plugin/.claude-plugin/plugin.json`：cc-plugin 用 auto-discovery，新 skill 放进 `skills/` 即被自动发现，无需声明。

## Section 2: description 与触发词策略（路由核心）

description 是 auto-discovery 路由的唯一依据，**最关键的防竞争设计点**。遵循 #243 指引：只用元词、不含强动词。

```yaml
name: using-jfox
description: |
  Use when the user asks meta or overview questions about jfox as a whole — what jfox
  can do, how to get started, or which jfox skill/command fits their goal. Triggers on
  "jfox 能做什么", "jfox 怎么用", "知识库怎么用", "我该用哪个 jfox 命令", "我该用哪个
  jfox skill", "jfox 有哪些功能", "jfox 入门", "jfox overview", "what can jfox do",
  "which jfox skill". This skill orients the user and routes to the specific skill; it
  is not for performing a concrete action.
```

设计约束：

- **只含元词**：能做什么 / 怎么用 / 哪个 / 入门 / overview。**不含** 搜索/导入/整理/保存/管理/创建知识库 等强动词。
- 末句「not for performing a concrete action」**刻意不点名具体动作**，避免把强动词写进 description 而被匹配器拾取。
- body 内可以出现 5 个 skill 名（路由表必需），但 body 不参与 description 匹配，不构成竞争。

## Section 3: body 内容结构（6 段）

body 给概念/约定**一句话 + 指针**，不复制完整内容。结构：

1. **JFox 是什么** — 一句话定位：本地优先的 Zettelkasten 知识管理 CLI（混合搜索 BM25+语义 + 知识图谱 + 多知识库 + Claude Code / Kimi Code 插件）。
2. **能力地图：我该用哪个 skill** — 决策表（见 Section 4）+ 5 个 skill 各一句话职责。
3. **笔记模型** — 一句话：fleeting / literature / permanent 三类 + `[[wiki link]]` 双链；深入「见 organize（Step 1–2）」。
4. **典型复合工作流** — ≥2 条（见 Section 5）。
5. **公共约定** — 一句话：所有 jfox 命令支持 `--kb`/`--json`/`--content-file`；权威「见 manage §4.1」。
6. **环境检查** — 2 行：`jfox --version`；未安装则 `uv tool install jfox-cli`。

指针锚点（已核实存在于 main）：

| 指向内容 | 锚点 |
|---------|------|
| 公共约定 `--kb`/`--json`/`--content-file` | `manage` skill §4.1 共享约定 |
| 知识库路径约定 / 多 KB | `manage` skill §2 |
| 笔记模型 + fleeting→permanent 提炼 | `organize` skill Step 1（Inbox 分析）+ Step 2（提炼） |
| 健康检查 / 衰减信号 | `manage` skill §5 |

## Section 4: 能力地图决策表（body 核心内容）

「你想做的 → 用哪个 skill」：

| 你想做的 | 用这个 skill | 典型触发词 |
|---------|-------------|-----------|
| 搜索 / 查找笔记、检索知识 | `search` | 搜索 / 查找 / find |
| 把 git 仓库 / PR / issues 导入成素材 | `ingest` | 导入仓库 / ingest repo |
| 提炼 fleeting→permanent、清理 inbox、补 wiki link、优化图谱 | `organize` | 整理 / 提炼 / clean inbox |
| 把当前会话总结存入知识库 | `session-summary` | 保存会话 / save session |
| 创建/切换/删除知识库、命令参考、健康检查、daemon | `manage` | 创建知识库 / kb status / 健康检查 |

5 个 skill 一句话职责（放在决策表下方）：

- **search** — 笔记检索：BM25 / 语义 / 混合搜索 + 知识图谱查询。
- **ingest** — git 仓库 → fleeting 素材笔记（git log / PR / issues）。
- **organize** — fleeting → permanent 提炼 + 图谱优化（orphans / 补链）。
- **session-summary** — 当前会话 → 知识库笔记。
- **manage** — 知识库生命周期 + 笔记 CRUD 权威参考 + 健康检查 + embedding daemon。

## Section 5: 典型复合工作流（body 内容，≥2 条）

1. **沉淀新知识**：`ingest`（导入素材为 fleeting）→ `organize`（提炼成 permanent + 补 `[[wiki link]]`）→ `search`（日后检索复用）。
2. **会话沉淀**：`session-summary`（把这次对话存入知识库）→ `organize`（提炼要点为 permanent）。
3. **知识库维护**：`manage` §5（体检 / 衰减信号检测）→ `organize`（清理 orphans / 补链接）。

## Section 6: 边界与不做清单

（同「非目标」，在 SKILL.md body 末尾以简短「本 skill 不做」段落地化，明确自我边界，防止 agent 误用它执行具体动作。）

## Section 7: 验收标准（对照 issue #243）

- [ ] 新增 `packages/cc-plugin/skills/using-jfox/SKILL.md`。
- [ ] description 只含元意图触发词，不含与 5 skill 重叠的强动词（可 grep 校验）。
- [ ] 包含能力地图决策表（用户意图 → skill）。
- [ ] 笔记模型 / 公共约定以「一句话 + 指针」呈现，指针锚点（manage §4.1 / organize Step 1–2）可解析。
- [ ] 覆盖 ≥2 条典型复合工作流。
- [ ] 不引入 `sessionStart` 注入；不修改 `plugin.json`。
- [ ] 不编辑现有 5 个 skill。
- [ ] 路由 sanity：问「jfox 能做什么」→ 命中 using-jfox；问「搜索笔记」→ 命中 search，**不**命中 using-jfox。

> issue §5「单一权威来源」一条：本期以「指针」实现（using-jfox 索引现有权威位置，不引入第三份副本）；完整重构转 FU-1。

## Section 8: 验证方式

本 skill 为纯 Markdown，无代码逻辑，验证以静态检查 + 路由 sanity 为主：

1. **frontmatter 合法**：YAML 可解析，`name` / `description` 字段齐全。
2. **防竞争 grep**：`description` 内不含强动词（搜索/导入/整理/保存会话/管理/创建知识库 等）—— 写一条 grep 断言。
3. **指针可解析**：body 中 `manage §4.1`、`manage §2`、`manage §5`、`organize Step 1/2` 对应章节确实存在（已核实）。
4. **路由 sanity（手动）**：装上新 skill 后，分别用元意图（「jfox 能做什么」）和具体意图（「搜索笔记」）提问，确认前者命中 using-jfox、后者命中 search。
5. **auto-discovery 可见**：新 skill 被 cc-plugin 自动发现（无需改 plugin.json）。

## Section 9: Follow-ups（本期不做，记录防漂移）

- **FU-1（方案 2 单一权威来源）**：待 #244–#247（wiki link / backlink 解析重构，正在改 organize/manage）合并后，把 using-jfox 升级为「笔记模型 + 公共约定」的单一权威来源；编辑 `manage` / `organize`，将其重复段落替换为「详见 using-jfox」。届时需验证所有 `[[link]]` / backlinks 行为未被破坏。
- **FU-2（两端一致性）**：另开 issue 评估 kimi-plugin 的 `using-jfox` 是否也应从「sessionStart 注入型」转为「按需路由型」，或显式接受两端分化并各自注明。注意两端 skill 引用语法不同（Kimi 用 `/skill:jfox-*`，CC 用 skill 名）。

## 备注

- 本 skill 与 #242（Kimi Code auto-summary）无功能耦合，同属「jfox 作为多 Agent 生态工具」的工程化议题。
- 实现极小：本质是新增一个 Markdown 文件。复杂度集中在 description 措辞与指针准确性，而非代码。
