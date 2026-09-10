---
name: jfox-judge
description: |
  把 jfox 采集的 user prompt 判断、合成 candidate 并确认晋升的端到端工作流。
  judge 仅手动触发，agent 只起草不晋升——new 类的草稿逐条给你确认后才 promote。
  Triggers on: "判断 prompt", "prompts judge", "prompt 积压", "处置判断结果",
  "待解决问题清单", "judge prompts", "prompt 合成笔记", "prompt 转笔记".
---

# 判断 prompt 并沉淀笔记（端到端）

本 skill 处理 jfox 采集的 user prompt：判断哪些值得沉淀，合成 candidate（候选笔记，破损级草稿），逐条确认晋升 permanent（永久笔记）或拒绝。judge 只在你调用时运行（无后台循环）；agent 只负责分类、取证、起草，**晋升决策始终由你做**。

日常增量（几条到几十条）用本 skill 端到端走完；**pending 积压超过 50 条或存量清理时切 `jfox-promote`**（三模式大积压过审，见末节分工）。

## 标准流程

### Step 1：看积压

```bash
jfox prompts status
```

输出计数：`total_prompts`（总记录）/ `unjudged`（未判断）/ `failed`（判断失败）/ `pending_disposition`（已判断待处置）/ `active_unresolved`（待解决问题）。`unjudged` 和 `pending_disposition` 都为 0 时无活可干。

### Step 2：触发判断

```bash
jfox prompts judge                    # 默认批量（配置 default_limit，默认 50 条）
jfox prompts judge --limit 20         # 小批量试跑
jfox prompts judge --all              # 不限批量
jfox prompts judge --retry-failed     # 连失败项一起重判
jfox prompts judge --session <session_id>   # 只判某个会话
```

judge 内部先 drain（把本地 spool 兜底队列灌库），再按 session 分组批量调用外部 runner（默认本地 pi，禁用工具/会话/扩展/skills/项目上下文；远程需 `--allow-remote`）。

输出逐条形如 `#12 new → candidate 202609101234567890`（成功）或 `#13 <错误>`（失败）。

四类判断结果：

- **new** — 有新知识，已起草 candidate 草稿
- **repeated** — 反复出现的澄清/痛点，候选「待解决问题」
- **recorded** — 已记录过，无需动作
- **needs_review** — 证据不足或非知识类；合法结果，不会被强行归类

### Step 3：逐条处置（确认环节）

**new 类：看草稿 → 你确认 → 晋升或拒绝**

```bash
jfox prompts show <ID> --full          # 看 prompt 原文与 judgment 详情
jfox candidates show <note_id>         # 看 candidate 完整正文（note_id 取自 judge 输出）
jfox prompts promote <ID>              # 确认：晋升该 candidate 为 permanent
jfox prompts ignore <ID> --reject-candidate   # 拒绝：忽略并归档草稿
```

**repeated 类：问用户 → 标记待解决**

```bash
jfox prompts unresolved <ID>           # 写入「待解决问题」清单笔记（仅 repeated；--force 可覆盖）
jfox prompts resolve-unresolved <ID>   # 问题解决后移除标记，闭环
```

**failed / needs_review 类**

```bash
jfox prompts retry <ID>                # 重置失败/证据不足状态，下次 judge 重判
jfox prompts ignore <ID>               # 确定无价值，忽略
```

处置命令有严格前置校验（如 `promote` 仅 new + candidate pending、`unresolved` 仅 repeated）；不满足时命令拒绝执行，确需覆盖用 `--force --reason "<理由>"` 留痕。

### Step 4：（可选）待解决问题闭环

`unresolved` 写入的清单聚合在一条带 `unresolved-problems` 标签的 permanent 聚合笔记里；问题解决后用 `resolve-unresolved` 移除标记。清单本身就是实践中的痛点信号，值得定期回看。

## 安全注意

- **仅手动触发**：hook 和 daemon 都不运行判断，每次 judge 由你显式发起。
- **runner 隔离**：默认本地 pi runner 禁用工具、会话、扩展、skills 和项目上下文，prompt 只走 stdin，被判断的 prompt 内容不会被 runner 执行。
- **隐私边界**：judge 会把 transcript（会话对话记录）上下文送给 runner；远程 runner 必须显式 `--allow-remote`——全文会离开本机。
- **前置校验与留痕**：默认动作前置不满足即拒绝；`--force --reason` 覆盖必须写明理由（留痕）。
- **不做自动决策**：judge 不做自动去重、自动合并、置信度过滤；candidate 是否晋升由你决定。

## 数据运维

```bash
jfox prompts drain                  # daemon 停机时把本地 spool 兜底灌库（judge 内部也会先 drain）
jfox prompts backfill --dry-run     # 预览从旧 session_fragments 回填历史 UserPromptSubmit
jfox prompts list --limit 50        # 浏览已记录 prompt（默认每页 20）
jfox prompts config                 # 查看/设置采集与判断配置（如 default_limit）
```

采集链路：hook（Claude Code）/ pi 扩展 → 本地 spool → POST daemon → `user_prompts` 表。daemon 不可用时 spool 保留不丢，用 `drain` 恢复。pi 会话来源标记为 `pi-coding-agent`，Claude Code 为 `claude-code`。

## 与 jfox-promote 的分工

- **本 skill**：日常增量（几条到几十条）——判断 + 逐条处置，端到端。
- **jfox-promote**：pending 积压超过 50 条或存量清理——三模式过审（客观去重扫描 / 簇级 triage / 单条 A/B/C）。
- judge 产出的 candidate 带 `source_prompts` 溯源字段，与存量 candidate 走同一过审队列；两边不要并行重复处置同一条。
