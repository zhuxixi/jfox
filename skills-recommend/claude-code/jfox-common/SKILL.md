---
name: jfox-common
description: Use when user wants to create, manage, or check the health of a Zettelkasten knowledge base. Triggers on "创建知识库", "初始化", "知识库管理", "检查知识库", "知识库健康", "知识库体检", "health check", "create knowledge base", "init", "kb management", "知识库诊断".
---

# JFox 知识库管理与健康检查

管理知识库的完整生命周期：创建、切换、查看状态，以及定期健康检查与衰减信号检测。将知识库管理（低频操作）与健康管理合并为一个技能。

## 前置条件

确认 jfox 已安装：
```bash
jfox --version
```
未安装时：`uv tool install jfox-cli`

## 知识库路径约定

所有知识库存储在 `~/.zettelkasten/` 下：

| 命令 | 知识库名称 | 路径 |
|------|-----------|------|
| `jfox init` | default | `~/.zettelkasten/default/` |
| `jfox init --name work` | work | `~/.zettelkasten/work/` |
| `jfox init --name research` | research | `~/.zettelkasten/research/` |

自定义路径须在 `~/.zettelkasten/` 下（CLI 强制限制）。

## 知识库管理

### 检查现有知识库

```bash
jfox kb list --format json
```

如果已有知识库，告知用户并询问是使用现有知识库还是创建新知识库。

### 创建知识库

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

### 创建后验证

```bash
jfox kb current --format json
jfox status --format json
```

确认知识库已注册、目录结构已创建、状态显示 0 条笔记。

### 管理命令

```bash
jfox kb switch <name>               # 切换知识库
jfox kb info <name> --format json   # 查看详情
jfox kb current --format json       # 当前知识库
jfox kb rename <old> <new>          # 重命名
```

## 笔记 CRUD

### 添加笔记

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

### 编辑笔记

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

### 删除笔记

```bash
jfox delete <note_id>               # 需确认
jfox delete <note_id> --force       # 跳过确认
```

### 查看笔记

```bash
jfox list --format json --limit 50              # 列出笔记
jfox list --type permanent --format json         # 按类型筛选
jfox daily --json                                # 今天的笔记
jfox daily --date 2026-04-01 --json              # 指定日期
jfox refs --search "<标题>" --format json        # 查看反向链接
```

### 删除知识库

```bash
jfox kb remove <name>               # 仅注销，保留笔记文件
jfox kb remove <name> --force       # 删除知识库（含笔记文件，不可恢复）
```

### 查看状态

```bash
jfox status --format json           # 当前知识库状态
```

所有命令均支持 `--kb <name>` 指定目标知识库，省略时使用当前默认知识库。

## 健康检查

通过组合多个 jfox 命令采集指标，综合评估知识库健康状况。没有单独的 "health" 命令，需要从多个数据源收集并综合分析。

> 如果用户指定了目标知识库名称，在以下所有命令中追加 `--kb <name>` 参数。未指定时省略，使用当前默认知识库。

### 6 项指标采集

```bash
# 1. 知识库总体状态
jfox status --format json [--kb <name>]

# 2. 图谱指标（--stats 和 --orphans 互斥，分开运行）
jfox graph --stats --json [--kb <name>]

# 3. 孤立笔记列表
jfox graph --orphans --json [--kb <name>]

# 4. 索引完整性
jfox index verify [--kb <name>]

# 5. 笔记清单（用于类型分布和日期分析）
jfox list --format json --limit 500 [--kb <name>]

# 6. 未处理收件箱
jfox inbox --json --limit 100 [--kb <name>]
```

### 健康指标表

从采集数据中计算以下指标：

| 指标 | 数据来源 | 健康 | 警告 | 危险 |
|------|---------|------|------|------|
| **孤立比例** | `isolated_nodes / total_nodes` | < 20% | 20-40% | > 40% |
| **平均连接度** | `avg_degree` (图谱统计) | > 2.0 | 1.0-2.0 | < 1.0 |
| **收件箱积压** | fleeting 笔记数量 | < 10 | 10-30 | > 30 |
| **索引完整性** | `jfox index verify` 结果 | 全部通过 | -- | 任何异常 |
| **连通率** | `(total_nodes - isolated_nodes) / total_nodes` | > 0.8 | 0.6-0.8 | < 0.6 |
| **类型平衡** | fleeting 占 total 比例 | fleeting < 30% | 30-50% | > 50% |

