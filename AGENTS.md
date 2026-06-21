# AGENTS.md - JFox 项目指南

> 本文档面向 AI 编程助手。项目语言：中文（注释和文档主要使用中文）

## 项目概述

**JFox** 是一个基于 Zettelkasten（卡片盒）方法的命令行知识管理工具。

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
├── pyproject.toml             # Python 项目配置
├── README.md                  # 详细文档（中文）
├── run_full_test.ps1          # 全量测试脚本（PowerShell）
├── jfox/                      # 主包
│   ├── __init__.py
│   ├── __main__.py            # 入口点
│   ├── cli.py                 # CLI 主程序（所有命令，~2900 行）
│   ├── models.py              # 数据模型（Note, NoteType）
│   ├── config.py              # 配置管理（ZKConfig, use_kb）
│   ├── global_config.py       # 全局配置管理（多知识库）
│   ├── note.py                # 笔记 CRUD 操作
│   ├── kb_manager.py          # 知识库管理器
│   ├── embedding_backend.py   # 嵌入模型后端（支持 daemon 代理）
│   ├── daemon/                # Embedding 模型 HTTP 守护进程
│   ├── fragment/              # 碎片采集（Hook → daemon API → SQLite）
│   ├── vector_store.py        # ChromaDB 向量存储
│   ├── bm25_index.py          # BM25 关键词索引
│   ├── search_engine.py       # 混合搜索引擎（RRF 融合）
│   ├── graph.py               # 知识图谱（NetworkX）
│   ├── indexer.py             # 文件监控和增量索引
│   ├── formatters.py          # 多格式输出（JSON/CSV/YAML/Tree）
│   ├── template.py            # 模板系统
│   ├── template_cli.py        # 模板 CLI 子命令
│   ├── git_extractor.py       # Git 仓库数据提取器（ingest 功能）
│   ├── model_downloader.py    # 嵌入模型下载与缓存管理
│   ├── note_index.py          # 笔记索引管理（文件名↔ID 映射）
│   └── performance.py         # 性能优化工具
├── tests/                     # 测试目录
│   ├── conftest.py            # pytest 配置和 fixtures
│   ├── test_core_workflow.py
│   ├── test_integration.py
│   ├── test_hybrid_search.py
│   ├── test_backlinks.py
│   ├── test_formatters.py
│   ├── test_suggest_links.py
│   ├── test_kb_current.py
│   ├── test_template.py
│   └── utils/                 # 测试工具
│       ├── temp_kb.py         # 临时知识库管理
│       ├── jfox_cli.py        # CLI 命令封装
│       └── note_generator.py  # 测试数据生成
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
# 安装（使用 uv，推荐）
uv sync --extra dev

# 安装（legacy pip fallback）
pip install -e ".[dev]"
```

### 运行测试

```bash
# 运行所有测试
uv run pytest tests/ -v

# 运行特定测试文件
uv run pytest tests/test_core_workflow.py -v

# 运行带标记的测试
uv run pytest tests/ -m "not slow"                     # 排除慢测试
uv run pytest tests/ -m "not embedding and not slow"   # 快速测试（不加载模型）
uv run pytest tests/ -m "integration"                  # 仅运行集成测试

# 保留测试数据（用于调试）
uv run pytest tests/ --keep-data

# 覆盖率
uv run pytest tests/ --cov=jfox --cov-report=html

# Windows 全量测试（清理 + 测试）
.\run_full_test.ps1

# 保留数据运行测试
.\run_full_test.ps1 -KeepData
```

### 代码格式化

```bash
# 使用 black 格式化
uv run black jfox/ tests/

# 使用 ruff 检查
uv run ruff check jfox/ tests/
```

### 构建和验证

```bash
# 构建
uv build

# 验证 CLI
uv run jfox --help
uv run jfox --version
```

## 代码组织

### 核心模块职责

| 模块 | 职责 |
|------|------|
| `cli.py` | 所有 CLI 命令定义和实现（~2900 行） |
| `models.py` | Note 数据类、NoteType 枚举、Markdown 序列化/反序列化 |
| `config.py` | ZKConfig 配置类、use_kb 上下文管理器（多知识库切换） |
| `global_config.py` | GlobalConfigManager，管理 ~/.zk_config.json |
| `note.py` | 笔记 CRUD：create_note, save_note, load_note, delete_note |
| `kb_manager.py` | KnowledgeBaseManager，知识库生命周期管理 |
| `search_engine.py` | HybridSearchEngine，支持 HYBRID/SEMANTIC/KEYWORD 模式，RRF 融合 |
| `bm25_index.py` | BM25Index，本地文件存储的关键词索引 |
| `vector_store.py` | VectorStore，ChromaDB 封装 |
| `graph.py` | KnowledgeGraph，NetworkX 图分析和可视化 |
| `git_extractor.py` | Git 仓库数据提取器（ingest 功能） |
| `model_downloader.py` | 嵌入模型下载与缓存管理 |
| `note_index.py` | 笔记索引管理（文件名↔ID 映射） |
| `indexer.py` | 文件监控（watchdog）+ 增量索引 |
| `daemon/` | Embedding 模型 HTTP 守护进程（server/client/process） |
| `fragment/` | 碎片采集：detector 分类 + store SQLite + service 编排 |

### 笔记类型

```python
class NoteType(Enum):
    FLEETING = "fleeting"       # 闪念笔记 - 快速捕捉
    LITERATURE = "literature"   # 文献笔记 - 读书笔记
    PERMANENT = "permanent"     # 永久笔记 - 整理后的知识
    SESSION = "session"         # AI Agent 会话记录
