---
name: jfox-session-to-permanent
description: |
  Distill reusable knowledge from the CURRENT conversation into permanent notes.
  Unlike session-summary (archive the whole conversation as a session note) and
  organize (refine notes already piled in the inbox), this skill reads the live
  conversation, extracts only cross-session reusable knowledge points, dedups
  against existing permanent notes, and writes new permanent notes after explicit
  user review.
  Triggers on: "session to permanent", "提炼到永久笔记", "会话沉淀永久笔记",
  "把这次对话沉淀成永久笔记", "提炼会话知识", "distill session to permanent",
  "会话提炼", "沉淀永久笔记", "提炼永久笔记".
---

# JFox 会话沉淀永久笔记（session → permanent）

从当前会话里识别**跨会话可复用**的知识点，比对已有 permanent 笔记去重，提炼成新的 permanent 笔记。核心目的只有一个——把这次对话里「下次还会用到」的知识固化下来，一次性事务则不记。

## 和现有 skill 的区别

这三个 skill 容易混淆，先对齐定位：输入和产出不同，适用场景就不同。

| skill | 输入 | 产出 | 区别 |
|-------|------|------|------|
| `jfox-session-summary` | 当前会话 | session 笔记 | 完整存档整段对话，不提炼 |
| `jfox-organize` | inbox / fleeting 笔记 | permanent | 整理**已堆积**在收件箱的笔记 |
| `jfox-session-to-permanent`（本技能） | 当前会话 | permanent | 从**当前会话**直接提炼可复用知识，先比对已有 permanent 去重 |

一句话：session-summary 记「这次干了啥」，organize 整理「早就堆在那的笔记」，本技能沉淀「这次对话里值得长期保留的知识点」。

## 前置条件

- 知识库已初始化（`jfox init`）。未初始化时，提示用户先调用 `/skill:jfox-common` 创建。
- pi 平台默认写入**默认知识库**，下文命令一律不带 `--kb`（与原 #365 的去重需求一致）。如需写到别的知识库，按 `/skill:jfox-common` §4.1 的 `--kb` 约定显式指定。

> 本技能复用 `/skill:jfox-common` §4.1 的共享约定（`--kb` / `--json` / `--content-file`），下文示例统一使用 `--json` 简写。

## 五步流程

按顺序走：提取 → 去重 → 起草 → 审阅 → 落库。其中**去重**和**审阅**是两条硬约束，跳过任何一条都算违规。

### Step 1: 会话知识提取

回顾当前会话，挑出**跨会话可复用**的知识点，排除一次性的东西。这一步的判断标准是「下次还会不会用到」。

**值得提炼的**（跨会话可复用）：
- 概念理解（某个工具/机制的原理、术语解释）
- 工具用法（命令、参数、配置的通用用法）
- 配置坑 / 踩坑教训（为什么会出错、怎么修）
- 设计模式 / 最佳实践（通用方法论）
- 调试思路（排查某类问题的通用路径）

**要排除的**（一次性事务，不记）：
- 本次具体改了哪个文件的哪一行
- 针对当前项目的特定事实（端口号、临时路径、特定 issue 编号）
- 已经众所周知的常识
- 纯粹的操作确认（「跑起来了」「测试过了」）

把筛选结果列成候选清单给用户看一眼（这一步只是预告，草稿还没生成）：

```
候选知识点（N 条）：
1. [工具用法] jfox suggest-links 的阈值含义与误命中坑
2. [配置坑] ChromaDB 多进程并发会报 "Error finding id"，需 jfox index rebuild
3. [排除] 本次改了 cli.py 第 245 行 —— 一次性事务，不记
```

### Step 2: 强制去重（硬约束）

对每条候选知识点，**先查知识库里有没有**，没记录过的才进入起草。这一步防止重复造笔记——已有的就跳过或标记为「补充」。

每条候选跑两个命令，互补使用：

```bash
# 1. 关键词搜已有 permanent（找「讲同一件事」的笔记）
jfox search "<知识点关键词>" --type permanent --json

# 2. 语义找关联笔记（找「讲相关概念」的笔记，供起草时嵌入 wiki link）
jfox suggest-links "<知识点一句话摘要>" --json   # 阈值默认 ≥ 0.6
```

按搜出来的结果给每条候选分三类：

| 查询结果 | 判定 | 处置 |
|---------|------|------|
| 已有 permanent 完整覆盖该知识点 | **已覆盖** | 跳过，不重复造 |
| 已有 permanent 讲了相关主题，但这条是新增量 | **可补充** | 标记，起草时准备用 `jfox edit` 追加到那条已有笔记 |
| 没找到对应 permanent | **未记录** | 进入 Step 3 起草新笔记 |

> **别只信 `suggest-links`**：它既会按关键词误命中，也会漏掉语义相近的笔记（参见 `jfox-promote` §6 的已知坑）。关键词搜（`jfox search`）和语义搜（`suggest-links`）要一起看，拿不准时手动按概念补查一次。

### Step 3: 提炼 permanent 草稿

对「未记录」的候选起草新笔记，对「可补充」的候选准备追加内容。每条草稿都按下面的结构组织。

**一事实一笔记**：一条 permanent 笔记只讲一个知识点。如果一次会话有多个知识点，分别建多条，别塞进一条。

**内容结构**（事实 → Why → How to apply）：

```markdown
<一句话核心事实。开门见山，把这条笔记最重要的结论放第一句。>

## Why
<这个事实为什么成立、背景是什么。每段只讲一个子主题，段首给概要句。>

## How to apply
<什么场景下用、具体怎么操作。结合示例或命令。>
```

