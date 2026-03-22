## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

Obsidian CLI 支持 8+ 种输出格式 (`json`, `csv`, `tsv`, `md`, `paths`, `text`, `tree`, `yaml`)，便于与其他工具集成。

当前 ZK CLI 仅支持 `json` 和 `text` 两种格式，限制了与外部工具（jq, Excel, 脚本等）的集成能力。

## 目标

为所有输出命令添加多种格式支持，便于管道处理和工具集成。

## 需要支持的格式

| 格式 | 用途 | 示例场景 |
|------|------|----------|
| `json` | 机器解析 | 当前已支持 |
| `text` | 人类阅读 | 当前已支持 |
| `csv` | Excel 导入 | `zk list --format csv > notes.csv` |
| `yaml` | 配置文件 | `zk kb info --format yaml` |
| `paths` | 仅文件路径 | `zk search "TODO" --format paths \| xargs rm` |
| `table` | 终端表格 | 默认格式，替代当前 text |
| `tree` | 树形结构 | `zk list --format tree` |

## 实现方案

### 1. 创建格式器模块 `zk/formatters.py`

```python
from typing import List, Dict, Any
import csv
import json
import yaml
from rich.table import Table

class OutputFormatter:
    @staticmethod
    def to_json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    @staticmethod
    def to_csv(data: List[Dict], headers: List[str]) -> str:
        # CSV 格式输出
        pass
    
    @staticmethod
    def to_yaml(data: Any) -> str:
        return yaml.dump(data, allow_unicode=True)
    
    @staticmethod
    def to_paths(data: List[Dict]) -> str:
        # 仅提取路径，每行一个
        return "\n".join(item.get("filepath", "") for item in data)
    
    @staticmethod
    def to_tree(data: Any) -> str:
        # 树形结构
        pass
```

### 2. 修改 CLI 命令

为以下命令添加 `--format` 参数：

```python
@app.command()
def list(
    format: str = typer.Option("table", "--format", "-f", 
                               help="输出格式: json, csv, yaml, table, paths"),
    # ... 其他参数
):
    results = note.list_notes(...)
    
    if format == "json":
        console.print(json.dumps([r.to_dict() for r in results]))
    elif format == "csv":
        console.print(formatter.to_csv([r.to_dict() for r in results]))
    elif format == "yaml":
        console.print(yaml.dump([r.to_dict() for r in results]))
    elif format == "paths":
        for r in results:
            console.print(r.filepath)
    else:  # table
        # 当前表格输出
```

### 3. 需要修改的命令

| 命令 | 当前格式 | 新增格式 |
|------|---------|----------|
| `zk list` | json/text | csv, yaml, paths, tree |
| `zk search` | json/text | csv, yaml, paths |
| `zk kb list` | json/text | csv, yaml, table |
| `zk kb info` | json/text | yaml |
| `zk refs` | json/text | csv, yaml, table |
| `zk graph --stats` | json/text | yaml, table |

## 使用示例

```bash
# 导出到 Excel
zk list --format csv > notes.csv

# 仅获取路径，批量处理
zk search "TODO" --format paths | xargs -I {} mv {} inbox/

# YAML 格式便于配置文件
zk kb info work --format yaml > work-kb.yaml

# 与 jq 结合
zk search "机器学习" --format json | jq '.[].title'
```

## 新增依赖

```txt
PyYAML>=6.0
```

## 验收标准

- [ ] `zk/formatters.py` 模块实现
- [ ] 所有列出的命令支持 `--format` 参数
- [ ] 支持 json, csv, yaml, table, paths, tree 格式
- [ ] 默认格式保持与当前一致（向后兼容）
- [ ] 添加相应测试

## 优先级

**高** - 便于工具集成和自动化

## 依赖

- Issue #9 (Obsidian CLI 调研)
