---
name: jfox-auto-summary
description: |
  Use when user wants to configure, run, or inspect JFox auto-summary for Claude Code sessions.
  Triggers on "自动总结", "auto-summary", "会话自动保存", "定时总结", "清理 ledger",
  "prune ledger", "jfox auto-summary", "claude 会话总结", "自动归档会话".
---

# JFox Auto-summary：Claude Code 会话自动总结

将本地 `~/.claude/projects` 下的 Claude Code 会话自动扫描、总结并写入 jfox 知识库。

## 前置条件

- 已安装 jfox CLI 并初始化知识库（详见 `/skill:jfox-manage`）
- 已安装 Claude Code（`claude` 命令在 PATH 中）
- auto-summary 依赖 `claude -p` 生成摘要；生成的最终笔记写入本地知识库

> 本技能复用 `/skill:jfox-manage` §4.1 的共享约定（`--kb` / `--json` / `--content-file`）。下文命令示例统一使用 `--json`（等价于 `--format json`）。

## 1. 查看状态

```bash
jfox auto-summary status --json
```

输出包含：

- 当前启用状态（enabled）
- 扫描间隔（interval_minutes）
- session 结束判定阈值（idle_threshold_minutes）
- 目标知识库（target_kb）
- 单轮最多处理数（max_per_tick）
- session 大小过滤与过期跳过阈值
- ledger 文件路径与状态分布
- 当前可扫描 session 的处理进度（总数/成功/跳过/待处理/失败）

## 2. 启用与配置

### 2.1 基本启用

```bash
jfox auto-summary enable
```

启用后，需启动 daemon 才会在后台定时运行：

```bash
jfox daemon start
```

> daemon 启动逻辑及 `--enable-auto-summary` / `--no-auto-summary` 选项详见 `/skill:jfox-manage` §6。

### 2.2 启用时调整参数

```bash
# 调整扫描间隔（分钟）和静默阈值（分钟）
jfox auto-summary enable --interval 30 --idle-threshold 60

# 指定写入目标知识库
jfox auto-summary enable --kb work

# 限制每轮最多处理 session 数
jfox auto-summary enable --max-per-tick 3
```

- `--interval`：daemon 后台扫描间隔，>=1 分钟
- `--idle-threshold`：判定 session 已结束的 mtime 静默时间，>=1 分钟
- `--kb`：目标知识库名称，省略则使用 default
- `--max-per-tick`：每轮最多处理几个 session

### 2.3 调度窗口（可选）

限制 auto-summary 只在指定时间窗口内运行：

```bash
jfox auto-summary enable \
  --schedule-enabled \
  --schedule-weekday-window 0-6 \
  --schedule-weekend-window 0-8 \
  --schedule-timezone Asia/Shanghai
```

- `--schedule-enabled/--no-schedule-enabled`：开关时间窗口
- `--schedule-weekday-window`：工作日窗口，格式 `开始小时-结束小时`，如 `0-6`
- `--schedule-weekend-window`：周末窗口，格式同上
- `--schedule-timezone`：时区，默认 `Asia/Shanghai`

## 3. 禁用

```bash
jfox auto-summary disable --json
```

禁用后 daemon 会停止后台循环，但 ledger 不会被清空。要重新处理已记录的 session，见 §6 `forget` 与 §7 `prune`。

## 4. 扫描待处理 session

```bash
jfox auto-summary scan --json
```

列出当前会被处理的 session（dry-run 视图），包含 project 名、session_id、大小、修改时间和静默时长。

## 5. 手动触发总结

### 5.1 实际执行

```bash
jfox auto-summary run --json
```

不依赖 daemon，立即扫描并处理一轮。即使 auto-summary 处于禁用状态，`run` 仍会执行。

### 5.2 预览模式

```bash
jfox auto-summary run --dry-run --json
```

只扫描、不调用 `claude -p`，也不写入知识库，用于预览本轮会处理哪些 session。

### 5.3 详细输出

```bash
jfox auto-summary run --verbose --json
```

输出每条 session 的处理结果、生成笔记 ID 和失败原因。

## 6. 从 ledger 移除记录

```bash
jfox auto-summary forget <session_id>
```

`session_id` 支持完整 ID 或前缀。移除后，该 session 会在下次扫描时被重新处理。

适用场景：

- 某条 session 之前处理失败或被跳过，想重跑
- 想修改后再总结

## 7. 清理 ledger

```bash
# 清理 30 天前的 ledger 条目（默认）
jfox auto-summary prune

# 指定天数
jfox auto-summary prune --days 7 --json
```

`prune` 只删除 ledger 中过旧的记录，不会删除知识库里的笔记。ledger 文件路径可通过 `status` 查看。

## 8. 典型工作流

### 8.1 首次启用

```bash
jfox auto-summary enable --interval 30 --idle-threshold 60 --kb work
jfox daemon start
jfox auto-summary status --json
```

### 8.2 排查某条 session 未被总结

```bash
jfox auto-summary scan --json          # 查看是否在待处理列表
jfox auto-summary status --json        # 查看是否已被 success/skipped/failed
jfox auto-summary forget <session_id>  # 如需重跑，先移除 ledger 记录
jfox auto-summary run --verbose --json # 手动重跑并查看详情
```

### 8.3 定期清理

```bash
jfox auto-summary prune --days 30 --json
```

## 9. 隐私与使用边界

- **本地优先**：auto-summary 只扫描本地 `~/.claude/projects` 下的 session 文件，最终笔记写入本地 jfox 知识库。
- **不上传**：jfox 不会把原始 session 文件上传到任何 jfox 服务端或第三方云存储。
- **摘要生成方式**：启用后，实际摘要由本地调用的 `claude -p` 生成，会话文本会按 Claude Code 的正常机制与 Anthropic API 交互；相关隐私政策以 Claude Code/Anthropic 官方说明为准。
- **数据留存**：ledger 仅记录处理状态（session_id、状态、时间戳等），不保存完整会话内容。

## 10. 命令参考速查

```bash
# 状态
jfox auto-summary status --json

# 启用（可同时修改参数）
jfox auto-summary enable
jfox auto-summary enable --interval 30 --idle-threshold 60 --kb <name>
jfox auto-summary enable --schedule-enabled --schedule-weekday-window 0-6

# 禁用
jfox auto-summary disable --json

# 扫描待处理 session
jfox auto-summary scan --json

# 手动触发
jfox auto-summary run --json
jfox auto-summary run --dry-run --json
jfox auto-summary run --verbose --json

# ledger 管理
jfox auto-summary forget <session_id>
jfox auto-summary prune --days 30 --json
```

## 11. 错误处理

| 场景 | 处理方式 |
|------|---------|
| "Knowledge base not found" | 调用 `/skill:jfox-manage` 创建或切换知识库 |
| `auto-summary 已禁用` | 如需要后台调度，执行 `jfox auto-summary enable` 后再 `jfox daemon start` |
| `interval 必须 >= 1` / `idle-threshold 必须 >= 1` | 检查参数值是否为正整数 |
| ledger 条目匹配多个前缀 | 提供更长、唯一的 `session_id` 前缀 |
| `claude` 命令不在 PATH | 安装 Claude Code 或检查环境变量 |
