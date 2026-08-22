# #263 夜间全量测试 cronjob — 设计文档（spec）

> issue: zhuxixi/jfox#263 ｜ 前置 #338（KB 备份恢复，PR #339 已合 2026-07-27）
> 设计已于 2026-07-28 经 brainstorming 与用户确认后落仓

## 1. 背景与目标

GitHub CI 每次只跑 test-fast（unit + 部分 integration），不跑全量；runner 也慢。JFox 功能迭代频繁，需要更严的回归保障。本 issue 在**本机**定时跑全量测试（含 performance / bulk / slow / integration / embedding），失败自动提 GitHub Issue，成功静默。

**成功标准**：每周二 09:00 自动跑一次全量测试；失败时自动开/复用带 `nightly-test-failure` label 的 issue 且内容足以定位失败；测试全程不污染 main 分支、不污染真实 KB 与用户配置；前置备份未完成时安全跳过。

## 2. 关键决策（含理由与事实依据）

| # | 决策 | 理由 / 事实依据 |
|---|---|---|
| D1 | **形态 = 仓内 bash 脚本 + 系统 crontab**，不用 agent / zima PJob / hermes | 夜间测试是纯机械任务（跑 pytest、提 issue），无语义判断环节，不需要 LLM。agent 是杀鸡用牛刀且引入不稳定性。`claude-md-refresh` 用 agent是因为核心是「哪些 commit 值得写进 CLAUDE.md」的语义判断——本 issue 无此环节。 |
| D2 | **定时器 = 系统 crontab**（非 hermes） | 仿 `md_review_gate.py` 的 `0 4 * * *` 系统cron范式。最原生、零抽象层。hermes 的 stdout 投递语义用不上（通知走 gh issue）。 |
| D3 | **频率 = 每周二 09:00**（`0 9 * * 2`） | 每周一次平衡回归发现速度与资源/噪声。09:00 = 每日 08:00 定时备份（#338）完成后。 |
| D4 | **备份兜底 = 脚本开头查 backup state** | 读 `~/.jfox-backup/state.json`（#338 `loop.py:42-48`：`{last_run: ISO时间, last_ok: bool, last_archive}`）。要求 `last_ok == true` 且 `last_run` 日期 == 今天；否则 skip 并在 stdout 告警（不提 issue——issue 是测试失败专用）。不重复触发备份。 |
| D5 | **失败通知 = 只 gh issue**（label `nightly-test-failure` + 失败签名去重） | issue 原文只要求「失败自动提 Issue」。同一失败签名连续出现 → 复用 open issue 追加评论，不刷屏。 |
| D6 | **测试时 daemon 不停，测试复用 daemon** | agent 查实：daemon 在跑时（PID 100675/18700），走子进程 CLI 的 embedding 测试会复用 daemon（HTTP `/encode`），不抢 GPU。**不可设 `JFOX_DAEMON_PROCESS=1`**（反而让测试各自 spawn 模型抢 GPU）。 |
| D7 | **换假 HOME 隔离**（`temp_kb` 不够） | agent 查实：`temp_kb` 只重定向 `ZK_KB_ROOT`（`conftest.py:23-24`），但 `~/.zk_config.json`（`DEFAULT_CONFIG_PATH` 不读 env，`global_config.py:19`）、`~/.jfox_daemon.pid/log`、`~/.jfox-backup/` 都没隔离；`cli` fixture 会真写 `~/.zk_config.json`。原 `run_full_test.ps1` 会**删真实 `~/.zk_config.json`**——必须避免。 |
| D8 | **gem_synth / auto-summary 不暂停** | D6 已确认测试复用 daemon 不抢 GPU。gem_synth 抢编码带宽会拖慢测试、往真实 KB 写 candidate，但每周才跑一次、可容忍；暂停需改 `enabled`（gem_synth 无 CLI，靠 `jfox-gem-synth-toggle`）增加复杂度，不值得。 |

## 3. 架构

