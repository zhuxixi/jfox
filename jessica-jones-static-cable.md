# Zettelkasten 知识管理系统 - 详细实施方案

## 系统概述

针对 **Intel Core Ultra 7 258V (Lunar Lake)** 优化的个人知识管理系统，利用 **NPU 4.0 (47 TOPS)** 进行语义检索加速。

---

## 1. 系统架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
│  语音输入法 ──→ 终端 ──→ Kimi Code CLI ──→ Zettelkasten Skill   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        zk CLI 程序 (Python)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  笔记管理    │  │  NPU 加速    │  │  知识图谱    │             │
│  │  (Markdown) │  │  (OpenVINO) │  │  (NetworkX) │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│  ┌─────────────┐  ┌─────────────┐                               │
│  │  向量检索    │  │  文件监控    │                               │
│  │ (ChromaDB)  │  │  (watchdog) │                               │
│  └─────────────┘  └─────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        存储层                                    │
│  ~/.zettelkasten/                                                │
│  ├── notes/         # Markdown 笔记文件                         │
│  ├── .zk/chroma/    # ChromaDB 向量数据库                       │
│  └── .zk/graph.json # 链接图谱缓存                              │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 数据流

```
写入流程:
语音输入 → Kimi Skill → zk add → 写入 Markdown → 触发索引 → NPU Embedding → ChromaDB

查询流程:
语音输入 → Kimi Skill → zk query → NPU Embedding(查询) → ChromaDB检索 → 图谱遍历 → 整合结果
```

---

## 2. 目录结构

### 2.1 知识库目录 (~/.zettelkasten/)

```
~/.zettelkasten/
├── notes/                              # 笔记文件
│   ├── fleeting/                       # 闪念笔记
│   │   └── 20250322-143022.md
│   ├── literature/                     # 文献笔记
│   │   └── 20250322143022-book-title.md
│   └── permanent/                      # 永久笔记
│       └── 20250322143022-concept-name.md
├── .zk/                                # CLI 元数据（隐藏）
│   ├── chroma_db/                      # ChromaDB 数据
│   │   ├── chroma.sqlite3
│   │   └── ...
│   ├── cache/                          # 缓存
│   │   ├── embeddings.json            # Embedding 缓存
│   │   └── model_openvino/            # 预编译模型
│   ├── graph.json                      # 链接图谱
│   └── config.yaml                     # 配置文件
├── templates/                          # 笔记模板
│   ├── fleeting.md
│   ├── literature.md
│   └── permanent.md
├── inbox.md                            # 快速收集箱
└── index.md                            # 知识库索引入口
```

### 2.2 CLI 源码结构

```
zk-cli/
├── pyproject.toml              # 项目配置
├── requirements.txt            # 依赖
├── README.md                   # 文档
└── zk/
    ├── __init__.py            # 版本信息
    ├── __main__.py            # 入口点
    ├── cli.py                 # 主 CLI (Typer)
    ├── config.py              # 配置管理
    ├── models.py              # 数据模型
    ├── note.py                # 笔记操作
    ├── npu_backend.py         # NPU/Embedding
    ├── vector_store.py        # ChromaDB 封装
    ├── graph.py               # 链接图谱
    ├── indexer.py             # 索引同步
    ├── templates.py           # 模板管理
    └── utils.py               # 工具函数
```

### 2.3 Skill 结构

```
~/.config/agents/skills/zettelkasten/
├── SKILL.md                    # 技能定义
└── scripts/                    # 辅助脚本（可选）
    └── zk_helper.py
```

---

## 3. 数据模型

### 3.1 笔记模型

