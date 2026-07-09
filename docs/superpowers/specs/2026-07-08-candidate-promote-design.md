# L5 候选晋升（破损→完整）设计方案

> 对应 #249 五层 Loop Engineering 的最后一层（Layer 5 晋升层）。
> L1–L4（采集 → 存储 → 合成 → 产出 candidate）已跑通；本设计补上 candidate → permanent 的人工晋升闭环，跑通 #249 最后一项验收「碎片 → 候选 → 人工确认 → permanent」。
> 与 #295（status 滚动进度呈现）相互独立，不在本 spec 范围。

## 0. 目标与定位

把 gem-synth 产出的 candidate（`flawed` / `pending`）经人工审阅，晋升为 `permanent`，并织入知识图谱（wiki links）。

### 设计约束（继承 #249 核心观点）
- **晋升必须人工确认**，不存在自动晋升
- **碎片/candidate 永远不硬删**：reject 走归档（软删除，可恢复）

### 非目标（YAGNI）
- 不做 `merge` 合并去重命令（重叠笔记由 skill 在改写时提示，不自动合并）
- 不做按 `--min-confidence` 阈值过滤（过审是一条条顺序消费，不挑）
- 不做自动判档执行（agent 推荐 + 用户可 override，见 §3）

## 1. 整体形态

**`promote` skill（编排过审对话）+ `candidates` CLI（最小原子操作）+ 复用现有能力**。

不走 #249 草案的 `review / confirm / reject / merge` 命令式逐条操作——用户日常是队列式、对话式过审，CLI 退居底层原子操作。

## 2. CLI 原子命令（`candidates` 子命令组，新增 2 个）

| 命令 | 作用 | 实现 |
|------|------|------|
| `jfox candidates promote <id>` | candidate → permanent：改 type、保留溯源清状态、移文件、更新索引、回填 backlinks | **新建**（`note.py` 无改 type 能力）|
| `jfox candidates reject <id> [--reason <txt>]` | 归档丢弃，可选记原因 | 直接置 archived+status，单次 `update_note`（不调 `archive_note`）|

砍掉 #249 草案的 `review`（过审在 skill 里）、`merge`（YAGNI）。保留既有 `list` / `show`。

### 2.1 promote 的字段处理（晋升那一刻的数据模型）
- `type`: `candidate` → `permanent`
- **保留**：`source_fragments`（碎片溯源）、`grounded_by`（参考笔记）—— 满足 #249「合成产物必须可追溯到来源碎片」
- **清除**：`status`、`gem_level`、`confidence` —— 已人工确认，生命周期标记无意义
- `links`：由 `grounded_by` + skill 补的链合并填充
- 文件移动：`notes/candidate/` → `notes/permanent/`，更新 `note_index`

### 2.2 reject
直接置 `archived=True` + `status=rejected`（+ 可选 `reject_reason`），单次 `update_note` 落盘——**不调 `archive_note`**（避免二次写盘；CR round-1 调整，原 spec 写复用 archive_note）。要求 `type==CANDIDATE`（守卫）。软删除，search 默认排除，可 `jfox unarchive` 恢复（恢复时清 `reject_reason` + candidate 复位 `status=pending`）。`--reason` 写入 frontmatter `reject_reason` 字段（轻量，供复盘）。

## 3. `promote` skill（过审编排，核心）

过审一条 candidate 的流程 = **分流 triage + 引导式澄清**：

```
取下一条 pending candidate（队列，见 §3.1）
        │
        ▼
  ① agent 准确度评估
   （对照 grounded_by + suggest-links 拉到的现有 permanent，
    查 一致性 / 冲突 / 缺失）→ 判档 + 给依据
        │
        ├── A. 准确（无实质错误）──────► ② agent 微调：清 candidate 元段落、
        │                                修/补 wiki link、title 润色
        │                                → 展示改后版 → 用户确认 → promote
        │
        ├── B. 大部分对、局部有问题 ──► ② 澄清：agent 列出问题点，引导用户
        │                                给出正确信息（可多轮）
        │                                → 用户答 → agent 改 → 确认 → promote
        │
        └── C. 整体不可信 ──────────► agent 给依据（哪条 permanent 冲突）
                                        → reject 归档（记原因）
```

### 3.1 队列顺序
`confidence 降序 + created 升序`（优先过高置信度，同分先来先过）。

