# session-summary skill 精简（去两步确认）设计

**日期**：2026-07-12
**Issue**：#311
**目标 PR 分支**：`feat/issue-311-session-summary-streamline`（main 受保护，必须新分支 + PR）
**关联**：反掉 #154（`2026-04-15-session-summary-confirmation-design.md` 引入的两步确认）；保留 #202（`2026-05-09-session-note-type-design.md` 的 `session` 类型）作为硬编码默认

## 1. 问题

`session-summary` skill 当前生成总结后连续弹两次 `AskUserQuestion`：

- **Step 2 内容确认**：`笔记内容是否 OK？` → 内容没问题 / 需要修改（循环直到满意）
- **Step 3 选择笔记类型**：`session` / `fleeting` / `literature` / `permanent`

这两步是 #154 当年主动加的"防误写"设计（动机原文：「用户无法审查内容或选择笔记类型」）。随后 #202 新增 `session` 类型，成了 Step 3 的推荐项。

实际使用证明这套摩擦已无必要：

- 生成的总结基本都准确，"内容是否 OK"几乎总点"内容没问题"——纯交互阻塞。
- 笔记类型实际 100% 选 `session`（本就为 AI Agent 会话记录设计），类型选择多余。
- 用户仍想生成后**看到**内容，但不需要被交互挡住写入；不满意事后 `jfox edit` 即可。

## 2. 目标 / 非目标

**目标**

- 删掉两个 `AskUserQuestion`（内容确认 + 类型选择）。
- 笔记类型固定 `session`，`--topic` 仍由总结内容自动归纳。
- 总结以普通文本输出供阅读 + 立即写入，写入前无任何交互。
- 4 个 SKILL.md 变体同步精简，各自保留平台措辞 / namespace / JSON 标志差异。

**非目标**

- 不改 CLI 或 Python（`session` 类型与 `--topic` 参数 #202 已实现并稳定）。
- 不改总结内容模板（Step 1 的结构化模板不变）。
- 不动 `jfox add` 参数语义。
- 不清理历史已写入的 session 笔记。

## 3. 新流程

原 5 步收敛为 3 步：

| Step | 内容 | 变化 |
|------|------|------|
| Step 1 | 生成会话总结（结构化模板） | 不变 |
| Step 2 | 用普通文本展示总结 + **直接写入** `--type session` | 合并原 Step 2/3/4，删两个 `AskUserQuestion` |
| Step 3 | 处理长内容（`--content-file`） | 原 Step 5，不变 |

### Step 2 要点

- 总结内容先以普通文本输出供用户阅读，**随即直接写入**，不弹 `AskUserQuestion`。
- `--type session` 硬编码；`--topic` 必填，由总结内容归纳为简短英文 slug（如 `atomic-write`、`daemon-stop-fix`）。
- 标题统一 `Session: <简短主题>`，标签统一 `session`。
- 文末注明：如事后需修改用 `jfox edit`。

## 4. 改动范围（4 个 SKILL.md）

| 文件 | 平台 | 状态 |
|------|------|------|
| `packages/cc-plugin/skills/session-summary/SKILL.md` | Claude Code（marketplace 正版） | 主改 |
| `packages/kimi-plugin/skills/jfox-session-summary/SKILL.md` | Kimi Code（正版） | 主改 |
| `skills-recommend/pi/jfox-session-summary/SKILL.md` | pi coding agent | 同步 |
| `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md` | Kimi CLI（已被 kimi-plugin 取代的旧版） | 同步（避免漂移） |

### 各变体必须保留的差异（只动确认流程，不抹平台特征）

| 变体 | 第 9/11 行措辞 | 复用 namespace | JSON 标志 |
|------|---------------|---------------|-----------|
| cc-plugin | 「Claude Code」 | `/jfox:manage` §4.1/§4.5 | `--format json` |
| kimi-plugin | 「Kimi Code」 | `/skill:jfox-manage` §4.1/§4.5 | `--json` |
| skills-recommend/pi | 「Claude Code」 | `/jfox-common` | `--format json` |
| skills-recommend/kimi-cli | 「当前会话」 | `/skill:jfox-common` | `--json` |

### 每个文件的统一改动点

1. **开篇描述行**：去掉「（支持用户确认和笔记类型选择）」，改为「（session 类型，生成后直接写入）」之类。
2. **删原 Step 2（用户确认）整段** + **删原 Step 3（选择笔记类型）整段**。
3. **原 Step 4 → 新 Step 2**：标题改为「展示总结并写入知识库」，`--type <Step 3 选定的类型>` → `--type session`；补一句"内容已在上方以普通文本展示，如需修改事后 `jfox edit`"。
4. **原 Step 5 → 新 Step 3**：`--type <Step 3 选定的类型>` → `--type session`（出现在 `--content-file` 示例里）。
5. **命令参考段**：`--type <type>` → `--type session`。

## 5. 验证

skill-only，无单测。验收：

- `grep -n "AskUserQuestion\|内容是否 OK\|选择笔记类型" packages/*/skills/*/SKILL.md skills-recommend/*/jfox-session-summary/SKILL.md` → 4 文件均无命中。
- `grep -n "Step 3 选定的类型\|--type <type>" <4 文件>` → 无命中。
- 4 文件均含 `--type session` 且保留各自 namespace / JSON 标志 / 平台措辞。
- 人工通读 cc-plugin 版确认流程自洽（Step 编号连续、无悬挂引用）。

## 6. 风险

- **不再有写入前兜底**：偶尔生成的差总结会直接落盘。缓解：内容仍展示给用户，`jfox edit` 可改、可删。用户已明确接受此权衡（见 #311）。
- **`--topic` 归纳质量**：由模型从内容归纳英文 slug，质量与原先一致（原先也是自动归纳，只是多了确认步）。
- **skills-recommend/kimi-cli 是旧版**：已被 `packages/kimi-plugin` 取代，但仍同步以防拷贝漂移；若维护方判定可废弃，可另行清理（不在本 issue 范围）。
