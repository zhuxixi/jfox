---
name: jfox-manage
description: |
  Use when user wants to create, manage, or check the health of a Zettelkasten knowledge
  base, look up the canonical reference for any jfox note command (add/edit/delete/
  list/show/refs/daily), or start/stop the embedding daemon. Triggers on "创建知识库",
  "初始化", "知识库管理", "切换知识库", "重命名知识库", "删除知识库", "检查知识库",
  "知识库健康", "知识库体检", "知识库诊断", "守护进程", "启动 daemon", "停止 daemon",
  "kb status", "create knowledge base", "init", "kb management", "health check",
  "knowledge base decay", "jfox 命令参考", "jfox CRUD", "embedding daemon".
---

# JFox 知识库管理、命令参考与健康检查

管理知识库的完整生命周期；作为 jfox 笔记命令（add/edit/delete/list/show/refs/daily）的权威参考；提供定期健康检查与衰减信号检测。

## 1. 前置条件

确认 jfox 已安装：
```bash
jfox --version
```
未安装时：`uv tool install jfox-cli`

## 2. 知识库路径约定

所有知识库存储在 `~/.zettelkasten/` 下：

| 命令 | 知识库名称 | 路径 |
|------|-----------|------|
| `jfox init` | default | `~/.zettelkasten/default/` |
| `jfox init --name work` | work | `~/.zettelkasten/work/` |
| `jfox init --name research` | research | `~/.zettelkasten/research/` |

自定义路径须在 `~/.zettelkasten/` 下（CLI 强制限制）。

## 3. 知识库生命周期

### 3.1 检查现有知识库

```bash
jfox kb list --json
```

如果已有知识库，告知用户并询问是使用现有知识库还是创建新知识库。

### 3.2 创建知识库

**默认知识库（首次使用）：**
```bash
jfox init
```

**命名知识库：**
```bash
jfox init --name <name> --desc "<description>"
```

示例：
```bash
jfox init --name work --desc "工作笔记"
jfox init --name research --desc "研究笔记"
jfox init --name personal --desc "个人知识库"
```

**自定义路径（必须在 ~/.zettelkasten/ 下）：**
```bash
jfox init --name <name> --path ~/.zettelkasten/<custom-path>
```

### 3.3 创建后验证

```bash
jfox kb current --json
jfox status --json
```

确认知识库已注册、目录结构已创建、状态显示 0 条笔记。

### 3.4 切换与重命名

```bash
jfox kb switch <name>               # 切换知识库
jfox kb info <name> --json          # 查看详情
jfox kb current --json              # 当前知识库
jfox kb rename <old> <new>          # 重命名
```

### 3.5 删除知识库

```bash
jfox kb remove <name>               # 仅注销，保留笔记文件
jfox kb remove <name> --force       # 删除知识库（含笔记文件，不可恢复）
```

### 3.6 查看状态

```bash
jfox status --json                  # 当前知识库状态
```

## 4. Canonical 笔记 CRUD 参考

> **本节是 jfox 笔记命令的权威参考；ingest、organize、session-summary 技能直接引用此处，仅在文档中记录自身工作流相关的差异（如标签命名、特殊参数）。**

### 4.1 共享约定

- 所有命令均支持 `--kb <name>` 指定目标知识库，省略时使用当前默认知识库
- 大部分命令支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。**例外**：`jfox show` 仅输出原始 Markdown，无 JSON 模式
- 长内容或含特殊字符时，使用 `--content-file <path>` 从文件读取；`--content-file -` 表示从 stdin 读取，可避免 shell 转义问题

### 4.2 添加笔记

```bash
# 快速添加（内容直接作为参数）
jfox add "笔记内容，支持 [[其他笔记标题]] 链接" --title "笔记标题"

# 指定类型和标签
jfox add "内容" --title "标题" --type permanent --tag design --tag backend

# 从文件读取内容（v0.2.1+，适合长文本）
jfox add --content-file notes/draft.md --title "标题" --type literature

# 从 stdin 读取
cat notes.txt | jfox add --content-file - --title "标题"

# 使用模板
jfox add --template meeting --title "周会记录"
```

笔记类型：
- `fleeting`（默认）— 快速捕获，稍后提炼
- `literature` — 阅读笔记
- `permanent` — 已提炼的知识
- `session` — AI Agent 会话记录（用法及 `--topic` 必填参数详见 `/skill:jfox-session-summary`）

### 4.3 编辑笔记

```bash
# 编辑内容和标题
jfox edit <note_id> --content "新内容" --title "新标题"

# 从文件读取内容（v0.2.1+，适合长文本）
jfox edit <note_id> --content-file updated.md

# 修改标签和类型
jfox edit <note_id> --tag new-tag1 --tag new-tag2 --type permanent

# 在指定知识库中编辑
jfox edit <note_id> --kb work --content "新内容"
```

编辑会保留原始笔记 ID 和创建时间。

### 4.4 删除笔记

