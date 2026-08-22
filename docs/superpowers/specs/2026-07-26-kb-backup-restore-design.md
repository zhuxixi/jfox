# Spec: JFox KB 滚动备份 + 恢复（Issue #338）

> #263 夜间全量测试的前置依赖。备份验证万无一失后，才开跑 9 点测试。
> **架构（2026-07-26 定稿）**：做成 jfox 自带能力——新包 `jfox/backup/`（`BackupManager` + daemon 调度 loop + CLI），**由 jfox daemon 自己定时调度**（镜像 auto-summary，不走 Hermes/zima）。理由：随 jfox 发布、与 gem-synth/auto-summary 一致、无外部依赖；可进 pytest（沙箱演练变自动化测试）。

## 1. 目标 & 范围

**做什么**：给 jfox 加 `backup`/`restore` 能力；**daemon 内 backup_loop 每天 08:00 自动备份**，滚动留 7 份；恢复可逆；pytest 通过为验收硬门槛。

**备什么**（jfox 全部用户状态）：

- `~/.zettelkasten`（全部知识库：笔记、链接、ChromaDB 语义索引、bm25 索引，~256MB）
- `~/.zk_config.json`（全局配置：KB 注册表 + 当前 KB）

**不备什么**（非目标，见 §7）：模型缓存、daemon 日志、offsite/云备份、加密归档。

## 2. 决策表（brainstorming + 修订，2026-07-26）

| 维度 | 决策 | 依据 |
|------|------|------|
| **触发/调度** | **jfox daemon 内 backup_loop**，每天 config.schedule_time（默认 08:00）跑 | 镜像 auto-summary（daemon/server.py `_maybe_start_*` + `xxx_loop` + schedule.py）；随包发布、无外部依赖 |
| **形态** | 新包 `jfox/backup/`（manager/loop/schedule/cli）+ daemon server 接线 + cli.py 命令 | 与 gem_synth/auto_summary 同构 |
| **失败通知** | **状态型**：daemon 日志 + `jfox backup status` 看（last_run/next_run/快照数/上次成败） | daemon 不发飞书、zima 也不发；飞书推送留给 #263 测试失败 |
| 保留 | 滚动 7 份日备，超期删最旧 | 一周窗口够回溯 |
| 格式 | 自包含 `tar.gz` + 同名 `.manifest.json` | 便携、可校验 |
| 路径 | `~/.jfox-backup/daily/jfox-YYYYMMDD-HHMMSS.tar.gz` | 集中、可预测 |
| **一致性** | **quiesce 标志**：备份期间 gem_synth/auto_summary loop 跳过写 tick + ChromaDB 崩溃一致（SQLite WAL） | backup 跑在 daemon 内、不能停 daemon 自己；置标志让兄弟 loop 不写 → ChromaDB 静默 → 文件级 tar 可恢复 |
| 校验 | 创建即 `tar -tzf` + sha256 入清单；restore 前重算比对 | 杜绝"恢复时才发现归档坏" |
| 恢复 | **可逆**：当前态 rename 旁置（瞬时）→ 校验归档 → 解压到位；失败 rename 回 | restore 是独立 CLI 进程，可停 daemon 拿干净快照 |
| 配置 | `~/.zk_config.json`：`backup.enabled`(默认 false)/`schedule_time`("08:00")/`retain`(7) | 同 auto_summary config 风格 |

## 3. 组件契约

### 3.1 `jfox/backup/manager.py` — `BackupManager`（核心逻辑）

```python
class BackupManager:
    def __init__(self, backup_root=~/.jfox-backup, kb_root=~/.zettelkasten,
                 config_path=~/.zk_config.json, retain=7): ...
    def backup(self) -> Path:        # 置quiesce→tar→manifest→校验→轮转→清quiesce；返回归档路径
    def restore(self, snapshot, yes=False) -> None:  # 停daemon→rename旁置→校验sha256→解压→起daemon→验证
    def list_snapshots(self) -> list[SnapshotInfo]: ...
    def verify(self, snapshot) -> bool:              # 重算sha256比对+tar -tzf
```

