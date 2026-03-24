---
name: knowledge-base-workspace
description: |
  管理 Zettelkasten 知识库工作空间。在对话中维护当前知识库上下文。
  
  触发场景：
  - "有哪些知识库", "列出知识库", "查看所有知识库"
  - "切换到 xxx 知识库", "使用 xxx 库", "去 xxx 库"
  - "创建知识库", "新建一个叫 xxx 的知识库"
  - "删除 xxx 知识库", "移除知识库"
  - "知识库状态", "查看状态", "知识库情况"
  - "今天的笔记", "查看收件箱", "最近有什么笔记"
  
  重要：本 Skill 在对话中记住当前知识库，不使用全局默认配置。
---

# Knowledge Base Workspace

管理你的知识库工作空间。在对话中维护当前知识库，所有操作都显式指定 `--kb`。

## 核心设计原则

### 1. 会话级上下文（对话记忆）

在对话中记住当前知识库，不写入文件：

```
用户: "切换到 work 知识库"
→ 记住: current_kb = "work"
→ 后续操作自动使用 work

用户: "切换到 personal"
→ 更新: current_kb = "personal"
→ 后续操作自动使用 personal
```

### 2. 显式 --kb 参数

每个 CLI 命令都必须带上 `--kb` 参数：

```bash
# ✅ 正确
zk status --kb work --format json

# ❌ 错误（依赖全局默认，多实例会冲突）
zk status --format json
```

### 3. 不使用 zk kb switch

避免修改全局默认配置，只更新对话中的记忆。

## 工作流程

### 标准流程

```python
# 在对话中维护的上下文
current_kb = None  # 当前选中的知识库

def execute(user_input):
    # 1. 识别意图
    intent = recognize(user_input)
    
    # 2. 确定知识库
    kb = extract_kb(user_input) or current_kb
    
    # 3. 执行命令（必须带 --kb）
    result = run(f"zk {command} --kb {kb} --format json")
    
    # 4. 如果是切换操作，更新记忆
    if intent == "kb_switch":
        current_kb = kb
    
    # 5. 返回结果
    return format_response(result)
```

## Available Tools

### kb_list
列出所有知识库

**触发**: "有哪些知识库"

**CLI**:
```bash
zk kb list --format json
```

**返回示例**:
```json
{
  "current": "default",
  "knowledge_bases": [
    {"name": "default", "path": "~/.zettelkasten", "total_notes": 10, "is_current": true},
    {"name": "work", "path": "~/.zettelkasten-work", "total_notes": 25}
  ]
}
```

---

### kb_switch
切换到指定知识库（只更新对话记忆）

**触发**: "切换到 work", "使用 personal 库"

**实现**:
```python
def kb_switch(name):
    # 验证存在
    result = run("zk kb list --format json")
    kbs = json.loads(result)
    
    if name not in [kb["name"] for kb in kbs["knowledge_bases"]]:
        return error(f"知识库 {name} 不存在")
    
    # 更新对话记忆（关键：不调用 zk kb switch）
    current_kb = name
    
    return success(f"已切换到 {name}，后续操作将使用此知识库")
```

---

### kb_create
创建新知诖库

**触发**: "创建知识库", "新建一个叫 study 的库"

**CLI**:
```bash
zk init --name <name> [--path <path>] [--desc <description>]
```

---

### kb_remove
删除知识库

**触发**: "删除知识库"

**CLI**:
```bash
zk kb remove <name> --force
```

---

### kb_status
查看知识库状态

**触发**: "知识库状态", "查看状态"

**CLI**:
```bash
zk status --kb {current_kb} --format json
```

---

### kb_daily_notes
查看某天笔记（默认今天）

**触发**: "今天的笔记", "昨天的笔记", "查看某天的笔记"

**CLI**:
```bash
zk daily --kb {current_kb} [--date YYYY-MM-DD]
```

---

### kb_inbox
查看临时笔记

**触发**: "查看收件箱", "最近的临时笔记"

**CLI**:
```bash
zk inbox --kb {current_kb} [--limit N]
```

---

### note_list
列出笔记

**触发**: "列出笔记", "最近的笔记", "查看笔记列表"

**CLI**:
```bash
zk list --kb {current_kb} [--limit N] [--type TYPE] --format json
```

## 响应模板

### 切换成功
```
✅ 已切换到 {name} 知识库

后续操作将默认使用此知识库：
- 添加笔记
- 搜索内容  
- 查看状态

可用命令：
- "记录一个想法..."
- "搜索 xxx"
- "查看状态"
```

### 知识库列表
```
您的知识库 ({count} 个):

⭐ {current} (当前) - {path}
   笔记: {total} | F/L/P: {fleeting}/{literature}/{permanent}

   {name2} - {path2}
   笔记: {total2}

💡 使用 "切换到 {name}" 切换知识库
```

## 多实例说明

多个 Kimi Code 实例同时使用时：
- 每个实例有自己的对话记忆（current_kb）
- 互不干扰，不会冲突
- 每个命令都显式 `--kb`，不依赖全局默认

## Windows 注意事项

1. UTF-8 编码：`chcp 65001`
2. 验证安装：`where zk`
3. 表格乱码改用 JSON：`--format json`

## 参考

详细 CLI 命令参考：[references/commands.md](references/commands.md)
