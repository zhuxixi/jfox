# JFox Skill 重设计方案

## 背景

现有的 5 个 jfox skill（init、insert、organize、search、health）存在以下问题：
1. 冗余：insert 和 organize 之间有大量重复的命令参考
2. 缺失：没有覆盖从 GitHub 仓库批量导入 git log / PR / Issues 的流程
3. 不足：organize 缺少从 fleeting 提炼 permanent 时自动生成 `[[wiki links]]` 的能力
4. 繁琐：用户需要记忆 5 个命令，且部分 skill 过于低频（如 init）

## 用户工作流

用户的核心知识管理工作流是一条清晰的流水线：

```
1. jfox-common (一次性/低频) → 创建知识库、健康检查
2. jfox-ingest (低频)       → 从本地仓库导入 git log / GitHub PR / Issues 为 fleeting 笔记
3. jfox-organize (中频)     → 从 fleeting 提炼 permanent，生成 [[wiki links]]，图谱分析
4. jfox-search (高频，穿插) → 随时搜索、查询图谱、推荐链接
```

### 导入场景

- 仓库已经在本地，用户指定本地路径
- Agent 自动检测 remote origin 判断是否是 GitHub 仓库
- GitHub 仓库：用 `gh cli` 补充读取 PR / Issues
- 非 GitHub 仓库（如 GitLab）：只导入 git log
- v1 只做 GitHub 适配，预留 GitLab 扩展点
- 不做定时自动导入，手动为主，可选定时通过 cron 实现

### 提炼场景

- 融入 jfox-organize，不单独建 skill
- 从 fleeting 笔记中按来源/主题智能分组
- 识别可合并的笔记组（如同一 repo 的多个 commits 合并为一条 permanent）
- 生成 permanent 笔记时自动嵌入 `[[wiki links]]` 到相关笔记
- literature 类型暂不覆盖

## 方案：4 Skill 架构

从 5 个 skill 变为 4 个：

| 旧 Skill | 新 Skill | 变化 |
|----------|---------|------|
| jfox-init | jfox-common | 合并进 common |
| jfox-insert | jfox-ingest + jfox-organize | 能力分散 |
| jfox-organize | jfox-organize | 大幅加强 |
| jfox-search | jfox-search | 小幅精简 |
| jfox-health | jfox-common | 合并进 common |
| (新增) | jfox-ingest | 全新 |

### 目录结构

```
skills-recommend/claude-code/
├── jfox-ingest/       # 数据导入（新建）
├── jfox-organize/     # 整理提炼（重写）
├── jfox-search/       # 搜索查询（精简）
└── jfox-common/       # 知识库管理 + 健康检查（新建）
```

---

## Skill 详细设计

### 1. jfox-ingest

**职责**：从外部数据源导入信息为 fleeting 笔记。

**触发条件**：`/jfox-ingest`、"导入仓库信息"、"抓取 git log"、"导入 PR"、"导入 issues"、"读一下这个仓库"、"ingest repo"、"import notes from repository"

#### 数据源与采集方式

| 数据源 | 采集命令 | 输出 |
|--------|---------|------|
| Git Log | `git -C <path> log --format="%H\|%s\|%b\|%an\|%ad" --date=short -50` | 每条 commit 一条 fleeting |
| GitHub PRs | `gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels` | 每条 PR 一条 fleeting |
| GitHub PR Comments | `gh pr view <number> --repo <owner/repo> --json comments` | comments 附加到对应 PR 笔记 |
| GitHub Issues | `gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments` | 每条 issue 一条 fleeting |
| 手动输入 | 用户粘贴文本 | 结构化为 1 条 fleeting |

#### 工作流

1. **确定仓库信息**：用户提供本地路径，agent 检测 `git -C <path> remote get-url origin` 判断是否是 GitHub 仓库
2. **选择数据源**：根据用户指令选择导入 git log / PR / Issues / 全部
3. **采集数据**：执行对应命令采集原始数据
4. **去重检查**：`jfox search` 检查是否已有相同来源的笔记
5. **结构化**：将采集的数据转为 JSON 格式，每条记录生成一条 fleeting 笔记的 title + content + tags
6. **批量插入**：生成临时 JSON 文件，`jfox bulk-import <file> --type fleeting --kb <name>`
7. **确认报告**：报告插入了多少条笔记，来源分布

#### 笔记格式

每条导入的 fleeting 笔记包含：
- title: commit message 首行 / PR 标题 / Issue 标题
- content: 详细信息（body、comments、关联文件等）
- tags: `source:<repo-name>`, `source:git-log` / `source:pr` / `source:issue`, 以及内容相关的 topic tags
- 不添加 `[[wiki links]]`（fleeting 笔记之间不需要图谱关系）

#### 手动输入支持

用户直接粘贴文本时，agent 将其结构化为 1 条 fleeting 笔记，用 `jfox add` 插入。

---

### 2. jfox-organize

**职责**：整理知识库——从 fleeting 提炼 permanent、生成 `[[wiki links]]`、图谱优化。

**触发条件**：`/jfox-organize`、"整理知识库"、"清理 inbox"、"提炼笔记"、"组织笔记"、"看看有什么可以整理的"、"organize"、"process inbox"

#### 核心流程（3 步）

**Step 1：Inbox 分析**

```
1. jfox inbox --json --limit 50          # 列出所有 fleeting
2. 按 tag/来源分组                       # 同一 repo 的 commits 聚在一起
3. 识别可合并的笔记组                    # 相似主题的 commits 可合并为一条 permanent
4. 向用户展示提炼建议列表
```

