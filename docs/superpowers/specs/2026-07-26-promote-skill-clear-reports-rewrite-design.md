# promote SKILL.md 按 clear-reports 重写散文层（#341）

**日期**：2026-07-26
**Issue**：#341（父 #340 P0）
**PR 分支**：`worktree-issue-341-promote-skill-clear-reports-rewrite`
**关联**：#319（promote 三模式重写，本 skill 当前形态的设计源）、#340（clear-reports 评估 meta issue）

## 1. 问题

promote（cc）+ jfox-promote（kimi）两个 SKILL.md 是 #340 评估的 P0 重灾。问题集中在散文解释层，典型表现：

- 通篇电报体：「直接清，每组留 1」「2+H1 降级 H2」「keep-best」「reject 其余」——丢主语丢动词。
- 开篇甩 #249/#319 内部 issue 号 + L3/L5/A-B-C 黑话，无心智模型段，新读者不依赖 issue 号读不懂。
- 术语裸露：candidate / grounded_by / cosine / confidence 首次出现不解释。
- L3 命名冲突：合成层 L3 与去重档 L3 撞名。
- 表格（标准输出格式、错误处理）缺结论引导句。

**根因（调研发现）**：#319 spec 本身就是电报体写的，skill 照 spec 抄——电报体从设计阶段传下来。本 PR 新 spec 用 clear-reports 写作示范，建立 spec↔skill 同语言纪律。

## 2. 目标 / 非目标

**目标**
- 按 clear-reports 七规则重写 promote / jfox-promote 的**散文解释层**。
- cc/kimi 两版过审核心（§0–§7 + 关键约束）同步、风格一致；kimi 另保留「监控 L3 合成 / 命令参考 / 错误处理 / 使用建议」等独有章节（见 §7 表）。cc promote 自身无跨 skill 引用。
- 本 spec 文档本身按 clear-reports 写（示范 + 防下次飘）。

**非目标**
- 不改命令块；Python 脚本（dedup_scan、clean_for_promote）的逻辑 / 控制流 / 变量名原样保留，仅 print 输出标签和代码注释随去重档改名同步（避免散文叫「高度相似」、脚本输出叫「L2」的新不一致）。
- 不改触发词 / frontmatter / 错误处理表「场景-处理」骨架。
- 不改工作流步骤顺序与判定逻辑（只改表达，不改行为）。
- 不动 skills-recommend（无 promote 副本，调研已确认）。
- 不改 #319 老 spec（历史设计记录，本 PR 新 spec 自然用 clear-reports 写作示范）。
- 不落「SKILL.md 写作约定」总文档（属 #340 系统性缺口，另开 issue；本 PR 仅 promote）。

## 3. 心智模型段（精简版，✅ 已确认）

promote 开篇补一段，让新读者不依赖 #249/#319 也能读懂。3 条：

1. **candidate 是什么、从哪来**：gem-synth 后台合成出的「破损宝石」候选知识（pending 状态），处知识闭环（采集→合成→过审）链路上。
2. **过审做什么**：晋升为永久笔记（permanent）或拒绝归档（reject = archive 软删除）。
3. **三模式怎么选 + status 坑**：大积压模式1→2→3，小积压直接 2/3；点明 `candidate.status`（过审）≠ `gem-synth status`（合成进度）。

**定稿文本**：

> 本 skill 过审 gem-synth 合成的 candidate——一种「破损级」候选知识笔记，把它晋升为永久笔记（permanent），或拒绝归档（reject，软删除可恢复）。candidate 由后台合成器围绕锚点生成，处于 pending 状态；过审是知识闭环（采集→合成→过审）的最后一环。
>
> 积压量大时先用客观去重砍重复（模式1），再簇级 triage（模式2），最后精修高价值单条（模式3）；小积压直接模式2/3。注意：candidate 的 pending（过审状态）和 gem-synth status（合成进度）是两回事。

## 4. 电报体改写范式（前后对照）

> **clear-reports 七规则**（源自 `~/.claude/skills/clear-reports`，即《写作的逻辑》段落写作法）：①总论先行 + 心智模型 ②每段一主题 ③段首概要句 ④补充信息 what/why/how ⑤衔接前后段 ⑥统一并列表达 ⑦由已知→未知 + 句子完整（电报体违反此条）。下文所有改写均以这七条为标尺。

| 现状（电报） | 改后（完整句 + 术语解释） |
|---|---|
| `L1 content_hash 精确：直接清，每组留 1，不用读` | 第一档是精确去重：把清理后的正文逐字节比对（content_hash），完全相同的归为一组，每组只保留一条、其余拒绝（reject，即软归档）。这一档无需逐条阅读。 |
| `档 A 准确：读 candidate + grounded_by permanent → 微调 → 展示 → 确认 → promote` | 拆成有序步骤的完整陈述：「先读 candidate 及它依据的永久笔记（grounded_by），再微调正文……」 |
| `2+H1 降级 H2 或人审` | 如果剥掉首个标题后正文里仍有独立标题（说明合成时把标题当分节用了），把这些标题降级为二级，或交给人工确认。 |

**改写纪律**：保留信息密度，但每句有主语动词；术语首次出现带半句解释；`→` 流水改「先…再…最后…」或有序列表。精简 = 删不重要信息，不是压成电报。

## 5. 术语解释清单（首次出现补半句）

candidate、pending/flawed、permanent、grounded_by（合成依据的永久笔记）、grounding、dedup、content_hash、cosine（余弦相似度）、keep-best、fold/merge、confidence、leading H1、reject=archive。

## 6. L3 命名冲突（✅ 已确认：去重档改名）

模式1 三档从 L1/L2/L3 改名为 **精确 / 高度相似 / 中度相似**，彻底避开与合成层 L3 撞名（clear-reports 规则 7：消除歧义优于注释）。改名后正文里「L3」只指合成层。

## 7. cc/kimi 两版同步

| 改动点 | cc | kimi |
|---|---|---|
| 开篇心智模型段 | 补 | 补 |
| §0–§7 散文层（模式1/2/3、机械清理、已知坑、输出格式、约束） | 同步改 | 同步改 |
| 监控 L3 合成 / fragments 章 | 无 | kimi 独有，按同方法论润色 |
| 命令参考 / 错误处理表 / 使用建议 | 无 | kimi 独有，表格补结论句 |
| 引用语法 | 无跨 skill 引用（cc promote 不指向 manage） | `/skill:jfox-promote`、`/skill:jfox-manage` |

## 8. 验证（grep 断言，skill 无单测）

- 电报体残留核查：`grep -nE "直接清|留 1|2\+H1|降级 H2|keep-best|reject 其余" packages/{cc,kimi}-plugin/skills/{promote,jfox-promote}/SKILL.md` → 无命中（或仅保留并已配解释的）。
- L3 冲突核查：去重档不再用裸「L3」。
- 两版结构一致：心智模型段、三模式、机械清理四步、输出格式均在。
- 人工通读 cc 版确认不依赖 #249/#319 可读懂。

## 9. 风险

- 改写误改命令/脚本 → 用 grep 守住「只动散文层」。
- cc/kimi 两版改后不同步 → 同 PR 改、结构对照。
- 信息密度下降（散文化变啰嗦）→ clear-reports 纪律：精简是删不重要信息，不是压成电报；要点收成三条。

## 设计确认（2026-07-26）

1. **心智模型段颗粒度**：精简版（3 条）。定稿文本见 §3。
2. **L3 命名冲突**：去重档改名「精确 / 高度相似 / 中度相似」。
3. **老 spec**：只改 skill；#319 老 spec 不动，本 PR 新 spec 用 clear-reports 写作示范。
