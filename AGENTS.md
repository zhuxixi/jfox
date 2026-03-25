# AGENTS.md - JFox / ZK CLI 项目指南

> 本文档面向 AI 编程助手。项目语言：中文（注释和文档主要使用中文）

## 项目概述

**JFox**（又称 ZK CLI）是一个基于 Zettelkasten（卡片盒）方法的命令行知识管理工具。

- **项目定位**: 本地优先的个人知识库软件
- **核心价值**: 通过双向链接、语义搜索和知识图谱，帮助用户构建可生长的知识网络
- **技术特点**: 纯 CPU 运行，无需 GPU/NPU，数据完全本地存储

### 为什么叫 JFox？
- **J** - 创始人名字 "Jiefeng" 的首字母
- **Fox** - 谐音 "Box"（盒子），呼应卡片盒本质；狐狸象征聪明、机敏

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python >= 3.10 |
| CLI 框架 | Typer >= 0.12.0 |
| 终端美化 | Rich >= 13.0.0 |
| 文本嵌入 | sentence-transformers >= 3.0 (all-MiniLM-L6-v2) |
| 向量数据库 | ChromaDB >= 0.5.0 |
| 知识图谱 | NetworkX >= 3.0 |
| 文件监控 | Watchdog >= 3.0 |
| 配置管理 | PyYAML >= 6.0, Pydantic >= 2.0 |
| 模板引擎 | Jinja2 >= 3.1.0 |

## 项目结构

```
jfox/
├── zk-cli/                    # 主应用目录
│   ├── pyproject.toml         # Python 项目配置
│   ├── requirements.txt       # 依赖列表
│   ├── README.md              # 详细文档（中文）
│   ├── run_full_test.ps1      # 全量测试脚本（PowerShell）
│   ├── zk/                    # 主包
│   │   ├── __init__.py
│   │   ├── __main__.py        # 入口点
│   │   ├── cli.py             # CLI 主程序（所有命令）
│   │   ├── models.py          # 数据模型（Note, NoteType）
│   │   ├── config.py          # 配置管理（ZKConfig, use_kb）
│   │   ├── global_config.py   # 全局配置管理（多知识库）
│   │   ├── note.py            # 笔记 CRUD 操作
│   │   ├── kb_manager.py      # 知识库管理器
│   │   ├── embedding_backend.py  # 嵌入模型后端
│   │   ├── vector_store.py    # ChromaDB 向量存储
│   │   ├── bm25_index.py      # BM25 关键词索引
│   │   ├── search_engine.py   # 混合搜索引擎（RRF 融合）
│   │   ├── graph.py           # 知识图谱（NetworkX）
│   │   ├── indexer.py         # 文件监控和索引
│   │   ├── formatters.py      # 多格式输出（JSON/CSV/YAML/Tree）
│   │   ├── template.py        # 模板系统
│   │   ├── template_cli.py    # 模板 CLI 子命令
│   │   └── performance.py     # 性能优化工具
│   └── tests/                 # 测试目录
│       ├── conftest.py        # pytest 配置和 fixtures
│       ├── test_core_workflow.py
│       ├── test_integration.py
│       ├── test_hybrid_search.py
│       ├── test_backlinks.py
│       ├── test_formatters.py
│       ├── test_suggest_links.py
│       ├── test_kb_current.py
│       ├── test_template.py
│       └── utils/             # 测试工具
│           ├── temp_kb.py     # 临时知识库管理
│           ├── zk_cli.py      # CLI 命令封装
│           └── note_generator.py  # 测试数据生成
├── skill/                     # Kimi Skill 定义
│   ├── knowledge-base-notes/SKILL.md    # 笔记管理 Skill
│   └── knowledge-base-workspace/SKILL.md # 知识库工作空间 Skill
├── DEVELOPMENT_PLAN.md        # 开发计划与验收标准
├── SESSION_SUMMARY.md         # 会话历史记录
└── AGENTS.md                  # 本文档
```

## 构建和测试命令

### 安装开发环境

