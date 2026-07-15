---
name: jfox-promote
description: Use when user wants to review/promote gem-synth candidate notes into permanent notes, or reject/archive inaccurate ones. 过审 L5 候选宝石，按 A/B/C 三档 triage（准确/半准/不准）分流，最终晋升 permanent 或拒绝归档；也用于在过审前监控 L3 合成进度与上游 fragments。Triggers on "candidate 过审", "过审 candidate", "过审宝石", "晋升候选笔记", "审阅候选宝石", "promote candidate", "review candidate", "L5 晋升", "broken candidate", "candidate 审核", "破损 candidate", "合成进度", "碎片", "gem-synth status", "fragments".
---

# 过审 candidate（破损→完整）

把 L3 合成产出的 candidate（pending/flawed）逐条过审，晋升为 permanent 或拒绝归档。

对应 #249 五层 Loop Engineering 的 L5 晋升层。

> 本技能复用 `/skill:jfox-manage` §4.1 的共享约定（`--kb` / `--json` / `--content-file` / `--format json`），下文示例统一使用 `--json` 简写。

## 前置条件

确认当前知识库存在且 jfox CLI 可用：

```bash
jfox --version
jfox kb current --json
```

若尚未初始化，先调用 `/skill:jfox-manage` 创建知识库。

## 监控 L3 合成

在 candidate 进入过审流程前，可先查看 L3 合成状态与上游碎片，确认是否有新的 candidate 产出或失败锚点。

### 查看合成状态

```bash
jfox gem-synth status --json
```

关注字段：

- `pending_candidates` / `total_candidates`：待过审数量
- `failed_anchors`：合成失败或无法 grounding 的 fragment 锚点，需要人工介入
- `last_run` / `is_running`：判断当前是否正在批量合成

### 查看碎片

Hook 采集的 session 碎片会进入 `fragments.db`，过审前可通过 fragments 命令了解候选宝石的上游上下文。

```bash
jfox fragments list --json
jfox fragments show <fragment_id> --json
```

`fragments list` 可用于定位 candidate 可能来源的 session 主题；`fragments show` 可查看碎片原文、所属 session、采集时间等元信息。

### 何时使用

- 批量合成后先执行 `gem-synth status`，按 pending 数量安排过审计划。
- 某条 candidate 内容存疑时，用 `fragments show` 追溯其来源 fragment，辅助判档。
- 发现 `failed_anchors` 时，可转由 `/skill:jfox-session-summary` 检查对应 session 是否已产生高质量 summary，再决定是否重新触发合成。

## 过审流程（三档分流 triage）

### Step 1: 获取 pending candidate 列表

```bash
jfox candidates list --status pending --json
```

按 `confidence` 降序挑选下一条待审 candidate。若无 pending candidate，告知用户当前没有需要过审的候选宝石。

### Step 2: 读取 candidate 及其 grounding

```bash
jfox candidates show <candidate_id> --json
jfox show <grounded_by_id>              # 读取 grounded_by 指向的 permanent 笔记
```

`grounded_by` 可能有多个，按需逐一读取。若 candidate 未提供 grounded_by，则仅基于 candidate 自身内容判断。

### Step 3: 按准确度分流

#### 档 A：准确（无实质错误）

1. **微调正文**：清除 candidate 专属段落（如「待人工审阅」「置信度说明」「grounded_by」等元信息），整理成 permanent 笔记风格。
2. **补全 wiki link**：
   - 验证现有 `[[参考笔记]]` 是否指向真实笔记
   - 用 `jfox suggest-links "<改写后的正文>" --json` 查找 score ≥ 0.6 的候选链接并补漏
3. **展示结果**：向用户展示改写后的正文 + wiki link 报告，等待确认。
4. **写回并晋升**：
   - 将改写后的正文写回 candidate 文件（promote 只改 type/移文件/回填 backlinks，不改正文）
   - 调用 `jfox candidates promote <candidate_id>`

#### 档 B：大部分对、局部有问题（需澄清）

1. **列出问题点**：一次性列出所有待澄清问题（哪条事实待定、哪处二选一、缺什么信息）。
2. **等待用户批量回答**。
3. **据回答改写**：执行 §A 中的微调 + 补链流程。
4. **可能多轮澄清**；完成后展示改写结果 → 确认 → `jfox candidates promote <candidate_id>`。

#### 档 C：整体不可信

1. **给出依据**：说明与哪条 permanent 冲突、 grounding 如何崩了、或存在哪些事实性错误。
2. **等待用户确认拒绝**。
3. **拒绝归档**：
   ```bash
   jfox candidates reject <candidate_id> --reason "<拒绝原因>"
   ```

## 边界原则

- **能确信改对的**（格式、candidate 元段落、明显缺链）→ 微调后直接改，不问用户。
- **需要用户判断的**（事实对错、语义二选一、关键信息缺失）→ 澄清后再处理。
- **整体不可信的**（与 permanent 冲突 / grounding 崩）→ 给出依据后 reject。

## 关键约束

- 晋升前必须把改写后的正文写回 candidate 文件；`jfox candidates promote` 不会替你改写正文。
- wiki link 补链阈值 ≥ 0.6（与 `/skill:jfox-organize` 一致）。
- 用户始终有最终决定权：agent 判档 + 给依据，用户可 override（例如 agent 判为 B，用户坚持直接 promote）。
- 涉及多个 candidate 时，建议一次只处理一条，避免批量晋升导致错误扩散。

## 命令参考

```bash
jfox candidates list --status pending --json        # 列出待审 candidate
jfox candidates show <id> --json                    # 查看 candidate 详情
jfox candidates promote <id>                        # 晋升为 permanent
jfox candidates reject <id> --reason "<原因>"        # 拒绝并归档
jfox show <id_or_title>                             # 查看 permanent 笔记全文（--json 输出结构化字段）
jfox suggest-links "<正文>" --json                  # 推荐 [[wiki links]] 候选
jfox edit <candidate_id> --content-file updated.md  # 将改写后的正文写回 candidate
```

> 通用命令（`add` / `edit` / `delete` / `list` / `show`）以及 `--kb` / `--content-file` 用法详见 `/skill:jfox-manage` §4。

### 合成与碎片监控命令

```bash
jfox gem-synth status --json              # 查看 L3 合成进度与失败锚点
jfox fragments list --json                # 列出 Hook 采集的 session 碎片
jfox fragments show <fragment_id> --json  # 查看碎片详情
```

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| 无 pending candidate | 告知用户当前没有需要过审的候选宝石 |
| `jfox suggest-links` 返回低匹配度（score < 0.6） | 跳过补链，不强制添加 |
| candidate 对应的 grounded_by 笔记不存在 | 报告缺失，并基于 candidate 自身内容继续判断 |
| 用户拒绝 agent 的判档 | 按用户意图重新分流或终止 |

## 使用建议

- **定期过审**：建议每批 L3 合成完成后立即过审，避免 pending candidate 堆积。
- **优先高 confidence**：按 confidence 降序处理，先处理 agent 自身最有把握的候选。
- **大胆 reject**：整体不可信的 candidate 不应强行晋升，拒绝并归档是对知识库质量的保护。
