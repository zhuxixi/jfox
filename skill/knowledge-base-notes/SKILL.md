---
name: knowledge-base-notes
description: |
  管理 Zettelkasten 笔记的全生命周期。
  
  触发场景：
  - "记录一个想法", "帮我记个笔记", "添加笔记", "记一下..."
  - "搜索 xxx", "找一下笔记", "笔记里有..."
  - "删除笔记", "删掉这个笔记"
  - "查看引用", "这个笔记被哪些引用", "引用关系"
  - "推荐链接", "这个内容和哪些相关"
  - "深度搜索", "语义+图谱搜索"
  - "知识图谱", "孤立笔记", "图谱统计"
  - "用 meeting 模板", "创建会议记录", "用 literature 模板"
  
  依赖：需要知道目标知识库（从上下文获取或询问用户）。
---

# Knowledge Base Notes

管理笔记的全生命周期。需要目标知识库，从对话上下文中获取或询问用户。

## 核心设计原则

### 1. 依赖目标知识库

每个操作都需要 `--kb` 参数：

```python
def execute(user_input):
    # 1. 提取知识库（从用户输入或上下文）
    kb = extract_kb(user_input) or get_context_kb() or ask_user()
    
    # 2. 执行命令（必须带 --kb）
    result = run(f"zk {command} --kb {kb} --format json")
    
    return format_response(result)
```

### 2. 支持显式指定

用户可以在输入中指定知识库：

```
"在 work 库中搜索 Python" → --kb work
"personal 库添加笔记" → --kb personal
```

### 3. 回退到询问

如果不确定知识库，主动询问：

```
"您想在哪个知识库操作？"
1. work (当前上下文)
2. personal
3. default
```

## Available Tools

### add
添加笔记

**触发**: "记录一个想法", "添加笔记"

**参数**:
- content (required): 内容
- kb (required): 知识库
- title (optional): 标题
- note_type (optional): fleeting/literature/permanent
- tags (optional): 标签列表

**CLI**:
```bash
zk add "{content}" --kb {kb} [--title "{title}"] [--type {type}] [--tag {tag}] --format json
```

---

### add (with template)
使用模板创建笔记

**触发**: "用 meeting 模板", "创建会议记录"

**参数**:
- content (required): 内容
- template (required): quick/meeting/literature
- kb (required): 知识库
- title (optional): 标题

**CLI**:
```bash
zk add "{content}" --kb {kb} --template {template} [--title "{title}"] --format json
```

---

### search
搜索笔记

**触发**: "搜索", "找一下"

**参数**:
- query (required): 关键词
- kb (required): 知识库
- top_k (optional): 数量，默认 5
- search_mode (optional): hybrid/semantic/keyword，默认 hybrid

**CLI**:
```bash
zk search "{query}" --kb {kb} --format json [--top {n}] [--mode {mode}]
```

---

### query
深度搜索（语义+图谱）

**触发**: "深度搜索", "查找关联内容"

**参数**:
- query (required): 关键词
- kb (required): 知识库
- top_k (optional): 默认 5
- graph_depth (optional): 图谱深度，默认 2

**CLI**:
```bash
zk query "{query}" --kb {kb} --format json [--top {n}] [--depth {d}]
```

---

### delete
删除笔记

**触发**: "删除笔记"

**参数**:
- note_id (required): 笔记 ID
- kb (required): 知识库
- force (optional): 强制删除

**CLI**:
```bash
zk delete {note_id} --kb {kb} [--force]
```

---

### refs
查看引用关系

**触发**: "查看引用", "被哪些笔记引用"

**参数**:
- note_id (required): 笔记 ID
- kb (required): 知识库

**CLI**:
```bash
zk refs --kb {kb} --note {note_id} --format json
```

---

### suggest-links
推荐相关笔记

**触发**: "推荐链接", "和哪些笔记相关"

**参数**:
- content (required): 内容文本
- kb (required): 知识库
- top_k (optional): 默认 5
- threshold (optional): 阈值 0-1，默认 0.6

**CLI**:
```bash
zk suggest-links "{content}" --kb {kb} --format json [--top {n}] [--threshold {t}]
```

---

### graph
知识图谱分析

**触发**: "知识图谱", "孤立笔记", "图谱统计"

**模式**:
- `--stats`: 统计信息
- `--orphans`: 孤立笔记
- `--note {id}`: 特定笔记的关联

**CLI**:
```bash
zk graph --kb {kb} --format json [--stats | --orphans | --note {id}]
```

---

### template list
列出可用模板

**触发**: "有哪些模板", "可用模板"

**CLI**:
```bash
zk template list --kb {kb} --format json
```

## 响应模板

### 创建成功
```
✅ 笔记已创建
   知识库: {kb}
   标题: {title}
   类型: {type}
   ID: {id}
   路径: {filepath}
```

### 搜索结果
```
🔍 找到 {count} 条相关笔记：

{rank}. [{score}] {title}
   类型: {type}
   {preview}

💡 使用 "zk show {id}" 查看完整内容
```

### 推荐链接
```
💡 推荐链接（相似度 > {threshold}）:

{rank}. [{score}] {title}
   匹配类型: {match_type}
   
使用 "zk add '... [[{title}]] ...'" 添加链接
```

## 与 Workspace Skill 协作

```
用户: "切换到 work 知识库"
→ Workspace Skill
→ 记住: current_kb = "work"

用户: "记录一个想法：AI 发展很快"
→ Notes Skill
→ 获取 kb = "work"（从上下文）
→ 执行: zk add "AI 发展很快" --kb work --format json

用户: "搜索 Python"
→ Notes Skill
→ 获取 kb = "work"
→ 执行: zk search "Python" --kb work --format json

用户: "查看引用"
→ Notes Skill
→ 执行: zk refs --kb work --format json

用户: "推荐相关笔记"
→ Notes Skill
→ 执行: zk suggest-links "内容" --kb work --format json

用户: "知识图谱统计"
→ Notes Skill
→ 执行: zk graph --kb work --stats --format json
```

## 参考

详细 CLI 命令参考：[references/commands.md](references/commands.md)