```bash
cd zk-cli

# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 开发模式安装
pip install -e ".[dev]"
```

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_core_workflow.py -v

# 运行带标记的测试
pytest tests/ -m "not slow"      # 排除慢测试
pytest tests/ -m "integration"   # 仅运行集成测试

# 保留测试数据（用于调试）
pytest tests/ --keep-data

# Windows 全量测试（清理 + 测试）
.\run_full_test.ps1

# 保留数据运行测试
.\run_full_test.ps1 -KeepData
```

### 代码格式化

```bash
# 使用 black 格式化
black zk/ tests/

# 使用 ruff 检查
ruff check zk/ tests/
```

### 本地安装和验证

```bash
# 安装到本地
pip install -e .

# 验证安装
zk --help
zk --version
```

## 代码组织

### 核心模块职责

| 模块 | 职责 |
|------|------|
| `cli.py` | 所有 CLI 命令定义和实现（~1000 行） |
| `models.py` | Note 数据类、NoteType 枚举、Markdown 序列化/反序列化 |
| `config.py` | ZKConfig 配置类、use_kb 上下文管理器（多知识库切换） |
| `global_config.py` | GlobalConfigManager，管理 ~/.zk_config.json |
| `note.py` | 笔记 CRUD：create_note, save_note, load_note, delete_note |
| `kb_manager.py` | KnowledgeBaseManager，知识库生命周期管理 |
| `search_engine.py` | HybridSearchEngine，支持 HYBRID/SEMANTIC/KEYWORD 模式 |
| `bm25_index.py` | BM25Index，本地文件存储的关键词索引 |
| `vector_store.py` | VectorStore，ChromaDB 封装 |
| `graph.py` | KnowledgeGraph，NetworkX 图分析和可视化 |

### 笔记类型

```python
class NoteType(Enum):
    FLEETING = "fleeting"       # 闪念笔记 - 快速捕捉
    LITERATURE = "literature"   # 文献笔记 - 读书笔记
    PERMANENT = "permanent"     # 永久笔记 - 整理后的知识
```

### 笔记文件格式

每个笔记是一个 Markdown 文件，包含 YAML frontmatter：

```markdown
---
id: '20260321011528'
title: 笔记标题
type: permanent
created: '2026-03-21T01:15:28'
updated: '2026-03-21T01:15:28'
tags: [tag1, tag2]
links: ['20260321011546']      # 正向链接
backlinks: ['20260321011550']  # 反向链接（自动生成）
---

# 笔记标题

笔记内容，支持 [[其他笔记标题]] 双向链接语法
```

### 多知识库支持

- 全局配置存储在 `~/.zk_config.json`
- 默认知识库路径：`~/.zettelkasten`
- 命名知识库路径：`~/.zettelkasten-{name}`
- 使用 `use_kb()` 上下文管理器临时切换知识库

## 代码风格指南

### Python 代码规范

- **行长度**: 100 字符（pyproject.toml 中配置）
- **格式化**: black
- **检查**: ruff
- **类型注解**: 鼓励使用，特别是公共 API

### 命名规范

- **类名**: PascalCase（如 `KnowledgeGraph`, `NoteType`）
- **函数/方法**: snake_case（如 `create_note`, `search_notes`）
- **常量**: UPPER_SNAKE_CASE
- **私有成员**: 下划线前缀（如 `_note_cache`）

### 注释规范

- 使用中文注释（与项目文档保持一致）
- 模块和类需要文档字符串
- 复杂函数需要参数和返回值说明

### 错误处理

- 使用 try-except 捕获具体异常
- 记录错误日志（logging）
- CLI 命令返回结构化错误（JSON 格式）

## 测试策略

### 测试类型

1. **单元测试**: 测试单个函数/方法
2. **集成测试**: 测试完整工作流
3. **性能测试**: 标记为 `@pytest.mark.performance`

### 测试工具

- **临时知识库**: `tests/utils/temp_kb.py`
- **CLI 封装**: `tests/utils/zk_cli.py`
- **数据生成**: `tests/utils/note_generator.py`

### 测试 Fixture

```python
# conftest.py 中定义的主要 fixtures

