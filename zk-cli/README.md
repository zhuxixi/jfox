# ZK CLI - Zettelkasten 知识管理工具

一个简洁高效的命令行知识管理工具，基于 [Zettelkasten（卡片盒）](https://en.wikipedia.org/wiki/Zettelkasten) 方法论构建。

> 🦊 **为什么叫 ZK？** Zettelkasten 的缩写，德语中意为"纸条盒子"，是德国社会学家尼克拉斯·卢曼发明的知识管理系统。

---

## ✨ 核心特性

- 📝 **三种笔记类型** - 闪念笔记(Fleeting)、文献笔记(Literature)、永久笔记(Permanent)
- 🔗 **双向链接** - 使用 `[[笔记标题]]` 语法轻松建立笔记关联
- 🔍 **语义搜索** - 基于向量嵌入的智能搜索，理解内容含义而非关键词匹配
- 🕸️ **知识图谱** - NetworkX 驱动的链接关系分析和可视化
- 👁️ **文件监控** - 实时监控笔记变化，自动更新索引
- ⚡ **本地优先** - 纯 CPU 运行，无需 GPU/NPU，数据完全本地存储

---

## 📦 安装

### 推荐方式（使用 uv）

```bash
# 从 GitHub 克隆并安装（本地开发）
git clone https://github.com/zhuxixi/jfox.git
cd jfox/zk-cli
uv sync --extra dev

# 或直接安装为全局工具
uv tool install "git+https://github.com/zhuxixi/jfox.git#subdirectory=zk-cli"

# 免安装试用
uvx --from "git+https://github.com/zhuxixi/jfox.git#subdirectory=zk-cli" zk --help
```

验证安装：
```bash
zk --help
zk --version
```

### 传统方式（使用 pip）

```bash
pip install -e ".[dev]"
```

### 卸载

```bash
# uv 安装的用户
uv tool uninstall zk-cli

# pip 安装的用户
pip uninstall zk-cli
```

### 依赖要求

- Python >= 3.10
- 依赖包：typer, rich, sentence-transformers, chromadb, networkx, watchdog, pyyaml

### Windows PATH 问题

如果在 Windows 上提示找不到 `zk` 命令，请确保 Python Scripts 目录在 PATH 中：

```powershell
# 查看安装位置
pip show zk-cli | findstr Location
# 将对应的 Scripts 目录添加到 PATH，例如：
# C:\Users\<用户名>\AppData\Local\Packages\PythonSoftwareFoundation.Python3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts
```

---

## 🚀 快速开始

### 1. 初始化知识库

```bash
# 初始化默认知识库
zk init

# 创建命名知识库
zk init --name work --desc "工作笔记"
zk init --name personal --path ~/my-notes --desc "个人笔记"
```

这会创建知识库并注册到全局配置：
- 默认路径：`~/.zettelkasten`（默认知识库）或 `~/.zettelkasten-<name>`
- 包含目录：`notes/`（笔记文件）、`.zk/`（索引和配置）

### 2. 管理多个知识库

```bash
# 列出所有知识库
zk kb list

# 切换默认知识库
zk kb switch work

# 查看知识库详情
zk kb info work

# 删除知识库
zk kb remove work --force
```

### 3. 创建第一条笔记

```bash
zk add "这是我的第一条笔记，关于 Zettelkasten 知识管理方法" \
    --title "Zettelkasten 简介" \
    --type permanent
```

### 3. 创建带链接的笔记

```bash
zk add "[[Zettelkasten 简介]] 是一种非常有效的知识管理方法，由卢曼发明" \
    --title "卢曼与卡片盒" \
    --type permanent
```

注意到 `[[Zettelkasten 简介]]` 了吗？这就是**双向链接**语法，系统会自动：
- 找到标题包含"Zettelkasten 简介"的笔记
- 建立链接关系
- 生成反向链接

### 4. 查看引用关系

```bash
# 查看所有笔记的引用统计
zk refs

# 搜索特定笔记
zk refs --search "Zettelkasten"

# 查看具体笔记的引用关系
zk refs --note 20260321011528
```

### 5. 语义搜索

```bash
# 搜索相关知识
zk search "知识管理方法"

# 联合图谱的深度搜索
zk query "卢曼的方法论"
```

---

## 📚 完整命令参考

### 知识库管理

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk init` | 初始化知识库 | `zk init --name work --desc "工作笔记"` |
| `zk kb list` | 列出所有知识库 | `zk kb list` |
| `zk kb create <name>` | 创建知识库 | `zk kb create work --desc "工作笔记"` |
| `zk kb switch <name>` | 切换默认知识库 | `zk kb switch work` |
| `zk kb info [name]` | 查看知识库详情 | `zk kb info work` |
| `zk kb rename <old> <new>` | 重命名知识库 | `zk kb rename work job` |
| `zk kb remove <name>` | 删除知识库 | `zk kb remove temp --force` |

### 基础命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk init` | 初始化知识库 | `zk init` 或 `zk init --name work` |
| `zk add <content>` | 添加笔记 | `zk add "内容" --title "标题" --type permanent` |
| `zk list` | 列出笔记 | `zk list --type permanent --limit 20` |
| `zk search <query>` | 语义搜索 | `zk search "机器学习"` |
| `zk status` | 查看状态 | `zk status` |
| `zk delete <id>` | 删除笔记 | `zk delete 20260321011528 --force` |

### 双向链接相关

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk refs` | 查看引用关系 | `zk refs --search "关键词"` |
| `zk refs --note <id>` | 查看特定笔记的引用 | `zk refs --note 20260321011528` |

### 知识图谱

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk graph --stats` | 查看图谱统计 | `zk graph --stats` |
| `zk graph --orphans` | 孤立笔记 | `zk graph --orphans` |
| `zk graph --note <id>` | 查看子图 | `zk graph --note 20260321011528 --depth 2` |

### 时间管理

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk daily` | 今日笔记 | `zk daily` |
| `zk daily --date 2026-03-20` | 特定日期 | `zk daily --date 2026-03-20` |
| `zk inbox` | 临时笔记箱 | `zk inbox --limit 10` |

### 索引管理

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk index status` | 索引状态 | `zk index status` |
| `zk index rebuild` | 重建索引 | `zk index rebuild` |
| `zk index verify` | 验证完整性 | `zk index verify` |

### 高级查询

| 命令 | 说明 | 示例 |
|------|------|------|
| `zk query <text>` | 语义+图谱联合搜索 | `zk query "相关概念" --depth 2` |

---

## 📦 知识库管理

支持多知识库管理，方便区分不同领域的笔记（如工作、学习、个人）。

### 全局配置

所有知识库信息存储在 `~/.zk_config.json`：

```json
{
  "current_kb": "work",
  "knowledge_bases": {
    "default": {
      "path": "/home/user/.zettelkasten",
      "description": "Default knowledge base",
      "created": "2026-03-20T10:00:00"
    },
    "work": {
      "path": "/home/user/.zettelkasten-work",
      "description": "工作笔记",
      "created": "2026-03-21T14:30:00"
    }
  }
}
```

### 初始化命名知识库

```bash
# 创建名为 work 的知识库
zk init --name work --desc "工作相关笔记"

# 指定自定义路径
zk init --name personal --path ~/Documents/my-notes --desc "个人笔记"

# 创建但不设为默认
zk init --name temp --no-default
```

### 查看所有知识库

```bash
$ zk kb list

● default    ~/.zettelkasten              42    10/15/17    2026-03-20
○ work       ~/.zettelkasten-work         28    5/8/15      2026-03-21
○ personal   ~/.zettelkasten-personal     15    3/5/7       2026-03-19

● = current default, ○ = available
```

列说明：
- `Status`: ● 当前默认，○ 可用
- `F/L/P`: 闪念笔记/文献笔记/永久笔记数量

### 切换知识库

```bash
# 切换到 work 知识库
zk kb switch work

# 之后的所有操作都在 work 知识库上进行
zk add "新项目想法" --title "项目A"
zk list
```

### 知识库详情

```bash
$ zk kb info work

work [current]
  Path: /home/user/.zettelkasten-work
  Description: 工作笔记
  Created: 2026-03-21T14:30:00
  Last used: 2026-03-21T18:45:00

  Total notes: 28
    - Fleeting: 5
    - Literature: 8
    - Permanent: 15
```

---

## 🔗 双向链接详解

### 链接语法

在笔记内容中使用 `[[目标笔记标题]]` 即可创建链接：

```bash
zk add "[[机器学习]] 是人工智能的一个重要分支，包括监督学习和无监督学习" \
    --title "机器学习概述" \
    --type permanent
```

### 链接匹配规则

系统会按以下优先级匹配：
1. **精确 ID 匹配** - 如果内容正好是某个笔记的 ID
2. **标题包含匹配** - 标题包含链接文本
3. **标题精确匹配** - 标题完全等于链接文本

### 查看链接关系

```bash
# 查看所有笔记的链接统计
zk refs

# 输出示例：
# | ID           | Title           | Type     | Out | In |
# |--------------|-----------------|----------|-----|-----|
# | 202603210... | 机器学习概述    | permanent| 1   | 2   |
# | 202603210... | 深度学习        | permanent| 2   | 1   |
```

### 笔记文件中的链接

```markdown
---
id: '20260321011528'
title: 机器学习概述
type: permanent
links:
- 20260321011546        # 我链接到的笔记
backlinks:               # 链接到我的笔记（自动生成）
- 20260321011550
---

# 机器学习概述

[[深度学习]] 是机器学习的一个子领域...
```

---

## 🕸️ 知识图谱

### 查看图谱统计

```bash
$ zk graph --stats

{
  "total_nodes": 42,
  "total_edges": 38,
  "avg_degree": 1.81,
  "isolated_nodes": 5,
  "clusters": 3,
  "top_hubs": [
    {"id": "20260321011528", "title": "机器学习概述", "degree": 12},
    {"id": "20260321011546", "title": "深度学习", "degree": 8}
  ]
}
```

### 指标说明

| 指标 | 含义 |
|------|------|
| `total_nodes` | 笔记总数 |
| `total_edges` | 链接总数（正向+反向） |
| `avg_degree` | 平均连接数 |
| `isolated_nodes` | 孤立笔记数（没有链接） |
| `clusters` | 连通子图数量 |
| `top_hubs` | 最连接的笔记（枢纽） |

### 发现孤立笔记

```bash
$ zk graph --orphans

{
  "orphans": [
    {"id": "20260321011528", "title": "待整理的闪念", "type": "fleeting"}
  ]
}
```

孤立笔记是还没有建立任何链接的笔记，适合后续整理。

---

## 📝 笔记格式

### 文件结构

单个知识库：
```
~/.zettelkasten/                    # 默认知识库
├── notes/
│   ├── fleeting/                   # 闪念笔记
│   ├── literature/                 # 文献笔记
│   └── permanent/                  # 永久笔记
└── .zk/
    └── chroma_db/                  # 向量索引

~/.zettelkasten-work/               # 命名知识库示例
├── notes/
└── .zk/
```

全局配置：`~/.zk_config.json`

### 笔记文件格式

每个笔记是一个 Markdown 文件，包含 YAML frontmatter：

```markdown
---
id: '20260321011528'                    # 唯一标识符（时间戳）
title: ML Note 1                        # 标题
type: permanent                         # 类型：fleeting/literature/permanent
created: '2026-03-21T01:15:28'          # 创建时间
updated: '2026-03-21T01:15:28'          # 更新时间
tags:                                   # 标签列表
- ml
- ai
links:                                  # 正向链接（我引用的笔记）
- 20260321011546
backlinks:                              # 反向链接（引用我的笔记）
- 20260321011550
---

# ML Note 1

This is a test note about machine learning
```

### 笔记类型说明

| 类型 | 用途 | 文件名格式 |
|------|------|-----------|
| `fleeting` | 快速捕捉的临时想法 | `YYYYMMDD-HHMMSS.md` |
| `literature` | 读书笔记、文献摘要 | `YYYYMMDDHHMMSS-{slug}.md` |
| `permanent` | 经过整理的永久知识 | `YYYYMMDDHHMMSS-{slug}.md` |

---

## 🔧 高级用法

### 批量导入笔记

```bash
# 使用 shell 循环批量添加
for file in ~/old-notes/*.md; do
    content=$(cat "$file")
    zk add "$content" --title "$(basename "$file" .md)" --type permanent
done
```

### 配合编辑器使用

由于笔记是纯 Markdown 文件，你可以用任何编辑器编辑：

```bash
# VS Code
zk list | code -

# 直接编辑特定笔记
zk refs --search "目标笔记"
# 找到 ID 后
code ~/.zettelkasten/notes/permanent/20260321011528-ml-note-1.md
```

### 备份知识库

```bash
# 笔记就是普通文件，直接备份目录
cp -r ~/.zettelkasten ~/backup/zettelkasten-$(date +%Y%m%d)

# 或使用 git
cd ~/.zettelkasten
git init
git add .
git commit -m "Backup $(date)"
```

---

## ⚡ 性能指标

在 Intel Core Ultra 7 258V 上测试：

| 操作 | 耗时 |
|------|------|
| 嵌入生成 | ~1.6ms/文本 |
| 语义搜索 | <100ms |
| 图谱构建 | <1s (1000笔记) |
| 文件监控 | 实时 (<1s 延迟) |

---

## 🐛 故障排除

### 问题：找不到命令 `zk`

```bash
# 确保 pip 安装路径在 PATH 中
pip show zk-cli | grep Location
# 将对应的 Scripts 目录添加到 PATH
```

### 问题：模型下载慢

```bash
# 设置 HuggingFace 镜像（中国用户）
export HF_ENDPOINT=https://hf-mirror.com
zk init
```

### 问题：Windows 控制台乱码

```bash
# 设置 UTF-8 编码
chcp 65001
```

---

## 🛤️ 路线图

- [x] 基础 CLI 功能 (Issue #3)
- [x] 语义搜索
- [x] 知识图谱 (Issue #4)
- [x] 双向链接
- [x] 文件监控
- [x] 多知识库管理 (Issue #11)
- [x] Kimi Skill 集成 (Issue #5)
- [x] 性能优化 (Issue #6)
- [ ] Web 界面
- [ ] 移动端支持
- [ ] 数据同步

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

```bash
git clone https://github.com/zhuxixi/jfox.git
cd jfox/zk-cli
uv sync --extra dev
uv run pytest tests/
```

---

## 📄 许可证

MIT License - 详见 [LICENSE](../LICENSE)

---

## 🙏 致谢

- [sentence-transformers](https://www.sbert.net/) - 文本嵌入
- [ChromaDB](https://www.trychroma.com/) - 向量数据库
- [NetworkX](https://networkx.org/) - 图算法
- [Typer](https://typer.tiangolo.com/) - CLI 框架
- [Rich](https://rich.readthedocs.io/) - 终端美化

---

> 💡 **提示**：Zettelkasten 的核心不在于工具，而在于持续记录和链接知识的习惯。开始写第一条笔记吧！