```python
# models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict

class NoteType(Enum):
    FLEETING = "fleeting"       # 闪念笔记
    LITERATURE = "literature"   # 文献笔记
    PERMANENT = "permanent"     # 永久笔记

@dataclass
class Note:
    """知识卡片模型"""
    id: str                                    # 时间戳 ID (20250322143022)
    title: str                                 # 标题
    content: str                               # 内容 (Markdown)
    type: NoteType                             # 类型
    created: datetime                          # 创建时间
    updated: datetime                          # 更新时间
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)      # 正向链接
    backlinks: List[str] = field(default_factory=list)  # 反向链接
    source: Optional[str] = None               # 来源（文献笔记）
    
    # 运行时字段（不持久化到 frontmatter）
    embedding: Optional[List[float]] = None    # 向量
    score: Optional[float] = None              # 检索得分
    hop: Optional[int] = None                  # 图谱距离
    
    @property
    def filename(self) -> str:
        """生成文件名"""
        if self.type == NoteType.FLEETING:
            return f"{self.id[:8]}-{self.id[8:]}.md"
        else:
            slug = self.title.lower().replace(" ", "-")[:50]
            return f"{self.id}-{slug}.md"
    
    @property
    def filepath(self) -> Path:
        """完整文件路径"""
        base = Path.home() / ".zettelkasten" / "notes" / self.type.value
        return base / self.filename
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        frontmatter = {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "tags": self.tags,
            "links": self.links,
            "backlinks": self.backlinks,
        }
        if self.source:
            frontmatter["source"] = self.source
            
        import yaml
        fm_yaml = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)
        
        return f"---\n{fm_yaml}---\n\n# {self.title}\n\n{self.content}\n"
    
    @classmethod
    def from_markdown(cls, content: str, filepath: Path) -> "Note":
        """从 Markdown 解析"""
        import yaml
        import re
        
        # 解析 frontmatter
        match = re.match(r'^---\n(.*?)\n---\n+(.*)', content, re.DOTALL)
        if not match:
            raise ValueError("Invalid markdown format")
        
        fm = yaml.safe_load(match.group(1))
        body = match.group(2)
        
        # 提取标题
        title_match = re.search(r'^# (.+)$', body, re.MULTILINE)
        title = title_match.group(1) if title_match else "Untitled"
        
        # 提取内容（去除标题）
        content_text = re.sub(r'^# .+\n+', '', body, count=1)
        
        return cls(
            id=fm.get("id", ""),
            title=fm.get("title", title),
            content=content_text.strip(),
            type=NoteType(fm.get("type", "fleeting")),
            created=datetime.fromisoformat(fm.get("created", datetime.now().isoformat())),
            updated=datetime.fromisoformat(fm.get("updated", datetime.now().isoformat())),
            tags=fm.get("tags", []),
            links=fm.get("links", []),
            backlinks=fm.get("backlinks", []),
            source=fm.get("source"),
        )
```

### 3.2 配置模型

```python
# config.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class ZKConfig:
    """Zettelkasten 配置"""
    # 路径
    base_dir: Path = Path.home() / ".zettelkasten"
    notes_dir: Path = field(init=False)
    zk_dir: Path = field(init=False)
    chroma_dir: Path = field(init=False)
    
    # NPU 配置
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    device: str = "auto"  # auto / npu / gpu / cpu
    batch_size: int = 32
    
    # 检索配置
    default_semantic_top: int = 5
    default_graph_hops: int = 2
    similarity_threshold: float = 0.7
    
    # 同步配置
    auto_sync: bool = True
    sync_interval: int = 30  # 秒
    
    def __post_init__(self):
        self.notes_dir = self.base_dir / "notes"
        self.zk_dir = self.base_dir / ".zk"
        self.chroma_dir = self.zk_dir / "chroma_db"
        
    def ensure_dirs(self):
        """确保目录存在"""
        for d in [self.notes_dir / "fleeting",
                  self.notes_dir / "literature", 
                  self.notes_dir / "permanent",
                  self.zk_dir, self.chroma_dir]:
            d.mkdir(parents=True, exist_ok=True)
```

---

## 4. NPU 加速模块

### 4.1 设备自动检测

