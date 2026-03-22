# JFox 项目会话记录

## 会话时间
2026-03-20 ~ 2026-03-21

## 项目起源

### 最初的问题
用户询问 "neotron" 单词的含义（拼写可能有误）。

**答案：**
1. **Neutron（中子）** - 物理学中的亚原子粒子，位于原子核中，不带电荷
2. **Neotron** - 一个基于 ARM Cortex-M 处理器的复古风格开源计算机项目，使用 Rust 编写

---

## 项目定义

### 项目目标
开发一个**个人知识库软件**，基于 **Zettelkasten（卡片盒）** 思想。

### 命名决策

**选定名称：JFox**

**命名理由：**
- **J** - 取自创始人名字 "Jiefeng" 的首字母
- **Fox** - 
  - 谐音 "Box"（盒子），呼应卡片盒的本质
  - 狐狸（Fox）象征聪明、机敏，契合知识管理工具的定位
  - 发音简洁好记

---

## 开发进展

### Issue #3: CLI Core MVP ✅ 已完成
实现了基础 CLI 功能：
- `init` - 初始化知识库
- `add` - 添加笔记
- `search` - 语义搜索
- `list` - 列出笔记
- `status` - 查看状态
- CPU-only embedding 后端（sentence-transformers）

### Issue #7: Simplify to CPU-only ✅ 已完成
- 移除 NPU/GPU 复杂逻辑
- 简化为纯 CPU 后端
- 性能：1.6ms/text，约 600 texts/sec

### Issue #4: Advanced Features ✅ 已完成 (已关闭)
https://github.com/zhuxixi/jfox/issues/4

实现了高级功能：

#### 1. 知识图谱 (graph.py)
- NetworkX 驱动的有向图
- 自动反向链接生成
- 图遍历和最短路径
- 孤立笔记检测
- Hub 节点分析

#### 2. 文件监控 (indexer.py)
- Watchdog 实时监控
- 自动索引更新
- 索引完整性验证

#### 3. 新 CLI 命令
| 命令 | 功能 |
|------|------|
| `zk query <text>` | 语义搜索 + 图谱联合查询 |
| `zk graph --stats` | 图谱统计 |
| `zk graph --orphans` | 孤立笔记 |
| `zk daily` | 今日笔记 |
| `zk inbox` | 临时笔记 |
| `zk index status/rebuild/verify` | 索引管理 |
| `zk delete <id>` | 删除笔记 |
| `zk refs --search/--note` | 查看引用关系 |

#### 4. 双向链接 `[[...]]` 支持 🆕
- 人类友好的引用格式：`[[笔记标题]]`
- 自动解析并建立链接关系
- 自动维护反向链接
- 支持标题模糊匹配

**示例：**
```bash
zk add "深度学习是 [[机器学习概述]] 的一个分支..." --title "深度学习" --type permanent
# 自动识别 "机器学习概述" 并建立链接
```

---

## 笔记格式

```markdown
---
id: '20260321013131'
title: 深度学习介绍
type: permanent
created: '2026-03-21T01:31:31'
updated: '2026-03-21T01:31:31'
tags: []
links:
- 20260321011528        # 正向链接
backlinks: []            # 反向链接（自动生成）
---

# 深度学习介绍

深度学习是 [[机器学习概述]] 的一个分支...
```

---

## 技术栈

- **CLI**: Typer + Rich
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **Vector DB**: ChromaDB
- **Graph**: NetworkX
- **File Watch**: Watchdog
- **Python**: >=3.10

---

### Issue #8: 完善 README 文档 ✅ 已完成
- 重写了完整的 README.md
- 包含所有 11 个 CLI 命令的详细说明
- 双向链接使用指南
- 知识图谱指标解释
- 快速开始教程
- 故障排除指南
- 性能基准测试

### Issue #11: 多知识库管理 ✅ 已完成
- `zk kb` 命令组：list, create, switch, remove, info, rename
- 全局配置存储在 ~/.zk_config.json
- 支持多个独立知识库

### Issue #10: 集成测试框架 ✅ 已完成
- tests/utils/temp_kb.py - 临时知识库管理
- tests/utils/zk_cli.py - CLI 命令封装
- tests/utils/note_generator.py - 测试数据生成
- tests/conftest.py - pytest fixtures
- tests/test_integration.py - 集成测试

### Issue #5: Kimi Skill 集成 ✅ 已完成
- `zk mcp` 命令启动 MCP Server
- MCP 接口：search_notes, add_note, get_note, list_notes, get_kb_info, find_related
- STDIO 模式用于 Kimi Skill

### Issue #6: 性能优化 ✅ 已完成
- `zk bulk-import` - 批量导入笔记
- `zk perf` - 性能工具和报告
- ModelCache - 模型缓存（5分钟TTL）
- BatchProcessor - 批量处理优化

---

## 下一步行动
- [x] Issue #4 高级功能实现
- [x] Issue #8 完善 README 文档
- [x] Issue #11 多知识库管理
- [x] Issue #10 集成测试框架
- [x] Issue #5 Kimi Skill 集成
- [x] Issue #6 性能优化
- [ ] Web 界面
- [ ] 移动端支持

