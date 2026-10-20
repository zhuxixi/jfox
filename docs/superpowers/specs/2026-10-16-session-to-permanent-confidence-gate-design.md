# spec: jfox-session-to-permanent 高置信度分级闸门（issue #575）

Drafted: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-16T08:42:00+08:00
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-16T09:05:00+08:00 —— spec-cross-review 第 1 轮：4 真缺口 + 4 细化全部「接受并改」（R1-G1..G4、R1-D1..D4），详见 research/spec-review-round-1.md 修订摘要
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-16T09:20:00+08:00 —— 第 2 轮收敛（0 真缺口 / 5 核对通过）；3 条细化全部「接受并改」（R2-D1 A4 grep 短模式、R2-D2 D3 补验收映射、R2-D3 S2② 空结果分支），详见 research/spec-review-round-2.md 修订摘要

## 0. 背景与目标

把 Step 4 的「一刀切人工确认」改成「五级机械信号闸门 + 三级分流」：高确信度笔记自动落库（不阻塞、可审计、可撤销），其余走人工确认。MVP 只改三平台 SKILL.md，零 CLI 改动。

设计红线（来自调研 R2/R3）：① 不信自评置信度；② permanent 落库前必有检查点——本设计用「机械闸门 + 事后审计 + 可 veto」替代「逐条人工确认」，不是取消检查点；③ fail-closed（任何信号缺失/异常 → 降人工）。

## 1. 术语

- **确信度（confidence tier）**：由机械信号推导的三档判定（高/中/低）。与 LLM 自评 confidence 无关；自评 confidence 只作报告字段，不参与闸门判定（尊重 jfox-promote §6 教训与 #249 spec D14）。术语与 #444 搜索侧「置信度分层」对齐。

## 2. 数据流（新流程）

```
Step 1 提取 → Step 2 去重（新增：补查 candidate）
  → Step 3 起草（新增：每条草稿强制「依据锚点」）
  → Step 3.5 Gate（S1–S5 评估 + 分档）
      ├─ 高确信 → Step 5 落库（落库前重查 + #383 兜底）+ tag + 审计清单
      └─ 中/低 → Step 4 question 人工确认（现状不变）→ Step 5 落库
```

## 3. 闸门信号（Gate，Step 3.5）

每条草稿逐一评估五个信号；**全部通过 = 高确信**。任一失败按表中规则降级。

| 信号 | 判定标准 | 失败时 |
|---|---|---|
| S1 证据锚点 | 每条核心事实有出处：文件路径类事实须用 `test -e` 实测存在；命令类须本会话实际执行过；issue/PR 号须真实可查；用户原话须会话中有 | 降人工档 |
| S2 去重余量 | ① `jfox search --type permanent` 无「已覆盖」命中（Step 2 原流程）；② **追加** `jfox search "<草稿一句话摘要>" --mode semantic --json` 读最高分（cosine 量纲，`vector_store.py:221` score=1-distance）：<0.5 通过；0.5–0.65 灰色区降人工；≥0.65 降人工并按「可补充/已覆盖」走原流程（阈值为初始值，dogfood 中校准）；**空结果或结果无 score 字段 = 信号缺失 → 降人工**（健康通道下非空库不会返回 0 条，空即异常，不得当作「无重复」直接通过）；③ 补查 `jfox search --type candidate` 无同主题 pending；④ 落库前重跑一次 search（#528 提案 1） | 灰色区/异常降人工 |
| S3 类型白名单 | 仅放行：现状快照（文件/脚本/配置位置）、工具/命令用法（factual/procedural 的可验证子集）、已发生且可验证的事实。排除：ADR/决策、偏好、推测、待办、概念解释（初版保守）、冲突信息 | 降人工档 |
| S4 只新增不覆盖 | 仅 `jfox add` 新笔记可自动；`jfox edit` 追加存量一律人工 | edit 类永远人工 |
| S5 fail-closed | 任一通道退化/异常/拿不准 → 降人工。**检测动作（gate 前置）**：跑 `jfox daemon status` 确认 embedding daemon 在跑；并抽查 `jfox search --json` 返回条目的 `search_mode` 是否全为 `keyword`（健康态为 `hybrid`）。注意：`--json` 的 `warnings` 字段仅在组件缺失（#519）时写入，generic 异常会静默退化为 BM25-only——「search 成功且无 warnings」不能当作通道健康证据 | 降人工档 |

> **suggest-links 不作去重余量量具**：其输出 score 是关键词比率合成分（0.3–0.6），不是语义相似度；语义分支因 RRF 融合分封顶（≈0.033）恒不过 0.6 过滤（`note.py:1102/1107`、`search_engine.py:339-340`），属既有缺陷，另案跟踪。suggest-links 维持 Step 2 既有补链用途不变。
>
> **S3 排除 ≠ 不沉淀**：ADR/决策、偏好、概念解释等照常提炼、照常走 Step 4 人工确认，只是不进自动档（衔接 Step 1「值得提炼」清单，后者不变）。