```python
# npu_backend.py
import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class NPUAccelerator:
    """NPU 加速器封装（Lunar Lake 优化）"""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: str = "auto"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._device_name = None
        
    def _detect_device(self) -> str:
        """自动检测最佳设备"""
        if self.device != "auto":
            return self.device
            
        try:
            import openvino as ov
            core = ov.Core()
            devices = core.available_devices
            
            # 优先级：NPU > GPU > CPU
            if "NPU" in devices:
                logger.info("✅ NPU 设备已检测到")
                return "npu"
            elif "GPU" in devices:
                logger.info("✅ GPU 设备已检测到")
                return "gpu"
            else:
                logger.info("⚠️ 使用 CPU 设备")
                return "cpu"
        except ImportError:
            logger.warning("OpenVINO 未安装，使用 CPU")
            return "cpu"
    
    def load(self):
        """加载模型"""
        self._device_name = self._detect_device()
        
        try:
            from sentence_transformers import SentenceTransformer
            
            if self._device_name in ["npu", "gpu"]:
                # 使用 OpenVINO 后端
                self.model = SentenceTransformer(
                    self.model_name,
                    backend="openvino",
                    device=self._device_name
                )
            else:
                # CPU 模式
                self.model = SentenceTransformer(self.model_name)
                
            logger.info(f"模型已加载到 {self._device_name.upper()}")
            
        except Exception as e:
            logger.error(f"NPU 加载失败: {e}，降级到 CPU")
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            self._device_name = "cpu"
    
    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """编码文本"""
        if self.model is None:
            self.load()
            
        try:
            return self.model.encode(texts, batch_size=batch_size, show_progress_bar=False)
        except Exception as e:
            logger.error(f"编码失败: {e}")
            raise
    
    def encode_single(self, text: str) -> np.ndarray:
        """编码单条文本"""
        return self.encode([text])[0]
    
    @property
    def dimension(self) -> int:
        """向量维度"""
        return 384
    
    @property
    def current_device(self) -> str:
        """当前使用的设备"""
        return self._device_name or "unknown"
```

---

## 5. CLI 命令设计

### 5.1 命令列表

```python
# cli.py
import typer
from typing import Optional, List

app = typer.Typer(help="Zettelkasten 知识管理 CLI")

@app.command()
def add(
    content: str = typer.Argument(..., help="笔记内容"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="笔记标题"),
    type: str = typer.Option("fleeting", "--type", help="笔记类型 (fleeting/literature/permanent)"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="标签（可多次使用）"),
    links: Optional[List[str]] = typer.Option(None, "--link", "-l", help="链接的笔记 ID"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="来源（文献笔记）"),
):
    """添加新笔记"""
    pass

@app.command()
def search(
    query: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
):
    """语义搜索笔记"""
    pass

@app.command()
def graph(
    note_id: str = typer.Argument(..., help="中心笔记 ID"),
    hops: int = typer.Option(2, "--hops", "-d", help="遍历深度（1-3）"),
):
    """查看知识图谱"""
    pass

@app.command()
def query(
    query: str = typer.Argument(..., help="查询语句"),
    semantic_top: int = typer.Option(3, "--semantic-top", help="语义检索数量"),
    graph_hops: int = typer.Option(2, "--graph-hops", help="图谱遍历深度"),
):
    """综合查询（语义 + 图谱）"""
    pass

@app.command()
def daily(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="指定日期 (YYYY-MM-DD)"),
):
    """查看今日/指定日期笔记"""
    pass

@app.command()
def inbox(
    limit: int = typer.Option(10, "--limit", "-n", help="显示数量"),
):
    """查看收集箱"""
    pass

@app.command()
def init(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="知识库路径"),
):
    """初始化知识库"""
    pass

@app.command()
def sync(
    force: bool = typer.Option(False, "--force", "-f", help="强制全量同步"),
):
    """手动同步索引"""
    pass

@app.command()
def status():
    """查看知识库状态"""
    pass
```

### 5.2 输出格式

所有命令默认输出 **JSON**，便于 Skill 解析：

