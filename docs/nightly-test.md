# 夜间全量测试（nightly-test）

> GitHub issue: zhuxixi/jfox#263 ｜ 前置依赖：#338 KB 备份恢复
> 设计文档：[`docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md`](superpowers/specs/2026-07-28-nightly-fulltest-design.md)

## 职责

一句话：**每周二 09:00 由系统 crontab 触发 `scripts/nightly_test.sh`，跑全量 pytest；失败自动开/复用带 `nightly-test-failure` label 的 GitHub issue，成功静默。**

CI 只跑 `test-fast`（unit + 部分 integration），不覆盖 performance / bulk / slow / embedding 全量；本脚本在本机补这块回归保障。

## 前置依赖（#338 备份）

脚本开头会读 `~/.jfox-backup/state.json`，要求**今天**的备份已成功（`last_ok == true` 且 `last_run` 日期 == 今天）。否则脚本打 `SKIP: 今日备份未确认` 并 `exit 0`（不提 issue——issue 是测试失败专用）。

因此必须先启用 #338 备份守护并让它在 **每天 08:00** 跑（早于本脚本 09:00 一小时）：

```bash
jfox backup enable      # 启用备份 daemon
jfox backup status      # 确认 last_ok=true、last_run 是今天
```

设计依据：[#338 backup `loop.py`](superpowers/specs/2026-07-26-kb-backup-restore-design.md) 的 `state.json` schema = `{last_run, last_ok, last_archive}`。

## 安装 crontab（本机操作，不进 PR）

crontab 行装在**运行机器的本机**，不进仓库。把下面这段在本机执行一次：

```bash
# 编辑 crontab，追加每周二 09:00 触发
crontab -l | { cat; echo "0 9 * * 2 /home/elling/git-repo/github/jfox/scripts/nightly_test.sh >> /home/elling/.jfox-nightly-test/cron.log 2>&1"; } | crontab -

# 确认
crontab -l | grep nightly_test
```

要点：

- `0 9 * * 2` = 每周二 09:00（系统本地时区）。09:00 选在每日 08:00 的 #338 备份之后。
- `>> cron.log 2>&1` 把脚本 stdout/stderr 拼到日志文件，失败 issue 里也会写完整日志路径，但 crontab 投递的 stdout 留在这以便排查脚本自身故障。
- 脚本内部已 `export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"`，crontab 的极简 PATH 不会影响 `gh`/`uv`/`git` 定位。

## label（无需手工建）

`nightly-test-failure` label 由脚本**首次运行时自动 `gh label create --force`**，无需手工预建。颜色 `D73B3B`（红色），描述「夜间全量测试（#263）自动失败」。

## dry-run（验证 issue 流程）

`--dry-run` 跳过真实 pytest，用人造失败输出（2 条 `FAILED ...`）走完 `report_failure` 全流程：算签名 → 查 open issue → 决定 create / comment → 调 `gh issue`。

```bash
./scripts/nightly_test.sh --dry-run
```

验收步骤（参见下方验收清单）：

1. **首次**跑 `--dry-run` → 日志出现 `新开 issue（签名 ...）`， stdout 打印新 issue URL。
2. **二次**跑 `--dry-run`（签名未变） → 日志出现 `复用 issue #<num>（同签名 ...）追加评论`， stdout 打印评论 URL。
3. 验完**务必关掉/删除**测试 issue（避免污染仓库）：

   ```bash
   gh issue close <num> --repo zhuxixi/jfox
   gh issue delete <num> --repo zhuxixi/jfox --yes   # 可选，彻底清理
   ```

> 注意：`--dry-run` **不**验证「换假 HOME + 缓存指回真实路径」这一段（见下节），因为假 HOME 与 uv 缓存重指向只在真实 `uv sync` / pytest 子壳里生效。dry-run 在进入子壳前就 return 了。要验证缓存复用，需跑一次真实成功（见验收清单）。

## 隔离与缓存复用（how it isolates）

脚本核心隔离机制是**换假 HOME** + 在假 HOME 下把缓存/全局配置指回真实路径，确保：

1. 不污染真实配置：`~/.zk_config.json`、`~/.jfox_daemon.pid/log`、`~/.jfox-backup/` 全部重定向到一次性沙箱目录（`$LOG_DIR/home-XXXXXX`），跑完 `rm -rf`。
2. 不重下大文件：假 HOME 下空缓存会让 `uv` 重下 Python 工具链 + 包缓存、让 HF 重下 `bge-m3` ~2GB。脚本在 `run_tests` 子壳里显式把三类缓存指回真实路径：

   | 环境变量 | 指向 | 作用 |
   |---|---|---|
   | `UV_CACHE_DIR` | `$REAL_HOME/.cache/uv` | uv 包缓存，避免每次 cron 重下依赖 |
   | `UV_PYTHON_INSTALL_DIR` | `$REAL_HOME/.local/share/uv/python` | uv 管理的 Python 工具链 |
   | `HF_HOME` | `$REAL_HOME/.cache/huggingface` | bge-m3 embedding 模型缓存（~2GB） |
   | `GIT_CONFIG_GLOBAL` | `$REAL_HOME/.gitconfig` | 防御性：让沙箱内任何 git 调用仍读到真实 git 配置（文件不存在也无害） |

3. 真实 HF 缓存缺失时会打 `WARN: HF cache ... 不存在，测试可能重下 bge-m3`，不再静默跳过——运维能从 `cron.log` 看到这个信号。

## 故障排查

### 现象：脚本一直 `SKIP: 今日备份未确认`

- **原因**：#338 备份未在今天 08:00 成功跑过（`state.json` 的 `last_ok != true` 或 `last_run[:10] != 今天`）。
- **处置**：

  ```bash
  jfox backup status                      # 看 last_run / last_ok
  jfox backup run                         # 手工补跑一次今天的备份
  cat ~/.jfox-backup/state.json           # 确认 last_ok=true 且 last_run 是今天
  ```

- 若从未启用备份：`jfox backup enable`。

### 现象：`WARN: gh 缺失` / `WARN: gh 未认证`

- **原因**：`gh` CLI 未装或未 `gh auth login`。脚本仍会跑完测试，只是失败时**降级**写本地告警文件（`$LOG_DIR/issue-body-<ts>.md`），不提 GitHub issue。
- **处置**：

  ```bash
  which gh || sudo apt install gh         # 或见 https://cli.github.com/
  gh auth status                          # 看认证状态
  gh auth login                           # 重新登录
  ```

### 现象：crontab 触发了但 `command not found: gh`/`uv`/`git`

- **原因**：crontab 环境极简，没继承交互 shell 的 PATH。脚本内部已 `export PATH="$REAL_HOME/.local/bin:$REAL_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"` 兜底，但如果这些工具装在别处（如 `/opt/...`），需改脚本第 33 行的 PATH。
- **处置**：`which gh uv git` 确认路径，若不在脚本 PATH 里，编辑 `scripts/nightly_test.sh` 顶部 PATH 导出。

### 现象：`SKIP: 另一个 nightly_test 正在跑`

- **原因**：`flock -n /tmp/jfox-nightly-test.lock` 单飞保护触发，上一轮还在跑（全量 ~50min，偶发重叠）。
- **处置**：通常无需干预，等上一轮跑完即可。若确认是死锁残留（lock 文件在但无进程）：`rm /tmp/jfox-nightly-test.lock`。

### 现象：每次 cron 都重下 bge-m3 / Python 工具链（很慢）

- **原因**：真实 HF 缓存或 uv 缓存路径被删/移动，或 `REAL_HOME` 判定错（脚本以启动时 `$HOME` 为 `REAL_HOME`）。脚本会在日志打 `WARN: HF cache ... 不存在`（HF 侧），但 uv 侧静默重下。
- **处置**：

  ```bash
  ls -d ~/.cache/huggingface ~/.cache/uv ~/.local/share/uv/python   # 确认缓存目录存在
  df -h ~/.cache                                                      # 确认没满
  ```

  若是首次启用、缓存还没建：手工跑一次 `jfox init` 或 `uv sync --extra dev` 把缓存预热好，再让 cron 接管。

### 现象：worktree 残留 / 沙箱 home 没删

- **原因**：脚本异常退出（如 kill -9）未触发 `trap cleanup EXIT`。
- **处置**：

  ```bash
  ls ~/.jfox-nightly-test/                                # 看残留的 worktree-* / home-XXXXXX
  git -C /home/elling/git-repo/github/jfox worktree prune # 清理 worktree 元数据
  rm -rf ~/.jfox-nightly-test/worktree-* ~/.jfox-nightly-test/home-*
  ```

  调试时可加 `--keep-worktree` 保留 worktree 以便排查。

## 验收清单

在合并 / 正式启用前逐项勾选：

- [ ] `scripts/nightly_test_helpers.py` 单测全绿（`uv run pytest tests/unit/test_nightly_test_helpers.py -v`）
- [ ] `bash -n scripts/nightly_test.sh` 语法过
- [ ] `./scripts/nightly_test.sh --dry-run` 首次 = create 新 issue；二次 = 同签名 comment 复用
- [ ] dry-run 测试 issue 已 close/delete（不污染仓库）
- [ ] 降级路径：临时把 `gh` 改名再跑 dry-run → 本地告警文件 `$LOG_DIR/issue-body-*.md` 生成，脚本不崩
- [ ] 真实成功跑一次（手动，可 `--keep-worktree` 观察隔离）：worktree 清理、假 HOME 删除、不碰真实 `~/.zk_config.json` / `~/.jfox-backup/`
- [ ] crontab 行已装（`crontab -l | grep nightly_test`）
- [ ] #338 备份已启用且每天 08:00 跑（`jfox backup status` 的 `last_ok=true`）

## 相关文件

| 文件 | 作用 |
|---|---|
| `scripts/nightly_test.sh` | 编排脚本（flock → 备份检查 → worktree → 假 HOME → uv sync → pytest → 失败 issue 去重） |
| `scripts/nightly_test_helpers.py` | 纯逻辑辅助（失败解析、签名、去重决策、备份检查）+ CLI dispatcher |
| `tests/unit/test_nightly_test_helpers.py` | helpers 单测 |
| `docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md` | 设计文档（决策与契约） |
| `~/.jfox-nightly-test/` | 本机运行时目录（日志、worktree、沙箱 home、issue body） |
| `~/.jfox-backup/state.json` | #338 备份状态（脚本前置检查读它） |
