---
name: knowledge-base
description: |
  自然语言管理 Zettelkasten 知识库。当用户想要：
  - 记录想法、笔记（"记录...", "帮我记...", "添加笔记"）
  - 在指定知识库操作（"在工作库...", "切换到...知识库"）
  - 管理知识库（"有哪些知识库", "创建...知识库"）
  - 搜索笔记（"搜索...", "找一下..."）
  - 使用模板（"用...模板", "创建会议记录"）
  - 查看状态（"查看知识库状态", "知识库情况"）
  
  始终先确认目标知识库，再执行操作。自动维护会话级知识库上下文。
---

# Knowledge Base Skill

使用自然语言与 Zettelkasten 知识库交互，无需记忆 CLI 命令。

## Core Principle

**知识库优先**：任何操作前，先确定目标知识库。

### 上下文管理

维护会话级上下文：

```python
kb_context = {
    "current_kb": None,      # 当前使用的知识库名称
    "default_kb": None,      # 系统默认知识库
    "available_kbs": [],     # 可用知识库列表
}
```

### 知识库选择优先级

1. **用户明确指定**（"在工作库..." / "--kb work"）
2. **当前会话上下文**（上次使用的知识库）
3. **系统默认知识库**（default）
4. **询问用户选择**（当以上都无效时）

---

## When to Use

### 触发场景

| 场景 | 示例短语 |
|------|---------|
| **知识库管理** | "有哪些知识库", "切换到工作库", "创建新知识库" |
| **快速记录** | "记录一个想法", "帮我记个笔记", "添加笔记" |
| **模板创建** | "用 meeting 模板", "创建会议记录", "写个阅读笔记" |
| **搜索查找** | "搜索 Python", "找一下之前的笔记", "笔记里有..." |
| **查看状态** | "知识库状态", "查看笔记列表", "最近写了什么" |

---

## Intent Recognition

### 1. 识别知识库操作意图

**匹配模式：**
- "有哪些知识库" / "知识库列表" → `kb_list`
- "切换到...知识库" / "使用...知识库" → `kb_switch`
- "创建...知识库" / "新建知识库" → `kb_create`
- "删除...知识库" / "移除知识库" → `kb_remove`

**提取知识库名称：**
```python
patterns = [
    r"(?:在|切换到|使用|去)\s*(\w+)\s*(?:知识库|库)?",
    r"--kb\s+(\w+)",
]
```

### 2. 识别笔记操作意图

**匹配模式：**
- "记录..." / "添加..." / "帮我记..." / "记一下..." → `note_add`
- "搜索..." / "查找..." / "找一下..." / "笔记里有..." → `note_search`
- "用...模板" / "使用...模板" → `note_add_template`
- "状态" / "情况" / "统计" → `kb_status`
- "列出..." / "查看..." / "显示..." → `note_list`

---

## Command Mapping

### 知识库管理命令

| 意图 | CLI 命令 | 参数 |
|------|---------|------|
| `kb_list` | `zk kb list` | - |
| `kb_switch` | `zk kb use <name>` | name: 知识库名称 |
| `kb_create` | `zk init --name <name>` | name, path?, desc? |
| `kb_remove` | `zk kb remove <name>` | name, --yes? |
| `kb_status` | `zk status` | --kb? |

### 笔记操作命令

| 意图 | CLI 命令 | 参数 |
|------|---------|------|
| `note_add` | `zk add <content>` | content, --title?, --type?, --tag?, --kb? |
| `note_add_template` | `zk add --template <name> <content>` | template, content, --title?, --kb? |
| `note_search` | `zk search <query>` | query, --top?, --kb? |
| `note_list` | `zk list` | --limit?, --type?, --kb? |
| `template_list` | `zk template list` | --kb? |

---

## Execution Flow

### 标准执行流程

```python
def execute(user_input):
    # Step 1: 识别意图
    intent = recognize_intent(user_input)
    
    # Step 2: 提取参数
    params = extract_params(user_input, intent)
    
    # Step 3: 确定知识库
    kb = resolve_knowledge_base(intent, params)
    if not kb:
        kb = prompt_kb_selection()
    
    # Step 4: 构建命令
    cmd = build_command(intent, params, kb)
    
    # Step 5: 执行
    result = run_cli(cmd)
    
    # Step 6: 更新上下文
    update_context(kb, intent)
    
    # Step 7: 格式化输出
    return format_response(result, intent)
```

### 知识库解析逻辑

```python
def resolve_knowledge_base(intent, params):
    # 1. 检查参数中是否有 --kb
    if "kb" in params:
        return params["kb"]
    
    # 2. 检查当前会话上下文
    if kb_context["current_kb"]:
        return kb_context["current_kb"]
    
    # 3. 使用系统默认
    if kb_context["default_kb"]:
        return kb_context["default_kb"]
    
    # 4. 无法确定，需要询问
    return None
```

---

## Parameter Extraction

### 从自然语言提取参数

**记录笔记：**
```
"记录一个想法：AI 发展很快，标题是 AI 观察，标签是 tech"
→ {
    "content": "AI 发展很快",
    "title": "AI 观察",
    "tags": ["tech"]
}
```

**搜索笔记：**
```
"搜索 Python，找前 10 条"
→ {
    "query": "Python",
    "top": 10
}
```

**使用模板：**
```
"用 meeting 模板记录周会，关于产品评审"
→ {
    "template": "meeting",
    "content": "关于产品评审",
    "title": "周会"
}
```

---

## Response Format

### 成功响应模板

