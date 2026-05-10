# Session Note Type Design

**Date**: 2026-05-09
**Issue**: #202
**Status**: Approved

## 概述

新增 `session` 笔记类型，专门存储 AI Agent 会话记录（编码会话总结、CR 修复记录、debug 过程等）。

## 笔记类型对照

| 类型 | 语义 | 文件名格式 | 目录 |
|------|------|-----------|------|
| `fleeting` | 闪念笔记，快速捕获 | `YYYYMMDD-HHMMSSNNNN.md` | `notes/fleeting/` |
| `literature` | 文献笔记，阅读摘要 | `{id}-{slug}.md` | `notes/literature/` |
| `permanent` | 永久笔记，加工后知识 | `{id}-{slug}.md` | `notes/permanent/` |
| `session` | AI Agent 会话记录 | `{id}-{topic}.md` | `notes/session/` |

Session 的 ID 生成逻辑与其他类型一致（18 位 `YYYYMMDDHHMMSSNNNN`），文件名中的 topic 通过 `--topic` 参数传入。

## 改动清单

### 1. `NoteType` 枚举 — `models.py`

新增 `SESSION = "session"` 枚举值。

### 2. `Note` 模型 — `models.py`

新增 `topic: Optional[str] = None` 字段，持久化到 YAML frontmatter。`filename` 属性无需修改——session 走 else 分支（带 slug），topic 作为 slug 使用。

### 3. 目录创建 — `config.py`

`ensure_dirs()` 新增 `self.notes_dir / "session"` 目录。

### 4. `--topic` 参数 — `cli.py`

- `jfox add` 命令新增 `--topic` 可选参数
- 当 `--type session` 时 `--topic` 必填，否则报错
- 其他类型忽略 `--topic`
- Topic 存入 frontmatter 的 `topic` 字段
- Topic 同时用于文件名生成（通过 title slug 逻辑复用，或用 topic 替代 slug）

**title 与 topic 的关系**：`--title` 和 `--topic` 独立传入。title 用于 frontmatter 和搜索显示，topic 用于文件名生成。例如 `--title "Session: fix atomic write" --topic atomic-write` 产生文件名 `{id}-atomic-write.md`。

**文件名生成策略**：session 的 `filename` 属性优先用 `topic`（slugified），无 topic 时回退到 `title`：

```python
if self.type == NoteType.SESSION:
    source = self.topic or self.title
    slug = re.sub(r"[^\w\-]", "", source.lower().replace(" ", "-"))[:50]
    return f"{self.id}-{slug}.md"
```

`jfox-session-summary` skill 调用时会同时传 `--title` 和 `--topic`，确保文件名用 topic，显示用 title。

### 5. 内置 `session` 模板 — `template.py`

在 `BUILTIN_TEMPLATES` 中新增：

```yaml
name: session
description: AI Agent 会话记录
note_type: session
title_format: "{{date}}-{{time}}-{{topic}}"
content: |
  ## 背景
  <!-- 本次会话的起因/上下文 -->

  ## 完成的工作
  <!-- 本轮会话做了什么 -->

  ## 我的决策
  <!-- AI Agent 做出的决策 -->

  | 决策 | 状态 | 说明 |
  |------|------|------|
  |      | 采纳 |      |
  |      | 否决 |      |

  采纳率：采纳 X/N，否决 Y/N

  ## 耶稣决策
  <!-- 外部输入的高权重决策，必须以此为准 -->

  ## 意外收获
  <!-- 会话中发现的非当前问题的问题 -->

  | 发现 | 是否有跟进 | 跟进方式 |
  |------|-----------|----------|
  |      | 是/否     | issue / 项目管理 |

  ## 待办
  <!-- 后续需要处理的事项 -->
  - [ ]
tags:
  - session
```

### 6. `inbox` 命令 — `cli.py`

`_inbox_impl` 中将 `list_meta(note_type=NoteType.FLEETING)` 改为同时查询 fleeting + session 类型。

### 7. 查找逻辑 — `note.py`

无需修改。`find_note_by_id` 用 `{id}*.md` glob 已能匹配 `{id}-{topic}.md` 格式。

### 8. `jfox-session-summary` skill

两个版本（claude-code / kimi-cli）的 SKILL.md 更新：
- 默认 `--type session`
- 新增 `--topic` 参数传递
- 类型选择步骤中新增 session 选项并推荐为默认

### 9. `--type` 参数校验

所有接受 `--type` 的命令（add、search、list、edit、ingest-log、bulk-import、template create）自动支持 `session`，因为校验逻辑使用 `NoteType(note_type.lower())` 枚举转换。只需更新错误提示文案：

```
Invalid note type: xxx. Use: fleeting, literature, permanent, session
```

### 10. `template_cli.py` 校验

`create` 命令中的 note_type 校验白名单加入 `"session"`。

## 不做的事

- 不做 `jfox session` 子命令
- 不做自动迁移旧 fleeting session 笔记
- 不改 ID 生成逻辑
- 不改 `list_notes` / `search` 等通用查询（遍历 `NoteType` 的地方自动生效）

## 兼容性

- 已有的 fleeting 类型笔记不受影响
- 新知识库自动创建 `notes/session/` 目录
- 旧知识库首次使用 `--type session` 时自动创建目录（`ensure_dirs` 或写入时创建）