```
系统 crontab (0 9 * * 2)
      │  继承用户 HOME；脚本内 export PATH
      ▼
scripts/nightly_test.sh  ← 仓内，走 PR，全权负责
      │
      ├─ 0. flock 单飞（仿 md_review_gate.py:28-33）
      ├─ 1. 前置检查：backup last_ok（D4）＋ git/uv/gh 可用性
      ├─ 2. fetch origin/main → git worktree add 临时 worktree
      ├─ 3. export HOME=沙箱 + HF_HOME=真实缓存（D7，避免重下 bge-m3）
      ├─ 4. cd worktree → uv sync --frozen
      ├─ 5. uv run pytest tests/ -v --tb=short（全量 ~1249，pytest.ini addopts 已含）
      ├─ 6a. 成功 → 删 worktree → 静默 exit 0（stdout 空）
      └─ 6b. 失败 → 提取摘要 → gh issue 去重（D5）→ 删 worktree → exit 1
```

无 agent、无 zima PJob、无独立 gate 脚本——准入逻辑（flock + 备份检查）在 bash 脚本开头。

## 4. 组件契约：`scripts/nightly_test.sh`

仓内新增，bash，`set -euo pipefail`。可被 crontab 直接调用，也支持 `--dry-run`（人造失败，验证 issue 提交流程）和 `--keep-worktree`（调试）。

**步骤契约**：

1. **环境自举**：`export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"`；定位 `gh`/`uv`/`git`，缺失则报错退出（算脚本自身故障，提 issue）。
2. **flock 单飞**：`flock -n /tmp/jfox-nightly-test.lock`，占用失败直接 exit 0（上一轮还在跑）。
3. **备份前置检查**：读 `~/.jfox-backup/state.json`（#338 `loop.py:42-48`）。state schema = `{last_run: ISO时间, last_ok: bool, last_archive}`。要求 `last_ok == true` **且** `last_run[:10] == 今天`；不满足 → skip，stdout 打 `SKIP: backup not confirmed (last_run=<...>, last_ok=<...>)`，exit 0。
4. **fresh worktree**：在主仓库 `git fetch origin main` → `git worktree add "$TMPDIR/jfox-nightly-$(date +%s)" origin/main`（detached 或新分支 `nightly-test/<ts>`，绝不 checkout 到本地 main）。
5. **换假 HOME**：`SANDBOX=$(mktemp -d)` → `export HOME="$SANDBOX"` → `export HF_HOME="$REAL_HOME/.cache/huggingface"`（保留已缓存 `BAAI/bge-m3` ~2GB，避免重下；也 export `HF_HUB_CACHE` 等同类路径指回真实缓存）。
6. **装依赖**：`cd worktree && uv sync --frozen --extra dev`（守 lockfile，不漂移）。
7. **跑测试**：`uv run pytest tests/ -v --tb=short -ra`（pytest.ini 已含 `timeout=120`/`--strict-markers`）。捕获 stdout+exit code 到日志文件。
8. **清理**：`git worktree remove --force` + `rm -rf "$SANDBOX"`（finally 语义，无论成败）。
9. **结果分发**：
   - exit 0 → 静默（stdout 空，便于将来若切 hermes 的「空=静默」语义）。
   - exit ≠ 0 → `gh issue` 去重提 issue（见 §5）。

## 5. 失败处理与 issue 去重

**失败签名**（决定「连续失败复用」怎么判同）：从 pytest 输出提取失败的 test nodeid 集合（`FAILED tests/xxx.py::TestClass::test_yyy`），排序去重后取**前 10 个** join，再 sha1 取前 12 位作为 `signature`。标题用「首个失败 nodeid」便于人眼速读。

**issue 标题**：`nightly-test 失败 <YYYY-MM-DD 周二> [sig:<signature>]`

**issue label**：`nightly-test-failure`（issue 标签需先在仓库存在；脚本首次运行前手工建一次，或脚本里 `gh label create nightly-test-failure --if-not-exists`）。

**去重逻辑**：

- `gh issue list --repo zhuxixi/jfox --label nightly-test-failure --state open --search "sig:<signature>" --json number,title`
- 命中 open issue → `gh issue comment <num> --body "<本次失败摘要 + 复现于 <时间>>"`（追加，不新开）
- 未命中 → `gh issue create --title "..." --label nightly-test-failure --body "..."`

**issue body 模板**（bash heredoc 填充）：

- 失败时间、commit SHA（`origin/main` 的）、signature
- 失败 test 列表（前 10，含 nodeid）
- traceback 摘要（`--tb=short` 输出，截断到合理长度，如 200 行 / 8KB）
- 完整日志位置（crontab 重定向的日志文件路径，供人工查）
- 一句「这是 #263 夜间全量测试自动提交」+ issue 链接