兜底：`jfox add` 的 #383 闸门命中 duplicate → **不 `--force`**，该条降级人工，其余候选不受影响。

## 4. 三级分流与处置

| 档位 | 条件 | 处置 |
|---|---|---|
| 高确信 | S1–S5 全过 | 直接 `jfox add --type permanent --tag auto-distilled`；正文带「## 依据」锚点段；不弹 question；跳过 MOC 归属问询，输出含 `moc update` 兜底提示（D7） |
| 中确信 | S1/S3/S4 过，S2 灰色区或证据偏弱 | 默认走 Step 4 人工确认（与现状一致）；不切 candidate（D4） |
| 低/排除 | S3 排除类、S1/S2 失败、S5 触发 | 现行 question 逐条确认，行为不变 |

## 5. 审计与 veto

- 自动写入必带 tag `auto-distilled`（+主题 tag）；`jfox list --tag auto-distilled` 随时回查。
- 会话末输出审计清单：每条一行「标题 | ID | 档位依据摘要（S1 锚点 / S2 分数）」，附 veto 提示（`jfox edit` / `jfox delete`）。
- **熔断（D9）**：用户 veto 或要求修改任一自动放行条 → 本会话剩余候选全部降回人工确认。
- session 账本（审计清单落成 session 笔记）：follow-up，不在 MVP。

## 6. 启用方式与默认（D2）

- **默认关**：现状完全不变。
- MVP 启用方式 = 用户在当前会话明确授权（如「本次高置信度笔记直接写」），SKILL.md 写明授权短语、生效范围（仅当前会话）与熔断条款。
- follow-up（另开 issue，不在本 spec）：`NoteAddConfig.auto_confirm` 全局开关；影子模式校准（记录分歧率，达标后建议开启）。

## 7. 决策表

| ID | 决策 | 被丢弃的替代方案与理由 |
|---|---|---|
| D1 | 闸门放 Step 3 起草后、Step 4 前 | 起草前：证据锚点在草稿中才完整，提前评估信息不足 |
| D2 | 默认关 + 会话内显式授权 | 默认开：风格级变更（调研 R2 §2），必须显式选择 |
| D3 | 闸门用机械信号，自评 confidence 仅作报告 | 信自评置信度：jfox-promote §6 与 #249 D14 已证伪 |
| D4 | 中档默认人工确认 | 中档进 candidate：default KB candidate 积压 1159 条且 L5 吞吐低（R1 §3 / R2 §3），会加重积压 |
| D5 | 白名单窄（factual/procedural 可验证子集） | 含概念解释/ADR：判断成分高，错了伤知识库 |
| D6 | 审计 = tag + 会话末清单 | session 账本：MVP 超重，follow-up |
| D7 | 自动档跳过 MOC 归属问询，输出 `moc update` 兜底提示 | 自动档仍问 MOC：破坏「不阻塞」初衷；`moc update` 批量兜底已有（`moc/cli.py:515-519`） |
| D8 | 落库前重查保留；#383 命中降级不 force | force 绕过：安全网失效，违背红线② |
| D9 | 熔断：一次 veto → 本会话降回人工 | 全局降级：过重，会话粒度足够 |
| D10 | 术语「确信度」三档 | 复用 confidence：与自评置信度混淆 |
| D11 | 去重余量量具用 `--mode semantic` 的 cosine 分 | 用 suggest-links 分数：其 score 是关键词比率合成分、语义分支恒空（R1-G1 复核发现，代码实证 `note.py:1102/1107/1146-1147`、`search_engine.py:339-340`），量纲错位 |

## 8. 非目标

- 不改 #249 L5「candidate 晋升必须人工确认」；不动 gem_synth/prompts/judge/promote 任何代码与 skill。
- 不做 CLI 新参数（`--confidence`/`--grounded-by`）、不做全局配置项实现、不做影子模式账本——均为 follow-up。
- 不改变 cc/kimi 平台各自既有的确认交互风格细节（各平台按自身习惯适配散文/结构化表述）。
- **不修复 suggest-links 语义分支恒空的既有缺陷**（另开 issue 跟踪，待用户确认后建）；不改 generic 异常静默退化 BM25-only 的既有 CLI 行为（skill 文本只能缓解，见 §3 S5 检测动作）。

## 9. 影响范围