---

## Issue #24: 知识融合完整工作流 ✅ 已创建
https://github.com/zhuxixi/jfox/issues/24

**核心问题**：从 Inbox 到融入知识网络的完整流程设计

**Zettelkasten 标准工作流：**
```
Capture → Process → Connect → Develop
(捕获)    (整理)    (连接)    (发展)
```

**建议的新命令：**
- `zk review` - 查看待整理队列（孤立笔记、过期 fleeting）
- `zk process` - 处理笔记（类型转换、完善内容、建立链接）
- `zk extract` - 从文献提取永久笔记

**关联：** Issue #12 (Agent 需要完整流程), #16 (suggest-links), #21 (templates)

---

## Issue #23: 链接发现策略设计 ✅ 已创建
https://github.com/zhuxixi/jfox/issues/23

**核心问题**：CLI 添加笔记时，如何自动发现与现有笔记的链接？

**讨论要点：**
- 语义相似度自动发现 (推荐)
- 标签驱动关联
- 图谱补全算法
- 自动 vs 手动 vs 混合策略

**关联：** Issue #16 (suggest-links), Issue #12 (Agent 工作流)

---

## Issue #12: Voice-to-Knowledge Workflow Design ✅ 已创建

**GitHub Issue:** https://github.com/zhuxixi/jfox/issues/12

### 背景
用户希望设计一套**语音输入 + AI Agent** 驱动的工作流程，而非直接使用 CLI。

### 核心场景设计（5个场景）
1. 💻 **代码开发知识沉淀** - 技术问题记录、解决方案归档
2. 📝 **会议/对话快速记录** - 会议纪要、任务追踪
3. 📚 **文献/文章阅读** - 读书笔记、知识摘录
4. 🔍 **项目复盘总结** - git 历史分析、决策记录
5. 💡 **日常灵感捕捉** - 快速记录、待整理想法

### 子 Issue 追踪

| Issue | 标题 | 优先级 | 状态 |
|-------|------|--------|------|
| #13 | Add `--kb` parameter to all note commands | **高** | 待实现 |
| #14 | Add `kb current` command | **高** | 待实现 |
| #15 | Extend MCP Server with KB management | **高** | 待实现 |
| #16 | Add suggest-links command | 中 | 待实现 |

### CLI 功能检查结果

| 功能 | 状态 | Agent 适用性 | 备注 |
|------|------|-------------|------|
| `zk init --name` | ✅ | ✅ 满足 | Agent 可直接调用 |
| `zk kb switch` | ✅ | ⚠️ 需改进 | 需要显式切换，容易混淆 |
| `zk add` | ✅ | ⚠️ 需改进 | 缺少 `--kb` 参数 (Issue #13) |
| `zk search` | ✅ | ✅ 满足 | MCP `search_notes` 可用 |
| `zk query` | ✅ | ✅ 满足 | 语义+图谱联合搜索 |
| MCP Server | ✅ | ⚠️ 需扩展 | Issue #15 |

### 立即可用的 Agent 工作流

```python
class ZKAgent:
    async def add_note(self, content: str, kb: str = "default", **kwargs):
        # 临时切换到目标知识库
        await self.run(f"zk kb switch {kb}")
        # 执行添加
        return await self.run(f'zk add "{content}" --type fleeting')
```

### 下一步
- 实现 Issue #13: `--kb` 参数
- 实现 Issue #14: `kb current` 命令
- 实现 Issue #15: MCP Server 扩展

---

## 命令参考

### 知识库管理
```bash
zk init --name work --desc "工作笔记"    # 初始化命名知识库
zk kb list                                # 列出所有知识库
zk kb switch work                         # 切换默认知识库
zk kb info work                           # 查看知识库详情
```

### 笔记操作
```bash
zk add "内容" --title "标题" --type permanent   # 添加笔记
zk search "查询"                               # 语义搜索
zk query "查询" --depth 2                      # 联合搜索
zk refs --search "关键词"                      # 查看引用
```

### MCP Server
```bash
zk mcp    # 启动 MCP Server (STDIO 模式)
```

---

*会话总结自动生成*
### Issue #9: Obsidian CLI 调研 ✅ 已更新 (子 Issue 已拆分)
https://github.com/zhuxixi/jfox/issues/9

**子 Issue 追踪：**

| Issue | 标题 | 优先级 | 说明 |
|-------|------|--------|------|
| #17 | Hybrid Search: BM25 + Semantic | **高** | BM25 混合搜索 |
| #18 | Multi-format Output Support | **高** | csv, yaml, paths 格式 |
| #19 | TUI Mode | 中 | 交互式界面 |
| #20 | HTTP API Server | 中 | 外部工具访问 |
| #21 | Template System | 中 | 快速创建标准化笔记 |
| #22 | OCR & PDF Extraction | 低 | 非文本内容索引 |

**当前优势：**
- ✅ 语义搜索 (ChromaDB 持久化)
- ✅ NetworkX 知识图谱
- ✅ Watchdog 文件监控
- ✅ 多知识库管理

---

*最后更新: 2026-03-22*
