# Spec：skill 体系同步 #399 —— overview 退役引用清理 + jfox-judge 新 skill

日期：2026-09-10
Issue：zhuxixi/jfox#513
类型：skill 文档体系建设（纯文档 PR，无代码改动）
状态：draft，待用户审阅

## 1. 背景与目标

#399（gem-synth 退役 → prompt 记录 + 按需判断）已全部合入（#491–#498）并随 1.14.0 发布。jfox-promote 三个镜像已同步，但 skill 体系仍有两处欠账：

1. `skills-recommend/pi/jfox-overview/SKILL.md` 有 3 处退役引用（路由表 L44、一句话职责 L63、复合工作流 §2 L77）
2. prompt 判断闭环（`jfox prompts` 12 命令族）无 skill 覆盖——用户说「判断 prompt」「prompt 积压」时无路由

**目标**：清理退役引用 + 新建 `jfox-judge` skill，使 skill 体系与新命令面（1.14.0）一致。

## 2. 设计决策

| 编号 | 决策点 | 结论 | 理由 |
|------|--------|------|------|
| D1 | 新建 jfox-judge vs 路由到 promote | **新建，端到端定位** | 日常增量流程需要一站式：判断 → 合成 candidate → 确认晋升同一动线完成（`jfox prompts promote <ID>` 捷径命令已支持从 prompt 直接晋升）；`--allow-remote`/`--force --reason` 等安全细节值得独立沉淀；与 promote 的意图无重叠（judge 管日常增量，promote 管存量大积压清理） |
| D2 | 改动范围 | **仅 pi 侧 `skills-recommend/pi/`** | cc/kimi 无 overview 镜像（调研确认）；jfox-judge 的 cc/kimi 镜像列为 follow-up（kimi 侧无 prompt capture 链路，镜像暂无意义；cc 侧有 capture 可后续补） |
| D3 | overview 复合工作流 §2 改写 | `hook 全量记录 prompt（后台）→ jfox-judge（判断 + 确认晋升 permanent）→ jfox-search`；末尾注「存量 candidate 积压清理用 jfox-promote」 | 端到端定位；promote 仍在路由表与一句话职责中保留（其存量清理职责不变） |
| D4 | overview 路由表 + 一句话职责 | 各新增一行 jfox-judge（15→16 skill） | 「判断 prompt / 处置判断结果」是独立意图，需可路由 |
| D5 | jfox-promote 是否改动 | **不改内容，定位收窄说明写入 jfox-judge** | promote 已同步（candidate 由 judge 生成的说明已在 L14）；jfox-judge 的「分工」节写明：日常增量端到端走本 skill，积压 >50 / 存量清理切 jfox-promote 三模式 |
| D6 | jfox-judge 内容骨架 | 见 §3（端到端五节） | 依据 issue 骨架建议 + KB 沉淀（重构方向笔记、capture 链路契约笔记）+ README L113-136 权威源 + `jfox prompts promote <ID>` 捷径命令 |

## 3. jfox-judge skill 骨架（D6 展开）

**frontmatter**

- name: `jfox-judge`
- description（英文）+ Triggers: 「判断 prompt」「prompts judge」「prompt 积压」「待解决问题清单」「judge prompts」「处置判断结果」

**正文结构**（五节）

1. **职责一句话**：端到端工作流——把采集的 user prompt 判断成四类（new→candidate / repeated→unresolved / recorded / needs_review），new 草稿当场确认晋升 permanent；judge 仅手动触发，agent 只起草不晋升。
2. **标准流程（端到端）**：
   - `jfox prompts status` 看积压（total/unjudged/failed/pending_disposition）
   - `jfox prompts judge`（小批量，默认批量上限）`--limit N` / `--all` / `--retry-failed` / `--session <id>`
   - 读报告逐条处置（new 类：`jfox prompts show <ID>` 或 `jfox candidates show <note_id>` 看草稿 → 用户确认 → `jfox prompts promote <ID>` 晋升 / `ignore <ID> --reject-candidate` 拒绝；repeated 类：询问用户 → `unresolved <ID>` 标记待解决；failed/needs_review：`retry <ID>` 重判或 `ignore <ID>` 忽略）
   - 闭环：`jfox prompts resolve-unresolved <ID>` 解决待解决问题
