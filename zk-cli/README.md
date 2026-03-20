# ZK CLI - Zettelkasten 知识管理工具

针对 Intel Core Ultra 7 258V (Lunar Lake) 优化的个人知识管理系统，利用 NPU 4.0 (47 TOPS) 进行语义检索加速。

## 功能特性

- 📝 **笔记管理** - 闪念笔记、文献笔记、永久笔记
- ⚡ **NPU 加速** - OpenVINO 集成，自动设备检测
- 🔍 **语义检索** - ChromaDB 向量数据库
- 🔗 **知识图谱** - NetworkX 链接关系
- 🎯 **语音集成** - Kimi Skill 支持

## 安装

```bash
pip install -e .
```

## 快速开始

```bash
# 初始化知识库
zk init

# 添加笔记
zk add "这是一个测试笔记" --title "测试笔记"

# 语义搜索
zk search "关键词"

# 查看状态
zk status
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `zk init` | 初始化知识库 |
| `zk add <content>` | 添加笔记 |
| `zk search <query>` | 语义搜索 |
| `zk status` | 查看知识库状态 |

## 依赖

- Python >= 3.10
- Intel NPU 驱动 (可选，用于加速)

## 许可证

MIT
