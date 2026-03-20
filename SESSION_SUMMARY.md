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

### Issue #4: Advanced Features ✅ 已完成
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

*会话总结自动生成*
