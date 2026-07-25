# promote skill 三模式过审重写设计（#319）


## 背景
- promote skill 现状（cc + kimi 两版）：逐条 A/B/C triage，按 confidence 降序取下一条
- 一轮真实过审（pending 700+→432）验证痛点：confidence≠质量/冗余、逐条在 700+ 积压前 scale 不了、主要矛盾是「冗余」(被现有 permanent 覆盖)、机械清理每批重写占大半时间且每批补脚本 bug
- 调研（origin/main `e97e749`）：promote 不动正文/不剥 scaffolding（docstring「保留溯源」）、reject=软归档且增量毫秒级、dedup 基础设施完备（`gem-synth dedup-backfill` 只灌表不报告重复对）但缺存量查重扫描入口、cleaning marker 只 3 个固定串不含变体（现存缺陷）

## 目标
把 promote skill（cc + kimi 两版）从「逐条 A/B/C」重写为「三模式过审 + 冗余维度 + 固化机械清理」，让大积压可高效处理。

## 非目标（YAGNI / follow-up，本 PR 不做）
- 不改 Python 代码（promote_note 不加 --strip-scaffolding）
- 不新增 `candidates dedup-scan` 命令
- 不做 208 双 H1 backfill
- 不接跨版本 dedup 口径
- 不修现存 bug：promote 回填 backlinks 不同步 chroma（注：unarchive 复位 status 已核实非 bug，`note.py unarchive_note` 对 candidate 已复位 `status=pending` + 清 `reject_reason`）
- 以上各自开 follow-up issue，本 PR 评论登记

## 设计

### 模式选择决策树
pending 积压量决定入口：
- **大积压（>50）**：模式1（砍精确/高重复）→ 模式2（剩余簇）→ 模式3（高价值/模糊单条）
- **小积压（≤50）**：直接模式2 / 模式3

### 模式1：客观去重扫描（大积压第一步）
三档：
- **L1 content_hash 精确**（cleaning 后正文逐字节一致）：直接清，每组留 1，不用读
- **L2 cosine ≥ 0.95**：报簇（标题+分数+片段）给用户确认后清
- **L3 cosine 0.88–0.95**：很可能，读一眼确认；<0.88 不标记

**落地（纯文档 PR）**：skill 内嵌可跑临时脚本——
- 直读 pending candidate：glob `notes/candidate/*.md` + 解析 frontmatter 取 `status=pending`（绕过 `candidates list` 的分页 50 + 无 content 字段两个坑）
- 读正文 + cleaning（剥元段落 marker，regex 收紧覆盖变体）
- L1：sha1 content_hash 精确分组
- L2/L3：调 jfox embedding daemon 算 embedding（`from jfox.embedding_backend import get_backend`），numpy cosine
- 输出簇报告，dry-run 默认，`--apply` 批量 reject（keep-best）
- **标注**：`candidates dedup-scan` 命令（follow-up issue，待建后补编号）落地后替换本脚本
- daemon 不可用 → 降级只做 L1（content_hash）

### 模式2：簇级 triage（非精确重复的簇）
1. 每簇先查「是否已被现有 permanent 覆盖」（`jfox search` / `suggest-links`）= 冗余维度
2. **覆盖了** → keep-best（簇中 grounding 最实 / 信息最完整者）+ reject 其余
3. **未覆盖** → promote-merge 成 1 条（簇内 candidate 改写合并为单条 permanent）

### 模式3：单条深度 triage（现有 A/B/C，降为次要）
仅用于高价值单条或 L3 模糊条。保留现有：
- **A 准确**：微调（清元段落+补链+title）→ 确认 → promote
- **B 局部问题**：列待澄清问题批量回答 → 改写 → promote
- **C 不可信**：给依据 → reject

### 「冗余」verdict（跨模式维度，与 A/B/C 并列，非独立第4模式）
模式2 / 模式3 过审时，凡判定「已被现有 permanent 覆盖」→ `verdict=冗余`，处置 fold（折进现有 permanent）/ merge / reject。
**纪律**：promote 前强制查「是否已被现有 permanent 覆盖」，避免晋升冗余笔记。

### 机械清理标准流程（固化，别每批重写）
晋升前对 candidate 正文做标准 clean（skill 内可复制片段）：
1. **剥 frontmatter 字段**：promote 自动清 `status`/`gem_level`/`confidence`/`knowledge_type`/`reject_reason`（保留 `source_fragments`/`grounded_by` 溯源）
2. **删元段落**：regex `r"\n## (来源|参考的永久笔记|置信度.*|可信度.*)\n"` 截断（覆盖 `## 置信度说明`/`## 可信度说明` 变体，补 dedup cleaning 现存缺陷）
3. **去双/多 H1**：剥首个 leading H1（title 重复，复用 `_strip_leading_h1` 思路）；2+H1（剥首个后仍有行首 H1，LLM 用 H1 当分节）→ 降级 H2 或人审
4. **修 exact-link**：wiki link 精确标题匹配（关联 #275）；`suggest-links` 阈值放宽 0.4–0.5 + 手动按概念补链

### 已知坑（写进 skill，条条实踩）
- wiki link 要精确标题（`[[Boktionary]]`/`[[没爆就别修]]` 短链悬空实踩）；promote 未解析链 warning+跳过（spec §6）
- `suggest-links` 常关键词误命中/漏语义邻居，需手动按概念补链，不能只信它
- confidence 是合成器自评、≠质量/冗余，别按它排序或决定能否直接升
- reject=archive（文件保留、`unarchive` 可恢复）
- 批量 reject：调研显示实际增量（非全量重建），但每条触发 chroma add_note 含 embedding，大批量累积耗时——>40 条建议后台跑；`while read` 注意尾换行

### 标准输出格式
`verdict + 证据 + wiki-link 报告 + 处置(promote/reject/merge/fold) + 确认`

### 两版差异
- **cc**（`packages/cc-plugin/skills/promote/SKILL.md`）：聚焦过审流程，精简
- **kimi**（`packages/kimi-plugin/skills/jfox-promote/SKILL.md`）：额外保留 L3 合成监控 / fragments / 命令参考 / 错误处理表

## Follow-up 登记（本 PR 不做，issue 评论挂）
- 新 issue: `candidates dedup-scan` 命令（模式1 治本，替换临时脚本）
- 新 issue: promote `--strip-scaffolding`（机械清理治本，扩 promote_note）
- 归 #320: 208 存量双 H1 backfill
- 新 issue: 跨版本 dedup 口径（#320 issue-4）
- 新 issue: promote 回填 backlinks 不同步 chroma（现存 bug）
- ~~unarchive 不复位 status~~（已核实非 bug，`unarchive_note` 已复位 status=pending，不单开 issue）

## 测试 / 验证策略
- skill 是 markdown，无单测
- 验证：重写后两版结构一致；命令引用与 origin/main 实际一致；模式1 临时脚本可跑（dry-run）；cleaning regex 覆盖 4 类 marker（来源 / 参考的永久笔记 / 置信度.* / 可信度.*，含 `## 置信度说明` / `## 可信度说明` 变体）
- 可选人工验证：取一批真实 candidate 走三模式，确认流程顺畅

## 风险
- 模式1 临时脚本依赖 embedding daemon（不可用降级 L1）
- cleaning regex 过宽误删正文（须精确匹配 marker 开头）
- cc/kimi 两版同步维护成本（结构一致可降低）