**降级**：`gh issue create/comment` 本身失败（网络、认证、rate limit）→ 不阻塞脚本退出，stderr 打印告警 + 写本地 `$HOME/.jfox-nightly-test/failed-<ts>.log`（兜底留痕，下次人工查）。

## 6. crontab 行与环境注意

```
# 每周二 09:00 跑 jfox 夜间全量测试（#263）
0 9 * * 2 /home/elling/git-repo/github/jfox/scripts/nightly_test.sh >> /home/elling/.jfox-nightly-test/cron.log 2>&1
```

- crontab 环境极简（PATH 只有 `/usr/bin:/bin`，无 shell profile）→ 脚本内必须 `export PATH` 含 `gh`/`uv`/`git`。
- `HOME`：crontab 默认 = 用户 HOME（OK），脚本会自己 export 到沙箱。
- gh 认证：依赖 `~/.config/gh/hosts.yml`（token）或 `GH_TOKEN` env。脚本内 `gh auth status` 自检，失败则按 §5 降级写本地。验证 token 未过期。
- 日志目录 `~/.jfox-nightly-test/` 需存在（脚本 mkdir -p）。

## 7. 测试范围

全量 `uv run pytest tests/`（不加 `-m`，所有 marker 都跑）。实测 ~1249 个测试（embedding 48 个最慢，复用 daemon）。**含 performance / bulk / slow**——这些噪声大可能偶发失败触发 issue，但 issue 要求全量，且每周才跑一次、可容忍；若某 performance 测试长期 flaky，作为 issue 之外的后续优化项处理（见 §9 非目标）。

## 8. 隔离与安全网（汇总）

| 风险 | 防护 |
|---|---|
| 污染 main 分支 | fresh worktree from `origin/main`，绝不 checkout 本地 main |
| 污染真实 KB 数据 | `temp_kb` fixture 已重定向 `ZK_KB_ROOT`（conftest.py:23-24）+ 脚本换假 HOME 双保险 |
| 污染 `~/.zk_config.json`/pid/backup | 换假 HOME（D7） |
| 测试崩溃留残 `test_*` KB 注册 | conftest 会话级 cleanup（conftest.py:285-312）+ 假 HOME 兜底 |
| GPU 抢占 | 复用 daemon（D6），不设 `JFOX_DAEMON_PROCESS=1` |
| 重下 bge-m3 模型 | `HF_HOME` 指回真实缓存（§4 步骤 5） |
| 备份未完成就跑测试 | 脚本开头查 `last_run` + `last_ok`（D4） |
| 多实例并发 | flock 单飞 |
| gh 提 issue 失败 | 降级写本地日志（§5） |

## 9. 非目标（out of scope）

- 不用 agent / zima PJob（D1）
- 不判断 flaky / 不尝试自动修复失败（纯「跑+报告」）
- 不改 cosmobo schedule / 不新增 zima cycleType
- 不推飞书（只 gh issue）
- 不暂停 gem_synth / auto_summary（D8）
- 「重复初始化慢」「语义测试按改动跳过」「GPU 加速落地」——前序讨论（KB `202606211557467205`）已识别为本 issue 之外的后续优化项

## 10. 验收 / dry-run

- `scripts/nightly_test.sh --dry-run`：跳过真实 pytest，人造一个失败签名，走完整 `gh issue` 去重流程，验证 issue 被正确创建（首次）+ 复用（第二次 dry-run 同签名）。跑完手工 close/delete 该测试 issue。
- 手工触发一次真实全量跑（`scripts/nightly_test.sh`），确认成功静默、worktree 清理干净、假 HOME 沙箱删除、不碰真实配置。
- 确认 crontab 行加上后，下次周二 09:00 自动触发（或 `run-parts` 模拟）。

## 11. 待 plan 阶段细化的实现点

- 失败 test nodeid 提取的 awk/grep 精确模式（依赖 pytest `-ra` 的 `FAILED` 汇总行格式）
- traceback 截断长度与日志留存策略（保留多少次历史）
- `uv sync` 在 worktree（非主仓）首次是否需要额外 `--project` 指向
- 假 HOME 下是否需要软链 `~/.cache`、`~/.config/gh`（gh 认证）等到真实路径，避免 gh/HF 找不到——倾向 `export` 指回而非软链
- issue label 是否要带颜色/description