- 复用 `jfox/utils.py:atomic_write_json` 写 manifest；复用 global_config 路径解析。
- 并发锁：`~/.jfox-backup/.lock`（跨平台：fcntl Unix / msvcrt Windows），防 loop tick 与手动 `jfox backup run` 撞车。

### 3.2 `jfox/backup/loop.py` + `schedule.py`（daemon 调度，镜像 auto_summary）

- `backup_loop(stop_event)`：周期 tick，到 `schedule_time` 且今日未备份 → 调 `BackupManager.backup()`；记录 last_run/结果到状态文件供 `status` 读。
- `schedule.py`：`should_run_now(cfg, last_run)` —— 每日定点（默认 08:00），今日已跑则跳过。
- **quiesce 协调**：模块级 `BackupCoordinator.is_running` 标志；gem_synth_loop / auto_summary_loop 在写 tick 前检查、置位时跳过（**对既有 loop 加一处 flag 检查**，最小侵入）。

### 3.3 daemon 接线（`jfox/daemon/server.py`）

镜像 auto-summary：加 `_maybe_start_backup()` / `_maybe_stop_backup()`（`config.backup.enabled=true` 时 `asyncio.create_task(backup_loop(...))`）；起停钩子挂到 daemon start/stop。

### 3.4 CLI（`jfox/backup/cli.py` + `cli.py` 挂载）

```
jfox backup run [--quiet]              # 立即手动备份
jfox backup enable [--time 08:00] [--retain 7]   # 开 daemon 调度
jfox backup disable
jfox backup status                     # enabled? last_run/next_run/快照数/上次成败
jfox backup list
jfox backup verify <snapshot>
jfox restore <snapshot> [--yes]        # 人工恢复
```

按惯例加 `--format json` / `--kb`。

### 3.5 归档内部结构（自描述）

```
jfox-backup-YYYYMMDD-HHMMSS/
  zettelkasten/      # ~/.zettelkasten 全量
  zk_config.json     # ~/.zk_config.json
  manifest.json      # 同款清单（归档内也存一份）
```

manifest：`{version, created, jfox_version, archive, archive_sha256, kb_path, config_path, file_count, total_bytes}`

## 4. 数据流

### backup（daemon backup_loop 到点触发，或 `jfox backup run` 手动）

1. 取锁（取不到→跳过/退出，避免重叠）
2. **置 quiesce 标志**（gem_synth/auto_summary loop 跳过写 tick）—— 失败→跳到 7 报错，不快照
3. `tar czf <tmp> jfox-backup-.../`（`~/.zettelkasten` + `~/.zk_config.json`）
4. 算 sha256、写 manifest（`atomic_write_json`）、`tar -tzf` 验完整性
5. 原子 rename `<tmp>` → `~/.jfox-backup/daily/jfox-YYYYMMDD-HHMMSS.tar.gz`
6. 轮转：保留最新 7 份，删更旧
7. **清 quiesce 标志**（finally 兜底，无论成败）+ 写 last_run 状态
8. 默认打印确认 / `--quiet` 无 stdout；失败记 status + 日志（非 0 退出）

### restore（`jfox restore <snapshot>`，人工，独立 CLI 进程）

1. 预检：快照存在 + manifest 可读
2. **先停服**：`jfox daemon stop`（独立进程可停 daemon；避免它开着 ChromaDB 时目录被挪走）
3. **恢复前保险**：`~/.zettelkasten` → rename `~/.zettelkasten.pre-restore-<ts>`，`~/.zk_config.json` 同理（瞬时、不丢）
4. 重算归档 sha256 比对 manifest；不一致→**立刻 rename 回**、起 daemon、中止
5. 解压归档 → `zettelkasten/` 到 `~/.zettelkasten`、`zk_config.json` 到 `~/.zk_config.json`
6. `jfox daemon start` + 验证（`jfox list` KB 列表、笔记数）
7. 通过→保留 `.pre-restore-<ts>` 一份（轮转保留 1）；失败→rename 回、起 daemon、报错

## 5. 一致性 & 安全

