---
name: jfox-template
description: |
  Use when user wants to manage JFox note templates, create/edit/delete custom templates,
  or use templates to standardize note creation. Triggers on "模板管理", "创建模板",
  "编辑模板", "删除模板", "使用模板", "template", "templates", "meeting template",
  "literature template", "permanent template", "session template", "jfox template",
  "笔记模板".
---

# JFox 模板管理

管理笔记模板，让重复类型的笔记（会议、阅读、永久笔记、AI 会话）保持统一结构。

模板存储在当前知识库的 `.zk/templates/` 目录下，分为：
- **内置模板**（built-in）：`quick`、`meeting`、`literature`、`session`，不可修改或删除
- **自定义模板**：用户自行创建，可编辑、删除

## 前置条件

确认 jfox 已安装并初始化知识库：

```bash
jfox --version
jfox kb current --json
```

如果还没有知识库，先调用 `/skill:jfox-manage` 创建。

> 本技能复用 `/skill:jfox-manage` §4.1 的共享约定（`--kb` / `--json` / `--content-file`），下文示例统一使用 `--json` 简写。

## 1. 查看模板

### 列出所有模板

```bash
jfox template list --json
```

输出包含内置模板与自定义模板，字段包括 `name`、`description`、`note_type`。

### 查看单个模板

```bash
jfox template show <name> --json
```

示例：

```bash
jfox template show meeting --json
jfox template show literature --json
```

输出包含模板内容、`title_format`、默认 `tags` 等，便于在创建笔记前确认占位符。

## 2. 创建模板

```bash
jfox template create <name> \
  --description "模板描述" \
  --type <fleeting|literature|permanent|session> \
  --title-format "{{date}}-{{title}}" \
  --tag <tag1> --tag <tag2> \
  --content "模板内容，支持 {{variable}} 占位符"
```

如果省略 `--description`、`--content` 等字段，CLI 会进入交互式提示。

示例：

```bash
jfox template create permanent \
  --description "永久笔记模板" \
  --type permanent \
  --title-format "{{title}}" \
  --tag permanent \
  --content "## 核心观点\n\n## 论证与证据\n\n## 关联笔记\n\n{{content}}"
```

### 长内容编辑建议

`jfox template create` 的 `--content` 适合中等长度内容。如果模板内容很长，推荐：

1. 先创建模板骨架：
   ```bash
   jfox template create my-template --description "我的模板" --type permanent
   ```
2. 使用系统编辑器补充完整内容：
   ```bash
   jfox template edit my-template
   ```

## 3. 编辑模板

```bash
jfox template edit <name>
```

调用系统默认编辑器（`$EDITOR`，Windows 上默认 `notepad`）打开模板 YAML 文件。

> 只能编辑自定义模板；内置模板会报错，如需调整请先 `jfox template create <新名称>` 复制一份。

## 4. 删除模板

```bash
jfox template remove <name> --yes
```

> 只能删除自定义模板；内置模板不可删除。

## 5. 使用模板创建笔记

在 `jfox add` 中通过 `--template <name>` 调用模板：

```bash
jfox add "<内容>" --title "<标题>" --template <name>
```

模板会自动渲染 `title`、`content`、`note_type` 和 `tags`。渲染时会注入以下变量：

| 变量 | 来源 |
|------|------|
| `{{title}}` | `--title` 参数 |
| `{{content}}` | `add` 命令的内容参数 |
| `{{source}}` | `--source` 参数 |
| `{{topic}}` | `--topic` 参数（session 类型） |
| `{{date}}` | 当前日期 `YYYY-MM-DD` |
| `{{time}}` | 当前时间 `HH:MM` |
| `{{datetime}}` | 当前日期时间 `YYYY-MM-DD HH:MM` |

### 常用模板示例

#### 会议记录（meeting）

```bash
jfox add "确认了 Q3 目标拆解" \
  --title "周会记录" \
  --template meeting
```

`meeting` 模板默认生成 permanent 笔记，并带有 `meeting`、`permanent` 标签。

#### 阅读笔记（literature）

```bash
jfox add "来源：How to Take Smart Notes" \
  --title "卡片盒笔记法" \
  --template literature
```

#### 永久笔记（permanent）

如果已按 §2 创建了 `permanent` 自定义模板：

```bash
jfox add "原子化笔记应只包含一个核心观点" \
  --title "原子笔记原则" \
  --template permanent
```

> 笔记的通用 CRUD、标签与链接管理详见 `/skill:jfox-manage` §4。

## 6. 命令参考速查

```bash
jfox template list --json                         # 列出模板
jfox template show <name> --json                  # 查看模板
jfox template create <name> --description "..." --type <type> --content "..."   # 创建
jfox template edit <name>                         # 编辑模板
jfox template remove <name> --yes                 # 删除模板

jfox add "<内容>" --title "<标题>" --template <name>   # 使用模板创建笔记
```

## 7. 错误处理

| 场景 | 处理方式 |
|------|---------|
| `Template '<name>' not found` | 使用 `jfox template list --json` 查看可用模板名称 |
| `Cannot edit built-in template` | 内置模板不可编辑，可 `jfox template create <新名>` 复制后修改 |
| `Cannot remove built-in template` | 内置模板不可删除 |
| 模板渲染失败 | 检查模板中使用的变量名是否正确，可用变量见 §5 |
| 没有知识库 | 调用 `/skill:jfox-manage` 初始化知识库 |

## 使用建议

- **会议/阅读/会话类型**优先使用对应内置模板，保持结构一致
- **永久笔记**建议创建符合自己思维框架的自定义模板
- 模板 `title_format` 支持 Jinja2 语法，可组合多个变量，例如 `{{date}}-{{time}}-{{title}}`
- 在批量导入或定期整理前，统一模板可显著降低后续整理成本
