# L3 宝石合成（碎裂→破损）设计方案

- **关联 Issue**: #249（父，Loop Engineering 五层架构）的 Layer 3
- **前置**: #261（Layer 1/2 采集+存储，已合并 1.1.1，`fragments.db` 实时采集中）
- **日期**: 2026-06-21
- **状态**: 设计待用户 review

## 0. 目标与定位

把采集到的 **碎裂级**碎片（`session_fragments` 表），围绕**高价值锚点**合成为 **破损级**知识宝石（`candidate` 笔记）。合成需用 JFox 永久笔记做事实基准，降低 LLM 幻觉。

**与 auto_summary 的区别（重要）**：
- `auto_summary` = 整个 session 1 次总结，breadth 优先，粗，丢细节
- L3 锚点合成 = 围绕高价值时刻做多次微合成，depth 优先，保住每个重要的注入/澄清瞬间

两者不冲突，目的与粒度都不同。

**不做跨 session 聚合**（本阶段）。合成单元是 session 内的锚点 + 其前后上下文。

## 1. 三个输入（合成公式）

| 输入 | 角色 | 来源 |
|------|------|------|
| **fragments** | 索引 —— 定位锚点在哪 | `~/.zettelkasten/fragments.db` |
| **transcript** | 原料 —— 锚点周围的完整对话（含 CC 推理过程） | CC 的 `~/.claude/projects/<proj>/<session_id>.jsonl` |
| **永久笔记** | 基准 —— 已成事实，防幻觉、做对齐 | JFox KB 的 `permanent` 笔记 |

> fragments ⊂ transcript：fragments 是 transcript 的"高价值时刻子集 + 加工版（打标签/可查）"。fragments 当目录定位锚点，transcript 当正文取上下文。

合成：**锚点的 transcript 上下文 + 相关永久笔记 top-K → LLM → 一颗破损宝石（带置信度 + 引用了哪些永久笔记）**

## 2. 锚点定义

session 内的"观点注入 / 澄清"高价值时刻，三种：
- `UserPromptSubmit` 且 fragment_type ∈ {`correction`, `decision`}（用户纠正/决策）
- `PostToolUse` 且 tool_name = `AskUserQuestion`（CC 主动提问）

> 不对每条 user_input 都合成（"ok 继续"无价值）。锚点过滤是**知识密度入口控制**，不是质量丢弃。volume 在这一层控制。

## 3. 合成管线（数据流）

```
① 找锚点    fragments.db 查 synthesis_log 里未处理的高信号锚点
    ↓
② 取上下文  拿锚点 timestamp → 读 transcript.jsonl 里"这一轮"的完整对话
    ↓           （上一条 user 输入到下一条 user 输入之间，含 CC 思考/工具结果）
③ 取基准    用锚点 content 做 hybrid 检索 → permanent 笔记 top-5 做防幻觉佐证
    ↓
④ LLM 合成 [②上下文 + ③永久笔记] → 结构化知识 + 置信度 + 引用的永久笔记
    ↓
⑤ 落库     写 candidate 笔记（type: candidate, gem_level: flawed）；synthesis_log 记录该锚点已处理
```

## 4. 新增 `candidate` 笔记类型 + GemLevel 枚举

### 4.1 GemLevel（5 级，本阶段建模，仅产出 flawed）

代码里预先建 5 级枚举（forward-looking，定下晋升阶梯）：

```python
class GemLevel(str, Enum):
    chipped  = "chipped"    # 碎裂 — raw 碎片（在 fragments.db，非笔记）
    flawed   = "flawed"     # 破损 — L3 合成的 candidate（本阶段产出）
    normal   = "normal"     # 完整 — L4/L5 成熟后
    flawless = "flawless"   # 完美
    perfect  = "perfect"    # 无暇 — 晋升 permanent 的候选终态
```

> **L3 只写 `flawed`。** 等级如何递进（破损→完整→…→无暇）与晋升规则（达到 perfect 后是否/如何进 permanent）属于 **L4/L5 范畴**，本阶段不实现，但 enum 先到位。#249 原则：晋升需人工确认，不存在纯自动晋升 —— 自动晋升与否留待 L5 设计定。

### 4.2 candidate 笔记

JFox 现有 4 种 type（fleeting/literature/permanent/session），新增第 5 种 `candidate`。触及：`models.py`（NoteType 枚举）、`note.py`（`notes/candidate/` 存储路径）、`cli.py`（`--type` 过滤）、indexer（索引 candidate）。

