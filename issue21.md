## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

Obsidian CLI 提供模板系统，允许用户快速创建标准化的笔记（会议记录、读书笔记、项目计划等）。

当前 ZK CLI 创建笔记时需要手动指定所有元数据，不够便捷。

## 目标

添加模板系统，支持预定义的笔记模板，快速创建标准化笔记。

## 模板设计

### 模板存储位置

```
~/.zettelkasten/.zk/templates/
├── meeting.yaml      # 会议记录模板
├── literature.yaml   # 文献笔记模板
├── project.yaml      # 项目计划模板
└── daily.yaml        # 每日笔记模板
```

### 模板格式

```yaml
# meeting.yaml
name: meeting
description: 会议记录模板
type: fleeting
title_format: "会议记录 - {{date}}"
content: |
  ## 参与人员
  - 
  
  ## 议题
  1. 
  
  ## 讨论要点
  
  
  ## 行动项
  - [ ] 
  
  ## 下次会议
  
tags:
  - meeting
  - work
```

```yaml
# literature.yaml
name: literature
description: 文献阅读笔记
type: literature
title_format: "文献 - {{title}}"
content: |
  ## 来源
  - 标题: {{source_title}}
  - 作者: {{author}}
  - URL: {{url}}
  - 阅读日期: {{date}}
  
  ## 核心观点
  
  
  ## 我的思考
  
  
  ## 关联笔记
  - 
tags:
  - literature
```

### 变量支持

| 变量 | 说明 | 示例 |
|------|------|------|
| `{{date}}` | 当前日期 | 2026-03-22 |
| `{{time}}` | 当前时间 | 14:30 |
| `{{datetime}}` | 完整时间 | 2026-03-22 14:30 |
| `{{title}}` | 用户输入的标题 | - |
| `{{source_title}}` | 来源标题 | - |
| `{{author}}` | 作者 | - |
| `{{url}}` | URL | - |

## CLI 接口

### 管理模板

```bash
# 列出模板
zk template list

# 查看模板
zk template show meeting

# 创建模板（交互式）
zk template create meeting

# 编辑模板
zk template edit meeting

# 删除模板
zk template remove meeting
```

### 使用模板创建笔记

```bash
# 使用模板创建笔记
zk add --template meeting "与产品团队讨论 v2.0 规划"

# 交互式填充变量
zk add --template literature --interactive

# 直接指定变量
zk add --template literature \
    --var title="Zettelkasten 方法" \
    --var author="Sönke Ahrens" \
    --var url="https://..."
```

## 内置模板

默认提供以下模板：

| 模板 | 用途 | 类型 |
|------|------|------|
| `quick` | 快速记录 | fleeting |
| `meeting` | 会议记录 | fleeting |
| `literature` | 文献笔记 | literature |
| `idea` | 想法记录 | fleeting |
| `daily` | 每日笔记 | permanent |

## 实现方案

```python
# zk/template.py
from pathlib import Path
from typing import Dict, Any
import yaml
from jinja2 import Template

class TemplateManager:
    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
    
    def list_templates(self) -> List[TemplateInfo]:
        """列出所有模板"""
        pass
    
    def load_template(self, name: str) -> Template:
        """加载模板"""
        template_file = self.templates_dir / f"{name}.yaml"
        with open(template_file) as f:
            return yaml.safe_load(f)
    
    def render(self, name: str, variables: Dict[str, Any]) -> NoteContent:
        """渲染模板"""
        template = self.load_template(name)
        
        # 合并默认变量
        variables.setdefault('date', datetime.now().strftime('%Y-%m-%d'))
        variables.setdefault('time', datetime.now().strftime('%H:%M'))
        
        # 渲染内容
        content_template = Template(template['content'])
        content = content_template.render(**variables)
        
        # 渲染标题
        title_template = Template(template.get('title_format', '{{title}}'))
        title = title_template.render(**variables)
        
        return NoteContent(
            title=title,
            content=content,
            type=template['type'],
            tags=template.get('tags', [])
        )
    
    def create_template(self, name: str, config: Dict) -> None:
        """创建新模板"""
        pass
```

## 与现有命令集成

```python
# cli.py
@app.command()
def add(
    content: str,
    template: Optional[str] = typer.Option(None, "--template", "-t"),
    var: Optional[List[str]] = typer.Option(None, "--var"),
    interactive: bool = typer.Option(False, "--interactive", "-i"),
    # ... 其他参数
):
    if template:
        # 使用模板
        template_mgr = get_template_manager()
        
        # 解析变量
        variables = {}
        if var:
            for v in var:
                key, value = v.split('=', 1)
                variables[key] = value
        
        # 交互式输入缺失变量
        if interactive:
            template_config = template_mgr.load_template(template)
            # 提示用户输入变量...
        
        # 渲染模板
        note_content = template_mgr.render(template, variables)
        
        # 创建笔记
        note = create_note(
            content=note_content.content,
            title=note_content.title,
            note_type=note_content.type,
            tags=note_content.tags
        )
    else:
        # 原有逻辑
        pass
```

## 新增依赖

```txt
Jinja2>=3.1.0
```

## 验收标准

- [ ] 模板管理模块 `zk/template.py`
- [ ] `zk template` 子命令 (list, show, create, edit, remove)
- [ ] `zk add --template` 支持
- [ ] 变量渲染支持
- [ ] 交互式变量输入
- [ ] 5 个内置模板
- [ ] 模板格式文档

## 优先级

**中** - 提升用户体验，快速创建标准化笔记

## 依赖

- Issue #9 (Obsidian CLI 调研)