def test_example(temp_kb, cli, generator):
    """
    temp_kb: 临时知识库路径
    cli: 已初始化的 ZKCLI 实例
    generator: NoteGenerator 数据生成器
    """
    pass
```

### 编写新测试的模板

```python
# tests/test_feature.py

import pytest
from tests.utils.temp_kb import temp_knowledge_base
from tests.utils.zk_cli import ZKCLI


class TestFeatureName:
    """测试功能名称"""
    
    def test_basic_functionality(self, temp_kb):
        """测试基本功能"""
        cli = ZKCLI(temp_kb)
        cli.init()
        
        # 测试代码
        result = cli.add("测试内容", title="测试笔记")
        
        assert result.success
        assert "test" in result.stdout.lower()
```

## 开发约定

### 添加新 CLI 命令

1. 在 `cli.py` 中定义命令函数
2. 使用 `@app.command()` 装饰器
3. 提供 `--format json` 输出支持
4. 添加 `--kb` 参数支持多知识库
5. 实现内部 `_xxx_impl()` 函数便于复用

模板：

```python
@app.command()
def new_command(
    arg: str = typer.Argument(..., help="参数说明"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式"),
):
    """命令说明"""
    try:
        if kb:
            from .config import use_kb
            with use_kb(kb):
                _new_command_impl(arg, output_format)
        else:
            _new_command_impl(arg, output_format)
    except Exception as e:
        # 错误处理...
        raise typer.Exit(1)
```

### 添加新搜索模式

1. 在 `search_engine.py` 的 `SearchMode` 枚举中添加模式
2. 在 `HybridSearchEngine.search()` 中实现逻辑
3. 更新 CLI 的 `--mode` 参数帮助文本

### 修改数据模型

1. 更新 `models.py` 中的 `Note` 类
2. 更新 `to_markdown()` 和 `from_markdown()` 方法
3. 考虑向后兼容性
4. 更新相关测试

## 安全注意事项

### 路径安全

- 使用 `Path.expanduser().resolve()` 处理用户输入路径
- 避免路径遍历攻击

### 命令注入

- 使用 Typer 的参数解析，避免直接拼接 shell 命令
- 用户输入内容应转义后再写入文件

### 数据安全

- 所有数据存储在用户主目录下（`~/.zettelkasten*`）
- 不会上传数据到远程服务器
- 向量数据库（ChromaDB）完全本地运行

## 性能基准

在 Intel Core Ultra 7 258V 上的性能指标：

| 操作 | 耗时 |
|------|------|
| 嵌入生成 | ~1.6ms/文本 |
| 语义搜索 | <100ms |
| 图谱构建 | <1s (1000笔记) |
| 文件监控 | 实时 (<1s 延迟) |

## 相关资源

- **详细 CLI 文档**: `zk-cli/README.md`
- **开发计划**: `DEVELOPMENT_PLAN.md`
- **会话历史**: `SESSION_SUMMARY.md`
- **Kimi Skills**: `skill/` 目录

## 常见任务速查

### 添加一个新的笔记命令

```python
# 1. 在 cli.py 中添加命令
@app.command()
def my_command(...):
    ...

# 2. 确保支持 --kb 参数
# 3. 添加测试到 tests/test_my_command.py
# 4. 更新 README.md 文档
```

### 添加新的输出格式

```python
# 在 formatters.py 中添加
class OutputFormatter:
    @staticmethod
    def to_new_format(data: List[Dict]) -> str:
        ...
```

### 添加新的搜索后端

```python
# 1. 创建新模块（如 new_index.py）
# 2. 实现索引类
# 3. 在 search_engine.py 中集成
# 4. 添加测试
```

---

## Session History

📋 **完整会话历史**: [SESSION.md](./SESSION.md)

> 最近会话摘要：
> - **Session 1** (2026-03-25): 通过 `/init` 命令生成 AGENTS.md 项目指南

---

*本文档最后更新: 2026-03-25*
