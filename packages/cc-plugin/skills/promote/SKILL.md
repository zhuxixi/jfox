---
name: promote
description: Use when user wants to review/promote gem-synth candidate notes into permanent notes, or reject/archive inaccurate ones. 过审 L5 候选宝石，分流 triage（准确/半准/不准），改写晋升或归档拒绝。Triggers on "过审 candidate", "过审宝石", "晋升候选笔记", "审阅候选宝石", "candidate 过审", "L5 晋升", "promote candidate", "review candidate", "broken candidate".
---

# 过审 candidate（破损→完整）

把 L3 合成产出的 candidate（pending/flawed）逐条过审，晋升为 permanent 或拒绝归档。
对应 #249 五层 Loop Engineering 的 L5 晋升层。

## 过审流程（三档分流 triage）

取下一条 pending candidate（`jfox candidates list --status pending`，按 confidence 降序），
然后按**准确度**分流：

### 档 A：准确（无实质错误）
1. 读 candidate 全文 + 其 `grounded_by` 指向的 permanent（`jfox show <id>`）
2. 微调：清 candidate 专属段落（「待人工审阅」「置信度说明」），整理成 permanent 风格
3. wiki link：验证已有 `[[参考笔记]]` 链对 + 用 `jfox suggest-links "<正文>"` 补漏链
4. 展示改写后正文 + wiki link 报告，请用户确认
5. 确认 → 改写回文件后 `jfox candidates promote <id>`

### 档 B：大部分对、局部有问题（澄清）
1. 列出问题点（哪条事实待定 / 哪处二选一 / 缺什么信息），一次性给出，请用户批量回答
2. 据回答改写（含 §A 的微调 + 补链）
3. 可能多轮澄清；完成后展示 → 确认 → `jfox candidates promote <id>`

### 档 C：整体不可信
1. 给出依据（与哪条 permanent 冲突 / grounding 崩了）
2. 请用户确认拒绝 → `jfox candidates reject <id> --reason "<原因>"`

## 边界原则
- **能确信改对的**（格式、candidate 元段落、明显缺链）→ 微调，直接改，不问用户
- **需要用户判断的**（事实对错、语义二选一、关键信息缺失）→ 澄清
- **整体不可信的**（冲突/grounding 崩）→ reject

## 关键约束
- 晋升前把改写后的正文写回 candidate 文件（promote 只改 type/移文件/回填 backlinks，不改正文）
- wiki link 补链阈值 ≥ 0.6（与 organize skill 一致）
- 用户始终有最终决定权：agent 判档 + 给依据，用户可 override