### 衰减信号检测

分析指标，检测以下 5 种衰减模式：

#### 1. 知识孤岛（孤立比例过高）
- **信号**：> 40% 的笔记没有任何链接
- **原因**：笔记已记录但未与现有知识建立关联
- **修复**：运行 `/jfox-organize` 查找并为孤立笔记添加链接

#### 2. Inbox 积压（未处理笔记过多）
- **信号**：> 30 条未处理的 fleeting 笔记
- **原因**：持续捕获想法，但未进行反思和提炼
- **修复**：运行 `/jfox-organize` 处理收件箱

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

### 评分系统

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

### 报告格式

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

### 运行时机建议

- **每周一次**：作为定期知识管理流程的快速健康检查
- **批量导入后**：验证索引和连接是否健康
- **整理前**：识别需要优先关注的区域
- **感觉知识库停滞时**：检测具体的衰减模式以对症下药

## 命令参考

以下仅列出知识库管理、笔记 CRUD 和健康检查相关命令。所有命令支持 `--kb <name>` 指定知识库，省略时使用当前默认知识库。

**约定**：所有命令均支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。

### 知识库管理

```bash
jfox init --name <name> --desc "<desc>"     # 创建知识库
jfox kb list --format json                  # 列出所有知识库
jfox kb switch <name>                       # 切换知识库
jfox kb info <name> --format json           # 查看知识库详情
jfox kb current --format json               # 当前知识库
jfox kb rename <old> <new>                  # 重命名
jfox kb remove <name>                       # 注销（保留文件）
jfox kb remove <name> --force               # 删除（含文件，不可恢复）
jfox status --format json                   # 知识库状态
```

### 笔记 CRUD

```bash
jfox add "<content>" --title "<title>" --type <type> --tag <tags>  # 添加笔记
jfox add --content-file <path> --title "<title>"                   # 从文件添加
jfox edit <id> --content "<new>" --title "<title>"                 # 编辑笔记
jfox edit <id> --content-file <path>                               # 从文件编辑
jfox delete <id> --force                                           # 删除笔记
jfox show <id_or_title> --format json                             # 查看笔记完整内容
jfox list --format json --limit <N>                                # 列出笔记
jfox daily --json                                                  # 今天的笔记
jfox daily --date YYYY-MM-DD --json                                # 指定日期
jfox refs --search "<title>" --format json                         # 反向链接
```

### 数据导入

```bash
jfox ingest-log <repo-path> --limit <N> --type fleeting --kb <name>  # Git 仓库导入
jfox bulk-import <file.json> --type fleeting --kb <name>             # 批量导入
```

### 健康检查

```bash
jfox graph --stats --json                    # 图谱指标（与 --orphans 互斥，分开运行）
jfox graph --orphans --json                  # 孤立笔记列表
jfox index verify                            # 索引完整性验证
jfox index rebuild                           # 重建索引
jfox inbox --json --limit <N>                # 未处理笔记
```

### Daemon（可选）

```bash
jfox daemon start                               # 启动 embedding 守护进程
jfox daemon stop                                # 停止守护进程
jfox daemon status                              # 查看 PID、端口、模型信息
```

注意：daemon 依赖（fastapi、uvicorn）已作为必选依赖安装，`jfox daemon start` 可直接使用。

> 搜索、导入、整理等高频操作命令见对应技能文档（jfox-search、jfox-ingest、jfox-organize）。

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| "Knowledge base already exists" | 使用 `jfox kb switch <name>` 切换到已有知识库，或使用不同名称创建 |
| "Path is outside managed directory" | 所有知识库必须在 `~/.zettelkasten/` 下 |
| `jfox: command not found` | 安装：`uv tool install jfox-cli` |
| 索引过时或 `jfox index verify` 异常 | 运行 `jfox index rebuild` 重建搜索索引 |
| `ingest-log` 报 "Not a git repository" | 提供正确的 Git 仓库路径 |