3. **安全注意**：
   - judge 仅手动触发（无后台循环）；本地 pi runner 默认禁工具/会话/扩展/skills/项目上下文，prompt 走 stdin
   - 远程 runner 需显式 `--allow-remote`（transcript 全文出机器，隐私边界）
   - 前置条件不满足时 `--force --reason` 留痕覆盖（默认动作拒绝执行）
4. **数据运维**：
   - daemon 停机兜底：`jfox prompts drain`（spool→库）
   - 历史回填：`jfox prompts backfill --dry-run` 预览（源：旧 session_fragments 的 UserPromptSubmit）
   - 配置：`jfox prompts config`
5. **与 jfox-promote 的分工**：日常增量（几条到几十条）用本 skill 端到端走完；**pening 积压 >50 或存量清理时切 jfox-promote 三模式**（客观去重 / 簇级 triage / 单条 A/B/C）。judge 产出的 candidate 带 `source_prompts` 溯源，与存量 candidate 通用同一过审工具；judge 不做自动 dedup/merge。

**写作约束**：skill 全文 markdownlint 合规（CI 门禁）；命令与输出格式以 `docs/cli-descriptions.yaml` 和 README 为准，不编造。

## 4. 改动清单（文件级）

| 文件 | 动作 | 内容 |
|------|------|------|
| `skills-recommend/pi/jfox-overview/SKILL.md` | 修改 | 三处退役引用清理（路由表 L44 / 一句话职责 L63 / 复合工作流 §2 L77）；路由表与一句话职责各新增 jfox-judge 行 |
| `skills-recommend/pi/jfox-judge/SKILL.md` | 新建 | §3 骨架全文 |

不改动：`packages/*`（inventory 不涉及）、`docs/cli-descriptions.yaml`（无命令变更）、jfox-promote（D5）。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | overview 无退役引用 | 自动化验证（static） | `grep -n "gem-synth\|碎片采集\|后台合成" skills-recommend/pi/jfox-overview/SKILL.md` | 无匹配（存量 candidate 历史说明除外，本 spec 下不应出现） |
| A2 | jfox-judge 存在且 frontmatter 合规 | 自动化验证（static） | 文件存在；frontmatter 含 name/description/Triggers 关键词 | name=jfox-judge；触发词含「判断 prompt」「prompts judge」「prompt 积压」 |
| A3 | jfox-judge 覆盖骨架四要素 | 自动化验证（static） | grep 关键内容：端到端流程（status/judge/prompts promote/unresolved/ignore/retry）、安全注意（--allow-remote/--force --reason/手动触发）、运维（drain/backfill）、promote 分工（source_prompts/三模式/积压 >50） | 四要素各有对应段落 |
| A4 | markdownlint 通过 | 自动化验证（build） | `npx --yes markdownlint-cli2` | 0 issues（含新增/修改文件） |
| A5 | CI 门禁通过 | 自动化验证（build） | GitHub Actions lint job（markdownlint + generated-docs drift gate） | 全绿（本 PR 不动生成文档源，drift 天然 CLEAN） |
| U1 | skill 实际可路由 | 用户实测 | 将 jfox-judge 装入实际 skill 目录后在 pi 会话说「判断 prompt」，观察路由与流程可执行性 | 路由到 jfox-judge；status→judge→处置命令链可跑通 |

**可测性拆分说明**：本 issue 为纯文档/skill PR，无代码逻辑，自动化验证均为 static/build 级（grep 结构断言 + lint + CI），无 unit/integration 拆分需求；U1 为安装后行为验证，须在真实 pi 环境执行，PR 合并后进行（不阻塞合并，结果回评 issue）。

## 6. 风险与边界

- **skill 数量 15→16**：overview 路由表按意图组织，新增一行不增加路由歧义（judge 管「采集→判断→晋升」的日常动线，promote 管「存量/大积压过审」，触发词与定位均无重叠）。
- **命令面时效**：skill 引用的命令以 1.14.0 为基线；后续 prompts 命令演进需同步 skill（与既有 promote 同等维护义务）。
- **非目标**：cc/kimi 镜像（follow-up issue）；prompts 代码改动；`jfox-overview` 其他章节重写。

## 7. 流程备注

- 实现在 worktree `issue-513-skill-sync-399-overview-jfox-judge`（≤64 字符，无前缀无 `/`）。
- spec 批准后进 worktree，plan + 实现 + 本地 CR + PR（Zima CR）。
