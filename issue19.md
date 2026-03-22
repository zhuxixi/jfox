## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

Obsidian CLI 提供 TUI (Terminal User Interface) 模式，允许用户在终端中以交互方式浏览和操作笔记，无需记住复杂的命令。

当前 ZK CLI 是纯命令式，对于不熟悉命令的用户不够友好。

## 目标

添加交互式 TUI 模式，提供类似 GUI 的操作体验。

## 功能设计

### 主界面

```
┌─────────────────────────────────────────────────────────────┐
│  ZK TUI - Knowledge Base: work                              │
├─────────────────────────────────────────────────────────────┤
│  Search: [                                                 ] │
├─────────────────────────────────────────────────────────────┤
│  Notes (12 total)                    │ Preview              │
│  ▸ Project Ideas                     │ # Project Ideas      │
│    Meeting 2026-03-20                │ Tags: work, planning │
│    Python Async Tips                 │                      │
│    Zettelkasten Intro                │ Discuss project      │
│    ...                               │ requirements with    │
│                                      │ team...              │
│                                      │                      │
├─────────────────────────────────────────────────────────────┤
│  [n] New  [d] Delete  [r] Rename  [s] Search  [q] Quit      │
└─────────────────────────────────────────────────────────────┘
```

### 快捷键

| 键 | 功能 |
|----|------|
| `↑/↓` 或 `j/k` | 上下选择 |
| `Enter` | 打开/查看笔记 |
| `/` 或 `s` | 搜索 |
| `n` | 新建笔记 |
| `d` | 删除笔记 |
| `r` | 重命名 |
| `t` | 切换知识库 |
| `g` | 跳转到图谱视图 |
| `q` 或 `Esc` | 退出 |

### 图谱视图

```
┌─────────────────────────────────────────────────────────────┐
│  Knowledge Graph - 42 nodes, 38 edges                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│       ┌──────────┐                                         │
│       │ Project  │──────────┐                              │
│       │ Ideas    │          │                              │
│       └────┬─────┘          ▼                              │
│            │          ┌──────────┐                         │
│            │          │ Meeting  │                         │
│            │          │ 2026-03  │                         │
│            │          └────┬─────┘                         │
│            │               │                               │
│            ▼               ▼                               │
│       ┌──────────┐    ┌──────────┐                         │
│       │ Python   │    │ Async    │                         │
│       │ Tips     │    │ Patterns │                         │
│       └──────────┘    └──────────┘                         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [←/→] Navigate  [Enter] Open  [t] Back to list  [q] Quit  │
└─────────────────────────────────────────────────────────────┘
```

## 实现方案

### 方案 A: Textual (推荐)

使用 `textual` 库构建 TUI：

```python
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, Footer, Input, Static

class ZKTUI(App):
    """ZK TUI 主应用"""
    
    CSS = """
    /* TUI 样式 */
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search...")
        yield DataTable()
        yield Static("Preview")
        yield Footer()
    
    def on_mount(self) -> None:
        # 加载笔记列表
        self.load_notes()
    
    def action_new_note(self) -> None:
        # 新建笔记
        pass
    
    def action_delete_note(self) -> None:
        # 删除笔记
        pass

# 启动
if __name__ == "__main__":
    app = ZKTUI()
    app.run()
```

### 方案 B: Rich + 简单交互

使用 `rich` 的 `Live` 和 `Prompt` 实现简化版：

```python
from rich.live import Live
from rich.table import Table
from rich.prompt import Prompt

def simple_tui():
    while True:
        # 显示表格
        table = Table()
        # ... 添加列和数据
        
        # 用户输入
        action = Prompt.ask("Action", choices=["n", "d", "s", "q"])
        
        if action == "q":
            break
        elif action == "n":
            # 新建笔记
            pass
```

## CLI 接口

```bash
# 启动 TUI
zk tui

# 或
zk interactive

# 指定知识库
zk tui --kb work
```

## 新增依赖

```txt
textual>=0.52.0
```

## 验收标准

- [ ] TUI 应用框架实现
- [ ] 笔记列表浏览
- [ ] 搜索功能（实时过滤）
- [ ] 新建/删除/重命名操作
- [ ] 知识库切换
- [ ] 简单的图谱可视化
- [ ] 键盘快捷键支持
- [ ] 响应式布局（适应终端大小）

## 优先级

**中** - 提升用户体验，但不是核心功能

## 依赖

- Issue #9 (Obsidian CLI 调研)