```json
// zk add "测试笔记" --type permanent --title "测试"
{
  "success": true,
  "note": {
    "id": "20250322143022",
    "title": "测试",
    "type": "permanent",
    "filepath": "~/.zettelkasten/notes/permanent/20250322143022-ce-shi.md"
  }
}

// zk search "微服务"
{
  "query": "微服务",
  "total": 5,
  "results": [
    {
      "id": "20250320143022",
      "title": "微服务架构的事件驱动设计",
      "type": "permanent",
      "score": 0.92,
      "excerpt": "在微服务架构中...",
      "filepath": "..."
    }
  ]
}

// zk query "微服务通信" --semantic-top 3 --graph-hops 2
{
  "query": "微服务通信",
  "semantic_results": [...],
  "graph_nodes": [...],
  "graph_edges": [...],
  "context": [
    {
      "note": {...},
      "relevance": "direct",
      "path": ["20250320143022"]
    }
  ]
}
```

---

## 6. Skill 设计

### 6.1 SKILL.md 结构

```yaml
---
name: zettelkasten
description: |
  Zettelkasten 知识管理系统 - 语音输入快速记录、语义检索、知识图谱。
  触发词: "zk", "zettel", "知识库", "笔记", "记录", "查找", "搜索", "关联", "今日回顾", "收集箱"
  当用户需要：
  1. 记录想法/笔记 ("记录", "记一下")
  2. 查找知识 ("查找", "搜索")
  3. 查看知识关联 ("关联", "相关知识")
  4. 回顾笔记 ("今日回顾", "今天记录了什么")
---

# Zettelkasten Skill

## 工作流程

### 1. 意图识别

解析用户输入，识别意图类型：

| 触发词 | 意图 | CLI 命令 |
|--------|------|----------|
| "记录", "记一下", "zk add" | 添加闪念笔记 | `zk add <content>` |
| "文献", "读书", "zk lit" | 添加文献笔记 | `zk add --type literature` |
| "整理", "永久", "zk perm" | 添加永久笔记 | `zk add --type permanent` |
| "查找", "搜索", "zk search" | 语义搜索 | `zk search <query>` |
| "关联", "图谱", "zk graph" | 知识图谱 | `zk graph <id>` |
| "查询", "zk query" | 综合查询 | `zk query <query>` |
| "今日回顾", "zk daily" | 今日笔记 | `zk daily` |
| "收集箱", "zk inbox" | 收集箱 | `zk inbox` |

### 2. 调用 CLI

所有操作通过 `zk` CLI 执行，解析 JSON 输出。

### 3. 结果呈现

根据操作类型，以友好方式呈现结果：

- **添加笔记**: 确认保存路径和标题
- **搜索/查询**: 展示相关知识网络（文本 + 可选的 Mermaid 图）
- **图谱**: 展示关联结构
- **回顾**: 时间线形式展示

## 使用示例

### 示例 1：记录想法

用户: "记录：关于微服务架构的一个想法，服务之间应该通过事件总线解耦"

Kimi:
1. 解析意图: 添加闪念笔记
2. 执行: `zk add "关于微服务架构的一个想法，服务之间应该通过事件总线解耦" --type fleeting`
3. 结果:
   ```
   ✅ 已创建闪念笔记
   📄 ~/.zettelkasten/notes/fleeting/20250322-143022.md
   
   🤖 语义分析发现相关笔记：
   - [0.88] 微服务拆分原则
   - [0.75] 事件驱动架构
   
   🔗 是否需要：
   1. 转为永久笔记
   2. 添加相关链接
   3. 就这样
   ```

### 示例 2：语义搜索 + 知识图谱

用户: "查找：微服务之间如何通信"

Kimi:
1. 解析意图: 综合查询
2. 执行: `zk query "微服务之间如何通信" --semantic-top 3 --graph-hops 2`
3. 结果:
   ```
   🔍 语义检索 + 链接图谱分析
   
   📌 核心笔记（语义最相关）：
   1. [0.92] 微服务架构的事件驱动设计
      - 服务间通过事件总线解耦...
      - 位置: permanent/20250320143022-xxx.md
   
   2. [0.85] 服务网格与服务发现
      - Sidecar 模式处理通信...
   
   3. [0.78] RESTful API 设计原则
      - 同步调用 vs 异步消息...
   
   🔗 相关知识网络（2跳延伸）：
   
   中心: 事件驱动设计
   ├─ 直接关联 ──→ 服务网格、CAP 定理
   ├─ 二跳关联 ──→ 容器编排、负载均衡
   └─ 相关概念 ──→ CQRS、分布式事务
   
   💡 建议进一步探索：
   - "对比事件驱动和 RPC 调用"
   - "查看所有微服务相关笔记"
   ```

### 示例 3：今日回顾

用户: "今日回顾"

Kimi:
1. 执行: `zk daily`
2. 结果:
   ```
   📅 2025-03-22 知识回顾
   
   📝 今日记录: 3 条笔记
   
   14:30 闪念笔记
   └─ 关于微服务架构的一个想法...
   
   10:15 文献笔记
   └─ 《构建微服务》- 第3章 服务通信
   
   09:00 永久笔记
   └─ 事件驱动架构设计原则
   
   🔗 知识关联:
   今日笔记与已有知识库产生 2 个新关联
   ```
```