```

各类型文件名格式：
- `fleeting`: `YYYYMMDD-HHMMSS.md`
- `literature`: `YYYYMMDDHHMMSS-{slug}.md`
- `permanent`: `YYYYMMDDHHMMSS-{slug}.md`

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
topic: null                    # 会话主题（仅 session 类型）
---

# 笔记标题

笔记内容，支持 [[其他笔记标题]] 双向链接语法
```

### 多知识库支持

- 全局配置存储在 `~/.zk_config.json`
- 默认知识库路径：`~/.zettelkasten/default/`
- 命名知识库路径：`~/.zettelkasten/<name>/`
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

### 测试目录结构

- `tests/unit/` — 纯逻辑单元测试（约 25 个文件）
- `tests/integration/` — 跨模块集成测试
- `tests/performance/` — 性能基准测试
- 根级遗留：`test_config_unit.py`、`test_config_set_unit.py`（与 unit 目录中测试内容不同）

### 测试工具

- **临时知识库**: `tests/utils/temp_kb.py`
- **CLI 封装**: `tests/utils/jfox_cli.py`
- **数据生成**: `tests/utils/note_generator.py`

### 测试 Fixture

```python
# conftest.py 中定义的主要 fixtures

def test_example(temp_kb, cli, cli_fast, generator, mock_embedding_backend):
    """
    temp_kb: 临时知识库路径
    cli: 已初始化的 ZKCLI 实例
    cli_fast: ZKCLI with mocked embeddings（快速，不加载模型）
    generator: NoteGenerator 数据生成器
    mock_embedding_backend: mock 嵌入后端
    """
    pass
```

### 测试标记（Markers）

| 标记 | 含义 |
|------|------|
| `slow` | 慢测试 |
| `performance` | 性能基准 |
| `integration` | 集成测试 |
| `embedding` | 涉及模型加载 |
| `workflow` | 工作流测试 |
| `bulk` | 批量操作测试 |

### 测试运行规则

- **全量/集成测试（~50min）不要自主运行**，提供命令让用户手动执行
- **快速单元测试（几秒内）可以自主运行**，如单个模块的纯逻辑测试，不涉及 embedding 或 ChromaDB
- `pytest.ini` 配置：`timeout=120`、`--strict-markers`、`-ra`
- 测试以单进程运行，避免 ChromaDB/模型加载冲突

### 编写新测试的模板

```python
# tests/test_feature.py

import pytest


class TestFeatureName:
    """测试功能名称"""
    
    def test_basic_functionality(self, temp_kb, cli):
        """测试基本功能"""
        # 使用 fixture 自动初始化的临时知识库和 CLI 实例
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

## CI（GitHub Actions）

`.github/workflows/integration-test.yml` 包含四个 job：

- **Fast**（PR/push 触发）：`not embedding and not slow`，Python 3.11，Ubuntu + Windows
- **Core**（main 分支推送）：Core workflow 测试，使用真实 embedding，Python 3.10 + 3.12
- **Full**（手动触发）：所有测试、所有 OS、所有 Python 版本
- **Coverage**（Fast 完成后）：运行覆盖率，上传 HTML/XML 产物

**Release** 工作流（`.github/workflows/publish.yml`）：在 GitHub Release 发布时自动推送到 PyPI。

## Windows 注意事项

- `robocopy` 参数会被 bash 误解析，应使用 `cmd.exe /c "robocopy source dest /E"`
- 设置 `PYTHONUTF8=1` 和 `chcp 65001` 避免编码问题
- HuggingFace 国内镜像：`export HF_ENDPOINT=https://hf-mirror.com`

## 分支规则

- **main 是保护分支**，不能直接 commit 或 push
- 所有改动必须通过**新分支 + PR** 合入

## 发版规则

- 发版时必须同时修改三处版本号：
  1. `pyproject.toml`
  2. `jfox/__init__.py`
  3. `uv.lock`
- 操作顺序：先改 `pyproject.toml` 和 `__init__.py`，再跑 `uv lock` 更新 lock 文件
- （曾有 #88 遗漏 `__init__.py` 的教训）

## 相关资源

- **详细 CLI 文档**: `README.md`
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

## 常见陷阱（Gotchas）

- `pytest.ini` 的 `addopts` 已包含 `-v`，手动再加 `-v` 是冗余的
- 测试目录重组已基本完成，根级 `test_config_unit.py` 和 `test_config_set_unit.py` 与 `tests/unit/` 中对应文件测试内容不同，不是重复
- `jfox show <id_or_title>` 复用 `find_note_id_by_title_or_id` 定位笔记，只读输出完整 Markdown

---

## Session History

📋 **完整会话历史**: [SESSION.md](./SESSION.md)

> 最近3个 session 摘要：
> - **Session 2** (2026-03-25): 修复 Windows Unicode 编码问题，改进 list table 格式
> - **Session 1** (2026-03-25): 通过 `/init` 命令生成 AGENTS.md 项目指南

---

*本文档最后更新: 2026-03-26*