```bash
jfox delete <note_id>               # 需确认
jfox delete <note_id> --force       # 跳过确认
```

### 4.5 查看笔记

```bash
jfox show <id_or_title>                         # 查看笔记完整内容（输出 Markdown，不支持 --json）
jfox list --json --limit 50                     # 列出笔记
jfox list --type permanent --json               # 按类型筛选
jfox daily --json                               # 今天的笔记
jfox daily --date 2026-04-01 --json             # 指定日期
jfox refs --search "<标题>" --json              # 查看反向链接
```

## 5. 健康检查

通过组合多个 jfox 命令采集指标，综合评估知识库健康状况。没有单独的 "health" 命令，需要从多个数据源收集并综合分析。

> 如果用户指定了目标知识库名称，在以下所有命令中追加 `--kb <name>` 参数。未指定时省略，使用当前默认知识库。

### 5.1 6 项指标采集

以下 6 个命令均为**只读操作**，相互独立，应使用 **Kimi Code AgentSwarm** 并行采集以缩短等待时间；汇总全部输出后再进入 §5.2 计算指标与评分。

> 如果用户指定了目标知识库名称，在所有命令中追加 `--kb <name>` 参数。未指定时省略，使用当前默认知识库。

**并行采集命令列表（每个 item 独立执行）：**

```text
jfox status --json
jfox graph --stats --json
jfox graph --orphans --json
jfox index verify
jfox list --json --limit 500
jfox inbox --json --limit 100
```

**AgentSwarm 示例：**

```yaml
description: 并行采集知识库健康检查指标
items:
  - "jfox status --json [--kb <name>]"
  - "jfox graph --stats --json [--kb <name>]"
  - "jfox graph --orphans --json [--kb <name>]"
  - "jfox index verify [--kb <name>]"
  - "jfox list --json --limit 500 [--kb <name>]"
  - "jfox inbox --json --limit 100 [--kb <name>]"
prompt_template: "执行命令 {{item}}，返回原始输出以及解析后的 JSON 数据。"
```

每个子代理执行其分配的 `{{item}}` 命令，返回原始输出与解析后的 JSON；主代理汇总 6 份结果后再进行后续分析与报告生成。

> 当 AgentSwarm 被调用时，它必须是当轮唯一的 tool call。本例中 6 条命令作为一个 AgentSwarm 调用同时派发，满足该约束。

** Fallback（单线程）：** 如果 AgentSwarm 不可用或命令数极少，也可顺序执行上述 6 个命令。

### 5.2 健康指标表

从采集数据中计算以下指标：

| 指标 | 数据来源 | 健康 | 警告 | 危险 |
|------|---------|------|------|------|
| **孤立比例** | `isolated_nodes / total_nodes` | < 20% | 20-40% | > 40% |
| **平均连接度** | `avg_degree` (图谱统计) | > 2.0 | 1.0-2.0 | < 1.0 |
| **收件箱积压** | `jfox inbox` 返回的 fleeting + session 笔记数 | < 10 | 10-30 | > 30 |
| **索引完整性** | `jfox index verify` 结果 | 全部通过 | -- | 任何异常 |
| **连通率** | `(total_nodes - isolated_nodes) / total_nodes` | > 0.8 | 0.6-0.8 | < 0.6 |
| **类型平衡** | fleeting 占 total 比例 | fleeting < 30% | 30-50% | > 50% |

### 5.3 衰减信号检测

分析指标，检测以下 5 种衰减模式：

#### 1. 知识孤岛（孤立比例过高）
- **信号**：> 40% 的笔记没有任何链接
- **原因**：笔记已记录但未与现有知识建立关联
- **修复**：调用 organize 技能（`/skill:jfox-organize`）查找并为孤立笔记添加链接

#### 2. Inbox 积压（未处理笔记过多）
- **信号**：> 30 条未处理的 fleeting 笔记
- **原因**：持续捕获想法，但未进行反思和提炼
- **修复**：调用 organize 技能（`/skill:jfox-organize`）处理收件箱

#### 3. 低连接度（平均连接度不足）
- **信号**：笔记平均链接数 < 1.0
- **原因**：添加笔记时未使用 `[[links]]` 语法
- **修复**：使用 `jfox suggest-links` 为现有笔记查找连接

#### 4. 索引失效（索引不同步）
- **信号**：`jfox index verify` 报告不匹配
- **原因**：文件在 jfox CLI 之外被添加或修改
- **修复**：`jfox index rebuild` 重建搜索索引

#### 5. Hub 依赖（图谱结构脆弱）
- **信号**：Top 3 中心节点拥有 > 50% 的所有边
- **原因**：过度依赖少数"枢纽"笔记
- **修复**：创建中间笔记以分散连接

### 5.4 评分系统

计算总体评分（0-100）：