frontmatter：
```yaml
id: candidate_<timestamp>
type: candidate
gem_level: flawed
source_fragments: [12, 15]       # 合成自哪些碎片
source_session: 9bbed2b8-...
confidence: 0.82                 # LLM 自评，仅作元数据（见 §6）
knowledge_type: procedural       # factual/procedural/preference/constraint
grounded_by: [[已有永久笔记标题]]  # 合成时参考的永久笔记（防幻觉佐证）
status: pending                  # pending → (L5) promoted/rejected
created_at: ...
---
# <AI 生成标题>
<AI 合成的结构化知识内容>
## 来源碎片
- Fragment {id} @ {timestamp}: {content_preview}
## 置信度说明
- 与 [[永久笔记]] 一致度 / 来源信号强度 / 上下文完整度
```

## 5. 触发与去重

- **触发**：daemon 后台循环（周期可配，默认沿用 auto_summary 节奏）。异步 —— LLM 调用慢，绝不进 hook 热路径（<100ms 教训）。
- **去重**：新增 `synthesis_log` 表（`anchor_fragment_id → candidate_note_id, synthesized_at`）。循环只查 ledger 里没有的锚点，不重复合成。

## 6. 置信度：记录但不丢弃（YAGNI）

- **本阶段不做"低于阈值丢弃"**。每个高信号锚点都产出一条 candidate，`confidence` 照样记录在 frontmatter。
- 理由：① LLM 自评 confidence 未校准，冷启动拿它做丢弃这种损失性决策不靠谱；② 先攒真实分布，"垃圾是否真多"验证后再加过滤；③ 与"碎片永不删"哲学一致。
- **未来（L5 或更晚）**：如确需过滤，做成查询期（`jfox candidates list --min-confidence X`）而非写入期丢弃。

## 7. 范围

**L3 本阶段做：**
- 合成管线（锚点 → transcript 片段 → 永久笔记 top-5 → LLM → candidate 笔记）
- `candidate` 笔记类型 + `GemLevel` 枚举（5 级建模，产出 flawed）
- `synthesis_log` 去重表
- daemon 循环（可配开关 + 周期，仿 auto_summary 的 config/loop 模式）
- 基础 `jfox candidates list`（查看产出的 candidate）

**不做（后续阶段）：**
- L4：candidate 笔记的成熟度递进机制（flawed→normal→flawless→perfect）
- L5：晋升工作流 `candidates review/confirm/reject/merge`、AI 辅助复核、candidate→permanent 转换、自动 vs 人工晋升规则
- 跨 session 语义聚合（embedding 聚类）

## 8. 模块拆分（初拟，plan 阶段细化）

| 模块 | 职责 |
|------|------|
| `jfox/gem_synth/` | 新包：合成循环 + 锚点查询 + transcript 解析 + LLM 调用 |
| `jfox/gem_synth/anchors.py` | 从 fragments.db 查未处理的高信号锚点 |
| `jfox/gem_synth/transcript.py` | 读 CC transcript.jsonl，按 timestamp 取"一轮"上下文 |
| `jfox/gem_synth/synthesizer.py` | 编排：上下文 + 永久笔记检索 → LLM → candidate 笔记 |
| `jfox/gem_synth/llm.py` | 独立 LLM 调用封装（不与 auto_summary 耦合，见 §9） |
| `jfox/gem_synth/loop.py` | daemon 后台循环（仿 auto_summary/loop.py） |
| `jfox/gem_synth/cli.py` | `jfox candidates list` 子命令 |
| `jfox/models.py` | NoteType 加 `candidate`；新增 `GemLevel` 枚举 |
| `jfox/global_config.py` | `gem_synthesis` 配置段（enabled/interval/anchor_types/top_k） |
| `jfox/daemon/server.py` | lifespan 启动 gem_synth 循环（仿 auto_summary） |

## 9. 待定 / 风险

- **LLM 调用**：gem_synth 建独立的 LLM 调用（不耦合 auto_summary）。理由：auto_summary 的「知识沉淀」角色可能被宝石合成取代（auto_summary 保留作「周工作简报」用途），不应把新系统绑在可能被淘汰的设施上。若 auto_summary 的调用封装能 trivially 借鉴则参考，否则独立实现。
- **transcript 解析**：CC transcript JSONL 格式需实地确认（role/内容字段结构）。
- **永久笔记检索**：复用 `HybridSearchEngine`，限定 `--type permanent`。
- **GemLevel 成熟度机制**（L4）与**晋升规则**（L5） deliberately 留白。