**创建笔记：**
```
✅ 笔记已创建
   知识库: {kb_name}
   标题: {title}
   类型: {note_type}
   ID: {note_id}
   路径: {filepath}
```

**搜索笔记：**
```
🔍 找到 {count} 条相关笔记：

{rank}. [{score}] {title}
   类型: {type} | 创建于: {date}
   {preview}

💡 提示: 使用 "zk show {id}" 查看完整内容
```

**知识库列表：**
```
您的知识库 ({count} 个):

{current_marker} {name} - {path}
   笔记: {note_count} | 类型分布: {type_counts}

💡 使用 "切换到 {name}" 切换默认知识库
```

### 需要确认的场景

**删除知识库：**
```
⚠️  即将删除知识库: {name}
   路径: {path}
   此操作不可恢复！

确认删除? (yes/no):
```

**选择知识库（当不明确时）：**
```
未指定知识库。可用选项:

1. {name1} (默认) - {note_count} 条笔记
2. {name2} - {note_count} 条笔记

请选择 (1/2/名称)，或输入 "新建" 创建:
```

---

## Examples

### Example 1: 首次使用，自动引导

**User:** 记录一个想法

**Claude:**
```
您当前没有默认知识库。可用的知识库:

1. default (~/zettelkasten) - 10 条笔记
2. work (~/work-notes) - 25 条笔记

请选择 (1/2/名称):
```

**User:** 2

**Claude:**
```
✅ 已选择 work 知识库，后续操作将默认使用此库。

请输入要记录的内容:
```

**User:** AI 的发展速度超出预期

**Claude:**
```
✅ 笔记已创建
   知识库: work
   标题: 2026-03-24-快速想法
   类型: fleeting
   ID: 20260324010123
```

---

### Example 2: 明确指定知识库

**User:** 在个人库中搜索 Python 笔记

**Claude:**
```
🔍 在 personal 知识库搜索 "Python"

找到 3 条相关笔记:

1. [0.92] Python 装饰器详解
   类型: permanent | 创建于: 2026-03-20
   Python 装饰器是一种强大的语法糖...

2. [0.85] Python 异步编程指南
   类型: literature | 创建于: 2026-03-18
   异步编程是 Python 中处理并发...

3. [0.78] 学习 Python 的心得体会
   类型: fleeting | 创建于: 2026-03-15
   今天学习了 Python 的列表推导式...

💡 提示: 使用 "zk show <id>" 查看完整内容
```

---

### Example 3: 使用模板

**User:** 用 meeting 模板创建一个关于产品评审的会议记录

**Claude:**
```
📝 使用 meeting 模板创建笔记

请输入会议内容 (支持 [[笔记标题]] 链接):
```

**User:** 讨论了 Q2 产品路线图，确定了优先级

**Claude:**
```
✅ 会议记录已创建
   知识库: work (当前默认)
   标题: 2026-03-24-产品评审
   类型: permanent
   ID: 20260324010234
   
📋 模板包含以下章节:
   - 会议信息 (日期: 2026-03-24, 时间: 14:30)
   - 参会人员
   - 议程
   - 会议内容
   - 行动项
   
您可以使用编辑器打开补充详细信息。
```

---

### Example 4: 管理知识库

**User:** 有哪些知识库？

**Claude:**
```
您的知识库 (3 个):

⭐ default - ~/zettelkasten
   笔记: 10 | 类型: fleeting(5), permanent(3), literature(2)

   work - ~/work-notes
   笔记: 25 | 类型: fleeting(10), permanent(12), literature(3)

   personal - ~/personal-notes
   笔记: 42 | 类型: fleeting(20), permanent(15), literature(7)

💡 使用 "切换到 {name}" 切换默认知识库
```

**User:** 切换到 personal

**Claude:**
```
✅ 已切换默认知识库为 personal
   路径: ~/personal-notes
   笔记数量: 42
   
后续操作将默认使用此知识库。
```

---

### Example 5: 连续操作（上下文保持）

**User:** 记录一个想法：Rust 的所有权机制很有意思

**Claude:**
```
✅ 笔记已创建
   知识库: personal (当前默认)
   标题: 2026-03-24-快速想法
   类型: fleeting
   ID: 20260324010345
```

**User:** 再记录一个

**Claude:**
```
📝 在 personal 知识库创建笔记

请输入内容:
```

**User:** 今天学习了生命周期

**Claude:**
```
✅ 笔记已创建
   知识库: personal
   标题: 2026-03-24-快速想法-2
   类型: fleeting
   ID: 20260324010346
```

---

## Error Handling

### 常见错误及响应

**知识库不存在：**
```
❌ 知识库 "xyz" 不存在

可用知识库: default, work, personal

请重新输入或使用 "zk kb list" 查看所有知识库。
```

**模板不存在：**
```
❌ 模板 "weekly" 不存在

可用模板:
  • quick - 快速记录想法
  • meeting - 会议记录模板
  • literature - 阅读笔记模板

使用 "zk template list" 查看所有模板。
```

**缺少必填参数：**
```
❌ 缺少笔记内容

请提供要记录的内容，例如:
  "记录一个想法：这里写内容"
  "添加笔记 --title 标题 内容"
```

---

## Best Practices

1. **主动确认知识库**：当上下文不明确时，主动询问而非假设
2. **记住用户选择**：一次选择后，后续操作默认使用
3. **提供快捷方式**：支持 "再记录一个" 等上下文延续表达
4. **友好的错误提示**：不仅报错，还要告诉用户正确的用法
5. **展示关键信息**：创建成功后显示 ID 和路径，方便后续操作