```
Score = 100
- min(orphan_ratio * 100, 40)                        # 最多扣 40 分
- min(max(0, 2.0 - avg_degree) * 10, 20)             # 最多扣 20 分
- min(max(0, inbox_count - 10), 20)                   # 最多扣 20 分
- (0 if verify_result["healthy"] else 20)             # 索引异常扣 20 分
```

评分对应等级：

| 分数 | 等级 | 状态 |
|------|------|------|
| 90-100 | A | 优秀 -- 健康，连接良好 |
| 75-89 | B | 良好 -- 存在少量问题 |
| 60-74 | C | 一般 -- 检测到衰减迹象 |
| 40-59 | D | 较差 -- 明显衰减 |
| 0-39 | F | 危险 -- 需要立即处理 |

### 5.5 报告格式

按以下格式呈现健康报告：

```
📊 知识库健康报告[KB: {kb_name}]

总体评分: {grade} ({score}/100)

✅ 索引完整性: {通过/未通过}
✅ 笔记总数: {N} (permanent: {X}, fleeting: {Y})
⚠️ 孤立笔记: {orphans}/{total} ({ratio}%) -- {建议}
⚠️ 平均连接度: {degree} -- {建议}
⚠️ 收件箱: {inbox_count} 条未处理 -- {建议}

详细指标:
- 集群数: {clusters}
- Top hubs: {hub_list}
- 连通率: {connectivity_ratio}

建议操作:
1. {最优先的操作}
2. {次要操作}
3. {可选优化}
```

使用默认知识库时显示 `[KB: default]`。

使用 emoji 指示器：
- ✅ 健康 / 通过
- ⚠️ 警告 / 需关注
- ❌ 危险 / 异常

### 5.6 运行时机建议

- **每周一次**：作为定期知识管理流程的快速健康检查
- **批量导入后**：验证索引和连接是否健康
- **整理前**：识别需要优先关注的区域
- **感觉知识库停滞时**：检测具体的衰减模式以对症下药

## 6. Daemon

```bash
jfox daemon start                               # 启动 embedding 守护进程
jfox daemon stop                                # 停止守护进程
jfox daemon status                              # 查看 PID、端口、模型信息
```

注意：daemon 依赖（fastapi、uvicorn）已作为必选依赖安装，`jfox daemon start` 可直接使用。批量整理 / 导入前启动 daemon 可加速 embedding 计算。

## 7. 命令参考速查

> 完整语法详见 §3–§6；本节按主题分组提供速查。

### 知识库生命周期

```bash
jfox init --name <name> --desc "<desc>"     # 创建知识库
jfox kb list --json                         # 列出所有知识库
jfox kb switch <name>                       # 切换知识库
jfox kb info <name> --json                  # 查看知识库详情
jfox kb current --json                      # 当前知识库
jfox kb rename <old> <new>                  # 重命名
jfox kb remove <name>                       # 注销（保留文件）
jfox kb remove <name> --force               # 删除（含文件，不可恢复）
jfox status --json                          # 知识库状态
```

### 笔记 CRUD

```bash
jfox add "<content>" --title "<title>" --type <type> --tag <tags>  # 添加笔记
jfox add --content-file <path> --title "<title>"                   # 从文件添加
jfox edit <id> --content "<new>" --title "<title>"                 # 编辑笔记
jfox edit <id> --content-file <path>                               # 从文件编辑
jfox delete <id> --force                                           # 删除笔记
jfox show <id_or_title>                                            # 查看笔记完整内容（无 --json）
jfox list --json --limit <N>                                       # 列出笔记
jfox daily --json                                                  # 今天的笔记
jfox daily --date YYYY-MM-DD --json                                # 指定日期
jfox refs --search "<title>" --json                                # 反向链接
```

### 健康检查

```bash
jfox graph --stats --json                    # 图谱指标（与 --orphans 互斥，分开运行）
jfox graph --orphans --json                  # 孤立笔记列表
jfox index verify                            # 索引完整性验证
jfox index rebuild                           # 重建索引
jfox inbox --json --limit <N>                # 未处理笔记
```

### Daemon

```bash
jfox daemon start                            # 启动 embedding 守护进程
jfox daemon stop                             # 停止守护进程
jfox daemon status                           # 查看状态
```

> 搜索（search）、导入（ingest）、整理（organize）、会话总结（session-summary）等高频操作命令见对应技能文档。

## 8. 错误处理

| 场景 | 处理方式 |
|------|---------|
| "Knowledge base already exists" | 使用 `jfox kb switch <name>` 切换到已有知识库，或使用不同名称创建 |
| "Knowledge base not found" | 调用本技能（`/skill:jfox-manage`）创建知识库 |
| "Path is outside managed directory" | 所有知识库必须在 `~/.zettelkasten/` 下 |
| `jfox: command not found` | 安装：`uv tool install jfox-cli` |
| 索引过时或 `jfox index verify` 异常 | 运行 `jfox index rebuild` 重建搜索索引 |
| `ingest-log` 报 "Not a git repository" | 提供正确的 Git 仓库路径（详见 `/skill:jfox-ingest`） |