**写作规范（遵循 clear-reports 段落写作法）**：草稿正文要按下面五条规则写，目的是让读者用最少的力气看懂——permanent 笔记是写给未来的自己看的，清晰比简短更重要。

1. **先给结论，再展开**：第一句话就是核心事实，不要先铺背景。读者可能随时不读完，最重要的信息放最前面。
2. **每段一个主题，段首一句概要**：一段只讲一件事，第一句点明本段主题。理想效果是只扫每段第一句就能串起整篇逻辑。段落 4–8 句为宜，别两句一段也别一页一段。
3. **术语第一次出现，顺手解释一句**：你刚泡在某个概念里半小时（slug、grounding、cosine、MECE……），对未来的读者是生词。第一次出现带半句解释，第二次起可省。
4. **句子要完整，别过度缩写**：别丢主语丢动词丢助词（「阈值放宽到 0.4」「全良性」）。写完整句子，宁可多两个字。精简是删掉不重要的信息，不是把句子压成电报。
5. **表格是对比工具，不是结论的替代品**：表格适合放同类项横向对比，表上方必须有一句话总结你看完表想让读者记住的结论。逻辑主线永远用文字承载。

**嵌入 wiki links**：把 Step 2 查到的关联笔记用 `[[精确标题]]` 嵌进正文（wiki link 必须精确匹配目标笔记标题，短链会悬空——见 `jfox-promote` §6）。

### Step 4: 用户审阅（硬约束）

**严禁未经审阅直接 `jfox add`。** 把所有草稿完整展示给用户，等明确确认。这是本技能和 `jfox-session-summary`（直接写入）最大的区别——session 笔记是存档可以存完再改，permanent 是知识沉淀，落库前必须过眼。

展示格式（让用户一眼看到去重结论和草稿内容）：

```
本次拟沉淀 2 条 permanent：

【1】新笔记：jfox suggest-links 的阈值含义与误命中坑
去重：未记录（search 无命中；suggest-links 最近的相关笔记是 [[ChromaDB 索引重建]]）
草稿：
---
<完整草稿正文>
---

【2】补充到已有笔记：ChromaDB "Error finding id" 排查
去重：可补充（已有 [[ChromaDB 索引重建]]，本条补「多进程并发触发」这个新增量）
追加内容：
---
<要追加的段落>
---

请确认：全部写入 / 改某条 / 跳过某条？
```

### Step 5: 落库

用户确认后再执行写入。**新笔记**用 `jfox add`，**补充已有笔记**用 `jfox edit` 追加。

```bash
# 新笔记：内容含 [[wiki links]]，类型 permanent
jfox add "<包含 [[links]] 的草稿>" --title "<标题>" --type permanent \
  --tag <tag1> --tag <tag2> --json

# 长内容或含特殊字符，用 --content-file
cat > /tmp/note-draft.md << 'EOF'
<草稿正文>
EOF
jfox add --content-file /tmp/note-draft.md --title "<标题>" --type permanent \
  --tag <tag1> --json

# 补充已有笔记：把追加段落拼到原内容后，整体写回
jfox show <已有笔记_id> --json | jq -r .content > /tmp/existing.md
cat >> /tmp/existing.md << 'EOF'

<追加段落>
EOF
jfox edit <已有笔记_id> --content-file /tmp/existing.md
```

> 写入后的验证（`jfox show` / `jfox refs`）详见 `/skill:jfox-common` §4.5。落库后可以顺手 `jfox graph --stats --json` 看 avg_degree、isolated_nodes 是否健康（目标见 `jfox-organize` Step 3）。

## 命令参考

本技能专属命令（通用命令见 `/skill:jfox-common` §4）：

```bash
jfox search "<query>" --type permanent --json   # 关键词搜已有 permanent（去重）
jfox suggest-links "<摘要>" --json              # 语义找关联笔记（去重 + 补链，阈值 ≥ 0.6）
jfox add ... --type permanent                   # 写入新 permanent 笔记
jfox edit <id> --content-file <path>            # 追加内容到已有 permanent 笔记
jfox graph --stats --json                        # 落库后看图谱健康度
```

## 错误处理

- **会话里没有可复用知识**（全是一次性事务）→ 告知用户「本次会话无可沉淀的跨会话知识」，不强行造笔记。
- **`jfox search` / `suggest-links` 因 daemon 未启动而失败** → 提示用户启动 daemon（见 `/skill:jfox-common` §6），或先用 `jfox search` 关键词模式（不依赖 embedding）。
- **草稿被用户全部否决** → 不写入任何内容，记录用户反馈后结束。
- **`suggest-links` 返回低匹配度**（score < 0.6）→ 不强制补链，但 `jfox search` 命中或手动判断相关的仍可嵌入。

## 关键约束

- **去重是硬约束**：起草前必须先 `jfox search --type permanent` 查已有，已覆盖的跳过、可补充的标记。不查就写等于重复造笔记。
- **审阅是硬约束**：所有草稿必须完整展示给用户确认后才能落库，严禁直接 `jfox add`。
- **一事实一笔记**：一条 permanent 只讲一个知识点，多个知识点分多条写。
- **wiki link 精确标题**：`[[xxx]]` 必须精确匹配目标笔记标题，短链会悬空。
- **默认知识库**：pi 平台默认不带 `--kb`，写入默认知识库；显式指定时用 `/skill:jfox-common` §4.1 的约定。
