---
name: jfox-admin
description: |
  Use when user wants to perform system-level maintenance on JFox: performance monitoring,
  embedding model download, or self-update. Triggers on "jfox 维护", "性能报告", "清理模型缓存",
  "下载模型", "embedding model", "jfox update", "升级 jfox", "self update", "perf report",
  "perf clear-cache", "model download", "jfox 升级", "jfox 管理员工具".
---

# JFox 系统维护

处理 JFox 运行环境层面的维护任务：性能监控、嵌入模型下载、CLI 自升级。这些命令不直接操作笔记内容，而是保障 JFox 整体运行效率与版本新鲜度。

## 前置条件

确认 jfox 已安装：

```bash
jfox --version
```

未安装时：`uv tool install jfox-cli`

> 本技能复用 `/skill:jfox-manage` §4.1 的共享约定（`--json` 等价于 `--format json`）。下文示例统一使用 `--json`。

## 1. 性能监控

### 查看性能报告

```bash
jfox perf report
```

输出一个表格，统计各类操作（如嵌入生成、搜索、索引、笔记保存等）的：

- **Count**：调用次数
- **Avg (s)**：平均耗时
- **Total (s)**：累计耗时

用途：
- 批量导入后发现整体变慢，定位是 embedding 慢还是 BM25/向量索引慢
- 对比优化前后的耗时变化
- 排查 daemon 是否真正减少了重复加载模型的开销

### 清理模型缓存

```bash
jfox perf clear-cache
```

清除 embedding 模型在本地的缓存文件。适用场景：

- 磁盘空间紧张，想释放模型缓存
- 切换了 embedding 模型后，旧模型缓存仍占用空间
- 模型文件损坏，需要强制重新下载

> 清理后下次调用 embedding 相关命令（如搜索、添加笔记）会重新下载/加载模型；如果 daemon 正在运行，建议先 `jfox daemon stop`。

## 2. 模型下载

### 下载默认模型

```bash
jfox model download
```

自动按当前配置或设备选择默认模型（通常是 `sentence-transformers/all-MiniLM-L6-v2` 或其替代）。

### 下载指定模型

```bash
jfox model download --model BAAI/bge-m3
```

### 强制重新下载

```bash
jfox model download --force
```

### JSON 输出

```bash
jfox model download --json
```

> 通常不需要手动调用。`jfox daemon start` 会自动按需下载模型。手动下载适用于：
> - 首次安装后想提前把模型拉下来，避免后续命令冷启动
> - 国内网络环境，想先单独验证模型下载链路
> - 需要指定非默认模型时

## 3. 自升级

### 升级到最新版

```bash
jfox update
```

自动检测并升级到 PyPI 上的最新版本。输出包含：

- 当前版本
- 安装方式（pip/uv/dev）
- 执行的升级命令
- 升级结果

### JSON 输出

```bash
jfox update --json
```

### 开发安装的特殊处理

如果当前 jfox 是以 `-e` / 可编辑模式安装的 dev 版本，`jfox update` 会提示无法自动升级，需要用户手动 `git pull` 后用 `uv pip install -e .` 或 `pip install -e .` 重装。

## 4. 何时调用本技能

| 用户说的 | 对应操作 |
|---------|---------|
| "jfox 怎么升级" / "升级 jfox" | `jfox update` |
| "下载 embedding 模型" / "模型缓存" | `jfox model download` / `jfox perf clear-cache` |
| "jfox 好慢" / "性能报告" / "看看哪里慢" | `jfox perf report` |
| "清理模型缓存" | `jfox perf clear-cache` |

## 5. 命令参考速查

```bash
jfox perf report                          # 性能报告
jfox perf clear-cache                     # 清除模型缓存
jfox model download                       # 下载默认 embedding 模型
jfox model download --model <model>       # 下载指定模型
jfox model download --force               # 强制重新下载
jfox update                               # 自升级到最新版
jfox update --json                        # JSON 格式输出升级结果
```

## 6. 错误处理

| 场景 | 处理方式 |
|------|---------|
| `jfox model download` 失败 | 按 CLI 提示的手动下载命令执行；或检查 `HF_ENDPOINT` 是否配置了镜像站（如 `https://hf-mirror.com`） |
| `jfox update` 提示 dev 安装 | 手动拉取源码后执行 `uv pip install -e .` 或 `pip install -e .` |
| `jfox perf clear-cache` 后搜索变慢 | 正常现象，第一次搜索会重新加载模型；建议启动 daemon 避免后续重复加载 |
| 模型下载后 daemon 仍报模型缺失 | 重启 daemon：`jfox daemon restart` |

## 7. 与相关 skill 的关系

- 知识库/笔记/健康检查/daemon 的日常管理见 `/skill:jfox-manage`
- 搜索、查询、链接推荐见 `/skill:jfox-search`
- 本技能专注系统级维护：perf / model / update