建议列表格式：
```
收件箱: N 条 fleeting 笔记

提炼建议:
1. [合并] 15 条 jfox git log commits → "JFox 近期开发总结" (permanent)
2. [合并] 5 条 jfox PR → "JFox PR 技术决策汇总" (permanent)
3. [保留] 3 条手动输入笔记 → 逐条处理
4. [删除] 2 条过时笔记 → 清理
```

**Step 2：提炼（fleeting → permanent）**

对用户确认的每条建议：
1. 分析内容，提炼核心知识点
2. `jfox suggest-links "<content>" --format json` 找到现有笔记中的关联
3. 生成 permanent 笔记，嵌入 `[[wiki links]]` 到相关笔记
4. `jfox add "<content>" --title "<title>" --type permanent --tag <tags>`
5. 删除已提炼的原始 fleeting 笔记：`jfox delete <original-id> --force`

关键：提炼出的 permanent 笔记之间也应该有 `[[wiki links]]`，形成图谱。

**Step 3：图谱优化**

```
1. jfox graph --orphans --json           # 找孤立笔记
2. 对孤立笔记执行 jfox suggest-links     # 推荐链接
3. jfox graph --stats --json             # 确认改善
4. 输出优化建议
```

#### 提炼策略

| 来源 | 提炼策略 | permanent 笔记示例 |
|------|---------|-------------------|
| git log (多个 commits) | 按时间段/主题合并，提取技术决策和变更摘要 | "JFox v0.1.4 技术变更总结" |
| GitHub PRs | 提取核心设计决策、争议点、最终方案 | "JFox PR#94 编辑命令的设计讨论" |
| GitHub Issues | 提取问题本质、解决方案、经验教训 | "JFox BM25 索引问题及修复方案" |
| 手动输入 | 根据内容判断是否值得提炼 | — |

#### 吸收的 jfox-insert 能力

整理过程中可以直接创建新笔记（permanent 或 fleeting），无需切换到其他 skill。

---

### 3. jfox-search

**职责**：搜索和查询知识库中的笔记。

**触发条件**：`/jfox-search`、"搜索"、"查找"、"找一下"、"查一下"、"有没有关于"、"search notes"、"find"、"look up"

#### 搜索策略（保持现有）

| 用户意图 | 策略 | 命令 |
|----------|------|------|
| 精确关键词 | BM25 | `jfox search "<keyword>" --mode keyword --format json` |
| 概念/想法 | Hybrid | `jfox search "<concept>" --mode hybrid --format json` |
| 纯语义相似 | Semantic | `jfox search "<idea>" --mode semantic --format json` |
| 探索相关主题 | 图谱遍历 | `jfox query "<topic>" --depth 2 --json` |
| 查看引用关系 | Backlinks | `jfox refs --search "<title>" --format json` |
| 链接推荐 | Suggestions | `jfox suggest-links "<content>" --format json` |

#### 调整

- 移除 literature 相关搜索过滤
- 精简命令参考（不重复其他 skill 已有的通用命令）

---

### 4. jfox-common

**职责**：知识库生命周期管理 + 健康检查。合并现有 init 和 health skill。

**触发条件**：`/jfox-common`、"创建知识库"、"检查知识库"、"知识库健康"、"jfox init"、"health check"

#### 知识库管理

```bash
jfox init --name <name> --desc "<description>"  # 创建
jfox kb list --format json                       # 列出
jfox kb switch <name>                            # 切换
jfox kb info <name> --format json               # 详情
jfox kb current --format json                    # 当前
jfox status --format json                        # 状态
```

#### 健康检查

沿用现有 jfox-health 的全部能力：

**6 项指标采集**：
1. `jfox status --format json`
2. `jfox graph --stats --json`
3. `jfox graph --orphans --json`
4. `jfox index verify`
5. `jfox list --format json --limit 500`
6. `jfox inbox --json --limit 100`

**健康指标**：

| 指标 | 健康 | 警告 | 严重 |
|------|------|------|------|
| 孤立比例 | < 20% | 20-40% | > 40% |
| 平均连接度 | > 2.0 | 1.0-2.0 | < 1.0 |
| Inbox 积压 | < 10 | 10-30 | > 30 |
| 索引完整性 | 通过 | — | 任何无效 |
| 连通率 | > 0.8 | 0.6-0.8 | < 0.6 |
| 类型平衡 | fleeting < 30% | 30-50% | > 50% |

**5 种衰减信号**：知识孤岛、Inbox 积压、低连接度、索引失效、Hub 依赖

**评分**：0-100 分，映射为 A/B/C/D/F 等级

#### 调整

- 移除 literature 相关内容
- 精简命令参考（与其他 skill 去重）

---

## 不在范围内的内容

- **literature 笔记**：用户确认目前不使用，后续版本再覆盖
- **GitLab 适配**：v1 只做 GitHub，预留扩展点
- **定时自动导入**：通过 cron 手动配置，不在 skill 内
- **纯手动粘贴导入**：v1 覆盖基础支持，后续可增强

## 删除的文件

```
skills-recommend/claude-code/
├── jfox-init/SKILL.md       # 删除（合并进 jfox-common）
├── jfox-insert/SKILL.md     # 删除（能力分散到 ingest 和 organize）
└── jfox-health/SKILL.md     # 删除（合并进 jfox-common）
```