- `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- 三副本内容存在实质差异（diff 行数随口径在百行级浮动，不逐一钉数字）→ 逐平台适配，不盲拷贝；但闸门语义条款（S1–S5、分档、审计、熔断、fail-closed、默认关）必须三平台一致，一致性以 A2 的 grep 核对为准。
- 不改 CLI、不改测试、不改 README。

## 10. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 三个 SKILL.md 文档质量 | 自动化验证（static） | `npx --yes markdownlint-cli2` | 三个文件 lint 通过 |
| A2 | 闸门语义条款三平台一致 | 自动化验证（static） | 一次性校验命令：逐条 grep 关键条款（S1–S5、`auto-distilled`、熔断、fail-closed、落库前重查、默认关、`moc update` 兜底提示、「自评 confidence 仅作报告、不参与闸门判定」）于三副本 | 全部命中；条款语义一致（平台措辞差异列显式豁免清单） |
| A3 | skill 引用的命令与参数真实存在 | 自动化验证（static） | 对 skill 引用的每条 jfox 命令跑 `--help` 校验（`add --tag`、`list --tag`、`search --type candidate`、`search --mode semantic`、`candidates list --min-confidence`、`moc update`、`daemon status` 等） | 全部存在 |
| A4 | 默认行为不变 | 自动化验证（static） | grep 确认「严禁未经审阅」硬约束仍在（用短模式——目标句含行内代码格式，`jfox add` 带反引号，字面整句匹配会 0 命中），且授权条款写明「默认关、会话内授权才生效」 | 条款存在且语义一致 |
| U1 | 授权模式真实会话 dogfood | 用户实测 | 部署前置见下。授权短语开启后观察：高确信条目自动落库带 `auto-distilled` tag；**无 MOC 归属问询且输出含 `moc update` 兜底提示**；审计清单输出；中/低档仍弹确认 | 行为符合 §3–§5；**首批累计 N≥20 条自动放行后**用户判定准确率 ≥95%（不足 20 条标 pending 继续累计，不在小样本上下结论）；veto 与熔断生效 |
| U2 | 默认关回归 | 用户实测 | 部署前置见下；不开授权跑一次沉淀 | 行为与改动前完全一致（每批 question 确认） |
| U3 | #383 兜底降级 | 用户实测（可构造） | 部署前置见下；构造一条会被 #383 闸门命中的高确信条目（同标题） | 该条被拦并降级人工，未 `--force` |
| U4 | 通道退化降级（S5 失败分支） | 用户实测（可构造） | 部署前置见下；构造退化态：停 daemon 且无本地模型回退（轻量安装无 embed 组件，或本地模型不可用）；授权后跑一次沉淀 | 自动档判定全部降人工、零自动写入。**若环境无法构造退化态，如实标注「S5 仅静态验证（A2 grep）」，记入 §11 保证边界** |

**用户实测部署前置（U1–U4 通用）**：试点平台 = pi。把 PR 分支的 `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` 同步到实际加载路径（`~/.pi/agent/skills/jfox-session-to-permanent/`，加载路径见 `skills-recommend/README.md:81-104`；或 `pi install` 指向改动副本）；**验收前先确认会话实际加载了新文本**（如让 agent 复述新增的 S1–S5 条款），否则实测跑在旧副本上：U1 假失败、U2 假绿。cc/kimi 副本在合入并各自发版（jfox-release-cc-plugin / jfox-release-kimi-plugin）后另行回归，不阻塞 MVP 验收。

**可测性拆分设计**：本 issue 的功能点是文档条款，可测性拆分体现为「条款原子化」——S1–S5 各自独立成节、判定标准写成「命令 + 阈值」的可机检句式，使 A2/A3 能逐条 grep/--help 核验；条款与验收 ID 双向可追溯：S1→U1；S2→A2/A3/U1/U3；S3/S4→A2/U1；S5→A2/U4；审计/熔断→A2/U1；D7→U1/A2/A3；D3→A2。A2/A3 的校验命令在 plan 中落成一次性命令并记录输出；如需固化为脚本（`scripts/`），在 plan 阶段单列 task，不阻塞 MVP。

## 11. 风险与降级

| 风险 | 对策 |
|---|---|
| agent 伪造/夸大锚点 | S1 要求机器可核验（`test -e` 实测）；审计清单可 veto；熔断 D9 |
| 并行会话竞态（#528） | S2④ 落库前重查；#383 闸门兜底 |
| daemon 不在 → embedding 通道退化 | S5 fail-closed + 检测动作（`daemon status` / `search_mode` 抽查）；generic 异常静默退化不可依赖 warnings（如实写入条款） |
| 自动放行错误事实 | 白名单窄（D5）+ tag 审计 + veto + 熔断 |
| 风格级变更争议（全项目散文确认传统） | D2 默认关，显式授权才生效；§7 决策表记录 |
| suggest-links 语义分支恒空（既有缺陷） | 本 issue 不修复；S2② 已改用 `--mode semantic` 独立量具（D11）；建议另开 issue 跟踪（待用户确认后建） |
| U4 退化态无法构造的环境 | 如实降级为「S5 仅静态验证（A2 grep）」并明示，不暗示已测过 |

## 12. 关联

- 调研：`research/01-现状机制盘点.md`、`research/02-kb设计史与外部先例.md`、`research/03-git与issue演化.md`
- 复核：`research/spec-review-round-1.md`、`research/spec-cross-review-state.md`
- issue：#249 / #528 / #383 / #502 / #451 / #376 / #444 / #317 / #366 / #367 / #399 / #513
- KB 笔记：gem_synth 证伪（202608191221200235）、确认风格史（202608061804503041）、去重盲区（202608270835202888）、promote/judge 分工 ADR（202609140903354519）、自动化调研（202606122145558487）