- **隔离**：`backup`/`restore` 直接动真实 `~/.zettelkasten`（其职责）；恢复演练在 pytest 的 `temp_kb` fixture（天然沙箱），真实 KB 不动。
- **quiesce 保证（daemon 内定时备份）**：备份期间 gem_synth/auto_summary 不写 → ChromaDB 无并发写 → 文件级 tar 干净。**崩溃一致性机制**：ChromaDB 底层 SQLite+WAL，tar 拷贝含 `.wal` 文件，restore 重开时 SQLite 自动 replay WAL 恢复到一致点（无需显式 checkpoint/关闭 DB）；quiesce 进一步消除并发写，双保险。注：quiesce 标志仅同进程可见，故**手动 `run` 与 `restore`（独立进程）改走"停 daemon 拿干净快照"**，不依赖 quiesce。
- **原子性**：manifest 用 `atomic_write_json`；归档先 tmp 再 rename；restore 用 rename 旁置保证可逆。
- **不删源**：restore 只 rename 旁置、永不 `rm` 当前 KB。

## 6. 降级 / 错误处理

| 场景 | 行为 |
|------|------|
| quiesce 置位失败 / tar 失败 | 中止 backup，**不快照**，记 status + 日志，finally 清 quiesce |
| 磁盘满（tar 写失败） | 清 tmp，保留旧快照不删，记 status |
| 归档 sha256 不符（restore） | 立刻 rename 回当前态，不动任何东西，报错退出 |
| `~/.zettelkasten` 不存在 | backup 警告并跳过；restore 按归档内容建 |
| 并发触发（锁占用） | 后者直接退出，不重叠 |
| manifest 缺失/损坏 | `restore`/`verify` 拒绝该快照、报错 |
| daemon 没在跑（loop 不触发） | `jfox backup status` 显示 daemon 未运行；手动 `jfox backup run` 仍可用 |

所有失败路径保证：**真实 KB 不被破坏**。

## 7. 非目标

- ❌ offsite/云备份 ｜ ❌ 增量备份（每次全量）｜ ❌ 备模型缓存 ｜ ❌ 备 daemon/gem-synth 日志 ｜ ❌ 加密归档 ｜ ❌ 自动恢复（restore 永远人工+确认）｜ ❌ 飞书推送（daemon 不具备；留给 #263）

## 8. 验收（万无一失的证明）

**硬门槛 —— pytest 测试**（`tests/test_backup.py`，跑在 temp_kb 沙箱，CI 覆盖）：

- `test_backup_creates_archive_with_manifest_and_sha256`
- `test_backup_quiesces_siblings`（gem_synth/auto_summary 写 tick 被跳过）
- `test_restore_roundtrip`（temp_kb→backup→破坏→restore→笔记数一致）
- `test_restore_reversible_on_corrupt_archive`（sha256 不符→原状不动）
- `test_retention_rotates_to_7`
- `test_schedule_should_run_now`（到点/已跑/未到点）
**可选 —— 真机演练**（用户点头）：真实环境跑一次 `jfox restore`，靠 rename 旁置保险保底。

## 9. 接入（实现+测试通过后）

1. `jfox backup enable --time 08:00 --retain 7` → 写 config + 触发 daemon reload（或 restart）
2. daemon 起备份 loop；到点自动备份
3. `jfox backup status` 监控（last_run/next_run/快照数/上次成败）
（无 Hermes/zima 介入；纯 jfox 自洽。）

## 10. 交付物（PR 范围）

- `jfox/backup/`（manager.py / loop.py / schedule.py / cli.py / `__init__.py`）
- `jfox/daemon/server.py` 加 `_maybe_start_backup`/`_maybe_stop_backup` + 起停钩子
- gem_synth_loop / auto_summary_loop 加 quiesce flag 检查（最小侵入）
- config 加 `backup.{enabled,schedule_time,retain}`
- `cli.py` 挂载 backup/restore 命令
- `tests/test_backup.py`（沙箱演练 = 自动化测试）
- README/docs 一节：备份恢复用法 + 启用调度
- 不动既有存储/搜索逻辑，纯新增能力