### 3.2 边界原则（微调 vs 澄清 vs reject）
- **能确信改对的**（格式、candidate 专属段落如「待人工审阅 / 置信度说明」、明显链接缺失）→ **微调**，agent 直接改，不问用户
- **需要用户判断的**（事实对错、语义二选一、关键信息缺失）→ **澄清**，引导式问
- **整体不可信的**（与现有 permanent 冲突、grounding 崩了）→ **reject**

### 3.3 准确度评估依据（决定判档可靠度）
- 读 `grounded_by` 指向的 permanent，查 candidate 陈述是否一致
- `suggest-links` 拉相关 permanent，查冲突 / 支撑
- 冲突 → B 或 C；仅缺链 / 格式 → A

### 3.4 wiki link 处理（验证 + 主动补链）
- **验证**：candidate 已有的 `[[参考笔记]]` 是否链到正确目标（目标存在、语义真匹配），错链改对
- **补链**：用 `suggest-links` 对正文语义匹配（复用 organize skill 的 ≥0.6 阈值），把漏掉的相关 permanent 补成 `[[link]]`

### 3.5 细节默认
- **分流决策权**：agent 判档 + 给依据，用户可 override
- **澄清粒度**：一次列出所有问题点，用户批量回答（不逐个问）
- **微调范围**：只动晋升相关（清元段落、补链、title），**不动知识内容**（内容改动走澄清）

## 4. 数据流

```
candidate (type=candidate, status=pending, gem_level=flawed)
  → promote skill: 评估 → 分流 → 微调/澄清 → 用户确认
     ├─ promote: type→permanent, 保留 source_fragments/grounded_by,
     │           清 status/gem_level/confidence, 移文件, 回填 backlinks
     └─ reject:  archived+status=rejected（+reject_reason）, 单次 update_note（不调 archive_note）, 可 unarchive 恢复
```

## 5. 模块拆分（初拟，plan 阶段细化）
- `jfox/note.py`：新增 `convert_note_type(id, new_type, field_policy)` —— promote 的核心原子（改 type + 移文件 + 清/留字段）
- `jfox/note_index.py`：type 变更后更新 文件名↔ID 映射
- `jfox/cli.py`：`candidates promote` / `candidates reject` 两个子命令 + `_impl` helper（遵循项目 `_xxx_impl` 惯例）
- `packages/cc-plugin/skills/promote/`：新 skill（过审编排）
- 复用：`jfox suggest-links`（补链）、`jfox show`（展示 candidate）；reject 直接设字段（不调 archive_note）

## 6. 错误处理
- promote 时 wiki link 目标不存在 → 警告，不阻塞（broken link 留待后续 organize 修）；是否升级为阻塞由 plan 阶段定
- reject 的 candidate 事后发现误判 → `jfox unarchive` 恢复，重新过审
- promote 改写后正文丢失关键信息 → skill 自检（对照原 candidate 的核心陈述）

## 7. 测试策略
- **promote 原子操作**（`note.py`）：字段处理（保留溯源清状态）、文件移动、`note_index` 更新、backlinks 回填 —— 纯逻辑单测，不涉及 embedding
- **reject**：归档 + `reject_reason` 写入 + 可 unarchive
- **skill 端到端**：mock 三档 candidate（准 / 半准 / 不准），验证分流 + 改写 + 晋升 / 归档

## 8. 待定 / 风险
- **准确度评估的可靠度**：判档依赖 agent 对照 permanent 做一致性检查，可能误判（如 `grounded_by` 本身不全）。缓解：判档始终给依据 + 用户可 override；C 档 reject 可恢复。
- **改 type 原子操作的原子性**：移文件 + 改 frontmatter + 更新索引需事务性，失败要回滚（plan 阶段参考 `2026-05-06-atomic-write-design.md`）。
- **broken link 策略**：promote 时遇到目标不存在的 wiki link，阻塞 vs 警告，plan 阶段定。

## 9. 与现有设计的关系
- 上游：依赖 L3（gem-synth）产出的 candidate（`2026-06-21-gem-synthesis-design.md` §4.2 定义的 frontmatter）
- 复用：归档（#259 / `2026-06-18-archive-soft-delete-design.md`）、suggest-links（organize skill）、backlinks 回填（commit e6157f3）
- 独立：#295（status 滚动进度）与本 spec 无依赖，各自推进