---

## 7. 实现步骤

### Phase 1: CLI 核心功能 (MVP)

1. **项目初始化**
   - 创建 Python 项目结构
   - 配置 pyproject.toml
   - 设置依赖（typer, chromadb, sentence-transformers, openvino, watchdog）

2. **基础模块**
   - `models.py`: 数据模型
   - `config.py`: 配置管理
   - `note.py`: 笔记 CRUD

3. **NPU 集成**
   - `npu_backend.py`: NPU 封装
   - 实现设备自动检测和降级

4. **CLI 命令**
   - `zk init`: 初始化
   - `zk add`: 添加笔记
   - `zk search`: 语义搜索
   - `zk status`: 状态查看

### Phase 2: 高级功能

1. **向量存储**
   - `vector_store.py`: ChromaDB 封装
   - 集成 NPU embedding

2. **链接图谱**
   - `graph.py`: NetworkX 图管理
   - 多跳遍历算法

3. **索引同步**
   - `indexer.py`: watchdog 文件监控
   - 增量索引更新

4. **综合查询**
   - `zk query`: 语义+图谱整合
   - `zk graph`: 图谱可视化
   - `zk daily`: 每日回顾
   - `zk inbox`: 收集箱

### Phase 3: Skill 集成

1. **Skill 开发**
   - 编写 SKILL.md
   - 定义触发词和工作流程

2. **集成测试**
   - 语音输入 → Kimi → CLI 完整流程
   - NPU 性能测试

### Phase 4: 优化迭代

1. **性能优化**
   - 批量处理优化
   - 缓存策略

2. **功能增强**
   - 模板系统
   - 自动标签推荐

---

## 8. 依赖清单

```txt
# requirements.txt
# CLI 框架
typer>=0.12.0
rich>=13.0.0              # 美化输出

# NPU/AI
sentence-transformers>=3.0
openvino>=2025.0
optimum[openvouno]>=1.20

# 向量数据库
chromadb>=0.5.0

# 图谱处理
networkx>=3.0

# 文件监控
watchdog>=4.0

# 数据处理
pyyaml>=6.0
python-frontmatter>=1.0

# 工具
pydantic>=2.0
```

---

## 9. 预期性能指标

在 Intel Core Ultra 7 258V 上：

| 操作 | CPU 模式 | NPU 模式 | 提升 |
|------|---------|---------|-----|
| 单条 Embedding | 50ms | **10ms** | **5x** |
| 批量 32 条 | 1.5s | **0.3s** | **5x** |
| 语义搜索 | 100ms | **30ms** | **3x** |
| 添加笔记 | 200ms | **50ms** | **4x** |
| 功耗 | ~5W | **<1W** | **更低发热** |

---

## 10. 备选方案

### 方案 A: 纯 Skill 实现（简化版）
- 不使用 CLI，直接用 Python 脚本
- 文件搜索用 ripgrep
- 不使用向量数据库
- **适合**：快速启动，笔记量 < 1000

### 方案 B: CLI + Skill 完整版（推荐）
- 如上所述的完整方案
- **适合**：长期使用，笔记量 > 1000，需要语义检索

建议直接实施方案 B，一步到位。
