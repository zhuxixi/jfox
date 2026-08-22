# 夜间全量测试 cronjob 实现计划（#263）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每周二 09:00 自动跑 jfox 全量测试，失败自动开/复用带 `nightly-test-failure` label 的 GitHub issue，全程不污染 main 分支与真实用户配置。

**Architecture:** 系统 crontab 一行 → 仓内 bash 编排脚本 `scripts/nightly_test.sh`（flock 单飞 → 备份检查 → fresh worktree → 换假 HOME → `uv sync` → `uv run pytest` → 失败 `gh issue` 去重）+ Python 辅助模块 `scripts/nightly_test_helpers.py`（纯逻辑：解析失败/算签名/决策/备份检查，可 pytest 单测）。无 agent、无 zima PJob。

**Tech Stack:** bash（`set -euo pipefail` + flock）、Python 3.10+（复用项目 venv）、uv、pytest、gh CLI、git worktree。

## Global Constraints

（每个 task 的隐含前提，照抄 spec §2 决策）

- **分支**：所有改动在 `worktree-issue-263-nightly-fulltest` 分支，**禁碰 main**；commit 前 `git branch --show-current` 守卫。
- **Python**：≥3.10，行宽 100，提交前 `ruff check` **和** `black --check` 都过（black 用 `uv run --with black==26.3.1 black --check`）。
- **注释/文档**：中文。
- **隔离**：换假 HOME 沙箱保护真实 `~/.zk_config.json`/pid/backup；`HF_HOME` 指回真实缓存避免重下 bge-m3。
- **GPU**：测试复用正在跑的 embedding daemon（18700），**绝不设 `JFOX_DAEMON_PROCESS=1`**。
- **频率**：每周二 09:00（crontab `0 9 * * 2`）。
- **备份检查**：`~/.jfox-backup/state.json` 的 `last_ok == true` 且 `last_run[:10] == 今天` 才跑。
- **失败通知**：只 `gh issue`，label `nightly-test-failure`，同签名复用 open issue 追加评论。
- **测试规则**：helpers 的 pytest 单测（几秒）可自主跑；**全量 pytest 不自主跑**（~50min，交脚本自己跑 + 用户手动）。
- **gem_synth/auto-summary 不暂停**（非目标）。

## File Structure

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `scripts/nightly_test_helpers.py` | 纯逻辑：解析 pytest 失败、算签名、issue 去重决策、备份检查；含 bash 调用的 CLI dispatcher | 新建 |
| `tests/unit/test_nightly_test_helpers.py` | helpers 的 pytest 单元测试 | 新建 |
| `scripts/nightly_test.sh` | bash 编排：单飞→备份→worktree→假HOME→uv sync→pytest→失败 issue | 新建（Task 3-5 逐步填充） |
| `docs/nightly-test.md` | crontab 安装、label 创建、dry-run 指南、故障排查、验收清单 | 新建 |
| `pyproject.toml` | 可能需把 `scripts/nightly_test_helpers.py` 纳入 ruff/black 检查范围（看现有配置） | 可能改 |

**为何 helpers 单独抽 Python**：bash 不便单元测试，把"失败签名/去重决策/备份日期"这些易错纯逻辑放 Python（项目主语言、有 pytest），可覆盖测试；bash 只留编排（worktree/HOME/进程），用 dry-run 端到端验证。这是对该 issue 的关键可测试性设计。

---

### Task 1: helpers — 失败解析（extract_failures + compute_signature）

**Files:**

- Create: `scripts/nightly_test_helpers.py`
- Test: `tests/unit/test_nightly_test_helpers.py`

**Interfaces:**

- Produces: `extract_failures(pytest_output: str) -> list[str]`、`compute_signature(failures: list[str], top_n: int = 10) -> str`（后续 task 依赖）

- [ ] **Step 1: 写 failing test**

新建 `tests/unit/test_nightly_test_helpers.py`：

```python
"""nightly_test_helpers 纯逻辑单测。"""
import sys
from pathlib import Path

# 让 tests 能 import scripts/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from nightly_test_helpers import compute_signature, extract_failures


def test_extract_failures_parses_nodeids():
    output = (
        "==== FAILURES ====\n"
        "FAILED tests/test_core_workflow.py::TestDevelopPhase::test_emb - AssertionError\n"
        "PASSED tests/test_other.py::test_x\n"
        "FAILED tests/test_hybrid.py::TestSearch::test_integration - TypeError\n"
    )
    assert extract_failures(output) == [
        "tests/test_core_workflow.py::TestDevelopPhase::test_emb",
        "tests/test_hybrid.py::TestSearch::test_integration",
    ]


def test_extract_failures_dedup_keeps_order():
    output = (
        "FAILED tests/a.py::test_1 - x\n"
        "FAILED tests/a.py::test_1 - x\n"
        "FAILED tests/b.py::test_2 - y\n"
    )
    assert extract_failures(output) == ["tests/a.py::test_1", "tests/b.py::test_2"]


def test_extract_failures_empty_when_no_failure():
    assert extract_failures("===== 5 passed in 3s =====") == []


def test_compute_signature_order_invariant():
    a = compute_signature(["tests/c.py::t", "tests/a.py::t", "tests/b.py::t"])
    b = compute_signature(["tests/b.py::t", "tests/c.py::t", "tests/a.py::t"])
    assert a == b  # 排序后稳定
    assert len(a) == 12  # sha1[:12]


def test_compute_signature_top_n_caps():
    many = [f"tests/x.py::test_{i}" for i in range(20)]
    assert compute_signature(many, top_n=10) == compute_signature(many[:10], top_n=10)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_nightly_test_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: nightly_test_helpers`（模块还没建）

- [ ] **Step 3: 写最小实现**

新建 `scripts/nightly_test_helpers.py`：

```python
"""夜间全量测试脚本的纯逻辑辅助函数（可单元测试）。

bash 编排脚本 scripts/nightly_test.sh 通过本模块的 CLI dispatcher 调用这些
纯逻辑：解析 pytest 失败、算失败签名（issue 去重用）、决定开新 issue 还是
追加评论、检查 #338 备份是否在今天完成。所有函数无副作用、便于 pytest 覆盖。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

# pytest -ra 汇总行形如：FAILED <nodeid> - <reason>
_FAILED_RE = re.compile(r"^FAILED\s+(\S+?)(?:\s+-\s+|$)", re.MULTILINE)


def extract_failures(pytest_output: str) -> list[str]:
    """从 pytest 输出提取失败的 test nodeid（去重、保持出现顺序）。"""
    seen: list[str] = []
    for m in _FAILED_RE.finditer(pytest_output):
        nodeid = m.group(1).strip()
        if nodeid and nodeid not in seen:
            seen.append(nodeid)
    return seen


def compute_signature(failures: list[str], top_n: int = 10) -> str:
    """失败 nodeid 排序后取前 N 个，sha1[:12] 作为去重签名（与顺序无关）。"""
    head = sorted(failures)[:top_n]
    digest = hashlib.sha1("\n".join(head).encode("utf-8")).hexdigest()
    return digest[:12]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_nightly_test_helpers.py -v`
Expected: 5 passed

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
uv run --with black==26.3.1 black --check scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
git branch --show-current  # 必须是 worktree-issue-263-nightly-fulltest
git add scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
git commit -m "feat(nightly-test): helpers 失败解析+签名 (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: helpers — 决策 + 备份检查 + CLI dispatcher

**Files:**

- Modify: `scripts/nightly_test_helpers.py`（追加 2 个函数 + CLI）
- Modify: `tests/unit/test_nightly_test_helpers.py`（追加测试）

**Interfaces:**

- Consumes: `extract_failures`、`compute_signature`（Task 1）
- Produces: `decide_issue_action(signature, open_issues) -> ("create"|"comment", int|None)`、`check_backup_last_ok(state_path, today) -> bool`、CLI 子命令 `check-backup`/`signature`/`decide`（供 bash 调用）

- [ ] **Step 1: 追加 failing test**

在 `tests/unit/test_nightly_test_helpers.py` 顶部 import 行追加 `check_backup_last_ok`、`decide_issue_action`，并加测试：

```python
from datetime import date

from nightly_test_helpers import check_backup_last_ok, decide_issue_action


def test_decide_reuses_matching_open_issue():
    issues = [
        {"number": 42, "title": "nightly-test 失败 2026-07-28 [sig:abc123def456]"},
        {"number": 7, "title": "nightly-test 失败 2026-07-21 [sig:zzz999]},
    ]
    assert decide_issue_action("abc123def456", issues) == ("comment", 42)


def test_decide_creates_when_no_match():
    assert decide_issue_action("new123sig456", []) == ("create", None)
    assert decide_issue_action("new123sig456", [{"number": 1, "title": "unrelated"}]) == (
        "create",
        None,
    )


def test_check_backup_ok_when_today_and_true(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        '{"last_run": "2026-07-28T08:00:00", "last_ok": true, "last_archive": "x"}',
        encoding="utf-8",
    )
    assert check_backup_last_ok(state, date(2026, 7, 28)) is True


def test_check_backup_false_when_not_ok(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        '{"last_run": "2026-07-28T08:00:00", "last_ok": false, "last_archive": null}',
        encoding="utf-8",
    )
    assert check_backup_last_ok(state, date(2026, 7, 28)) is False


def test_check_backup_false_when_other_day(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        '{"last_run": "2026-07-27T08:00:00", "last_ok": true, "last_archive": "x"}',
        encoding="utf-8",
    )
    assert check_backup_last_ok(state, date(2026, 7, 28)) is False


def test_check_backup_false_when_missing(tmp_path):
    assert check_backup_last_ok(tmp_path / "nope.json", date(2026, 7, 28)) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_nightly_test_helpers.py -v`
Expected: 新增 5 个 FAIL（ImportError：函数未定义）

- [ ] **Step 3: 追加实现 + CLI dispatcher**

在 `scripts/nightly_test_helpers.py` 的 `compute_signature` 之后追加：

```python
def decide_issue_action(
    signature: str, open_issues: list[dict]
) -> tuple[str, int | None]:
    """给定失败签名和当前 open 的 nightly-test-failure issue，决定复用还是新开。

    open_issues: `gh issue list --json number,title` 的结果，每项 {"number": int, "title": str}。
    返回 ("comment", issue_number) 复用既有，或 ("create", None) 新开。
    匹配规则：issue title 含 "sig:<signature>"。
    """
    needle = f"sig:{signature}"
    for issue in open_issues:
        if needle in str(issue.get("title", "")):
            return ("comment", int(issue["number"]))
    return ("create", None)


def check_backup_last_ok(state_path: Path, today: date) -> bool:
    """读 #338 backup state.json，判断今天的备份是否成功。

    state schema（jfox/backup/loop.py:42-48）：{last_run: ISO时间, last_ok: bool, last_archive}。
    要求 last_ok 为真且 last_run 的日期 == today。
    """
    if not state_path.exists():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not data.get("last_ok"):
        return False
    last_run = str(data.get("last_run", ""))
    return last_run[:10] == today.isoformat()
```

文件末尾追加 CLI dispatcher（供 bash 调用，避免 bash 内联 Python）：

```python
def _cli() -> int:
    """供 bash 脚本调用的 CLI。用法见各分支 stderr --help。"""
    import sys

    if len(sys.argv) < 2:
        print("usage: nightly_test_helpers.py {check-backup|signature|decide} ...", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "check-backup":
        # argv[2] = state.json 路径；退出码 0=今天已备份成功，1=否
        ok = check_backup_last_ok(Path(sys.argv[2]), date.today())
        return 0 if ok else 1
    if cmd == "signature":
        # stdin = pytest 输出；stdout = "signature\t首个失败nodeid\t失败总数"
        failures = extract_failures(sys.stdin.read())
        sig = compute_signature(failures)
        first = failures[0] if failures else "(none)"
        print(f"{sig}\t{first}\t{len(failures)}")
        return 0
    if cmd == "decide":
        # argv[2] = signature；stdin = gh issue list --json number,title 的 JSON 数组
        issues = json.loads(sys.stdin.read() or "[]")
        action, num = decide_issue_action(sys.argv[2], issues)
        print(f"{action}\t{num if num is not None else ''}")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_nightly_test_helpers.py -v`
Expected: 10 passed

- [ ] **Step 5: 手验 CLI dispatcher（可选但推荐）**

```bash
printf 'FAILED tests/a.py::test_1 - x\n' | uv run python scripts/nightly_test_helpers.py signature
# 期望输出形如：<12位sig>\ttests/a.py::test_1\t1
echo '[{"number":42,"title":"x [sig:'"$(printf 'FAILED tests/a.py::t\n' | uv run python scripts/nightly_test_helpers.py signature | cut -f1)"']"}]' | uv run python scripts/nightly_test_helpers.py decide "$(printf 'FAILED tests/a.py::t\n' | uv run python scripts/nightly_test_helpers.py signature | cut -f1)"
# 期望输出：comment<TAB>42
```

- [ ] **Step 6: lint + commit**

```bash
uv run ruff check scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
uv run --with black==26.3.1 black --check scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
git branch --show-current
git add scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
git commit -m "feat(nightly-test): helpers 决策+备份检查+CLI (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: bash — 骨架 + 备份检查

**Files:**

- Create: `scripts/nightly_test.sh`

**Interfaces:**

- Consumes: `python3 scripts/nightly_test_helpers.py check-backup <state>`（Task 2）
- Produces: 可执行脚本骨架（参数解析/环境自举/flock/日志/备份检查已就位；核心测试流程与失败分支留占位函数，由 Task 4/5 填充）

bash 编排层不做单元测试（项目无 bats），用 Task 4/5 的 dry-run 端到端验证。

- [ ] **Step 1: 写脚本骨架**

新建 `scripts/nightly_test.sh`：

```bash
#!/usr/bin/env bash
# 夜间全量测试 cronjob（GitHub #263）：每周二 09:00 由系统 crontab 触发。
# 跑全量 pytest，失败自动开/复用带 nightly-test-failure label 的 GitHub issue。
# 设计文档：docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_HOME="$HOME"
LOG_DIR="$REAL_HOME/.jfox-nightly-test"
LOCK_FILE="/tmp/jfox-nightly-test.lock"
BACKUP_STATE="$REAL_HOME/.jfox-backup/state.json"
REPO_SLUG="zhuxixi/jfox"
ISSUE_LABEL="nightly-test-failure"
mkdir -p "$LOG_DIR"

DRY_RUN=0
KEEP_WORKTREE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --keep-worktree) KEEP_WORKTREE=1; shift ;;
    -h|--help)
      sed -n '2,5p' "$0" >&2
      echo "Usage: $0 [--dry-run] [--keep-worktree]" >&2
      echo "  --dry-run        跳过真实 pytest，用人造失败验证 issue 流程" >&2
      echo "  --keep-worktree  跑完不删 worktree（调试）" >&2
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# crontab 环境极简，显式补 PATH（gh/uv/git 都在 ~/.local/bin 等）
export PATH="$REAL_HOME/.local/bin:$REAL_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
command -v git >/dev/null || { echo "ERROR: git 缺失"; exit 3; }
command -v uv  >/dev/null || { echo "ERROR: uv 缺失";  exit 3; }
command -v gh  >/dev/null || echo "WARN: gh 缺失，失败时只能写本地告警，无法提 issue"

# flock 单飞（仿 ~/.zima/scripts/md_review_gate.py）
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "SKIP: 另一个 nightly_test 正在跑"; exit 0; }

log() { printf '[%s] %s\n' "$(date '+%F %T %z')" "$*"; }

# --- 前置：备份检查（#338）---
if [[ "$DRY_RUN" -eq 1 ]]; then
  log "DRY_RUN: 跳过备份检查"
else
  if python3 "$REPO_ROOT/scripts/nightly_test_helpers.py" check-backup "$BACKUP_STATE"; then
    log "今日备份已确认，继续"
  else
    log "SKIP: 今日备份未确认（state=$BACKUP_STATE）"
    exit 0
  fi
fi

# --- 核心流程（Task 4 实现）---
run_tests() {
  echo "TODO: run_tests 占位（Task 4 填充）" >&2
  return 1
}

# --- 失败分支（Task 5 实现）---
report_failure() {
  # $1 = pytest 输出文件路径
  echo "TODO: report_failure 占位（Task 5 填充）" >&2
}

# --- 主流程 ---
PYTEST_OUT="$LOG_DIR/pytest-$(date +%s).log"
if run_tests >"$PYTEST_OUT" 2>&1; then
  log "测试通过"
  rm -f "$PYTEST_OUT"
  exit 0
else
  rc=$?
  log "测试失败 (rc=$rc)，提 issue"
  report_failure "$PYTEST_OUT" || log "WARN: 提 issue 失败，见本地告警"
  exit 1
fi
```

`chmod +x scripts/nightly_test.sh`。

- [ ] **Step 2: 验证骨架（--help + dry-run 备份跳过路径）**

```bash
./scripts/nightly_test.sh --help            # 期望打印用法
./scripts/nightly_test.sh --dry-run         # 期望跑进 run_tests 占位（Task 4 前 会 return 1，触发 report_failure 占位）——先确认不报语法错
bash -n scripts/nightly_test.sh             # 语法检查必须通过
```

- [ ] **Step 3: lint（shellcheck 若有）+ commit**

```bash
# shellcheck 可选：uv run --with shellcheck shellcheck scripts/nightly_test.sh || true
git branch --show-current
git add scripts/nightly_test.sh
git commit -m "feat(nightly-test): bash 骨架+备份检查+flock (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: bash — 核心测试流程（run_tests）

**Files:**

- Modify: `scripts/nightly_test.sh`（替换 `run_tests` 占位）

**Interfaces:**

- Consumes: `REAL_HOME`/`REPO_ROOT`/`LOG_DIR`/`DRY_RUN`/`KEEP_WORKTREE`（Task 3 骨架变量）
- Produces: `run_tests` 把全量 pytest 的合并输出写到 stdout（主流程已重定向到 `$PYTEST_OUT`），退出码 = pytest 退出码；dry-run 时喂人造失败输出

- [ ] **Step 1: 实现 run_tests**

把 Task 3 的 `run_tests` 占位函数替换为：

```bash
run_tests() {
  # 建 fresh worktree（基于 origin/main，绝不 checkout 本地 main）
  local ts; ts="$(date +%s)"
  local wt="$LOG_DIR/worktree-$ts"
  git -C "$REPO_ROOT" fetch -q origin main
  git -C "$REPO_ROOT" worktree add -q --detach "$wt" origin/main

  # 换假 HOME 沙箱，但 HF 缓存指回真实路径（避免重下 bge-m3 ~2GB）
  local sandbox; sandbox="$(mktemp -d "$LOG_DIR/home-XXXXXX")"
  local real_hf="$REAL_HOME/.cache/huggingface"

  # 清理函数（无论成败都跑）
  cleanup() {
    if [[ "$KEEP_WORKTREE" -eq 1 ]]; then
      log "保留 worktree: $wt（沙箱: $sandbox）"
    else
      git -C "$REPO_ROOT" worktree remove --force "$wt" 2>/dev/null || true
      rm -rf "$sandbox"
    fi
  }
  trap cleanup EXIT

  log "worktree=$wt sandbox=$sandbox"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    # 人造失败输出（验证 issue 流程用）；不真跑 pytest
    echo "==== dry-run 人造失败 ===="
    echo "FAILED tests/unit/test_nightly_test_helpers.py::test_extract_failures_parses_nodeids - FakeError: dry-run"
    echo "FAILED tests/unit/test_nightly_test_helpers.py::test_compute_signature_order_invariant - FakeError: dry-run"
    echo "===== 2 failed in 0.01s ====="
    return 1
  fi

  # 在 worktree 内、假 HOME 下跑全量测试
  (
    cd "$wt"
    export HOME="$sandbox"
    [[ -d "$real_hf" ]] && export HF_HOME="$real_hf"
    # 守 lockfile，不漂移依赖
    uv sync --frozen --extra dev
    uv run pytest tests/ -v --tb=short -ra
  )
}
```

- [ ] **Step 2: dry-run 验证（worktree 建删 + 假 HOME + 人造失败）**

```bash
bash -n scripts/nightly_test.sh                            # 语法
./scripts/nightly_test.sh --dry-run --keep-worktree        # 跑完保留，人工看 worktree/沙箱是否生成
ls "$HOME/.jfox-nightly-test/" | grep worktree             # 期望看到 worktree 目录（因 --keep-worktree）
# 清理本轮残留：
git -C "$REPO_ROOT" worktree list
git -C "$REPO_ROOT" worktree remove --force "$HOME/.jfox-nightly-test/worktree-"* 2>/dev/null || true
git -C "$REPO_ROOT" worktree prune
```

确认：① worktree 确实基于 origin/main 建出 ② sandbox（假 HOME）建出 ③ dry-run 没碰真实 pytest ④ cleanup 删干净（不带 --keep-worktree 时）。

- [ ] **Step 3: 真实验证一次成功路径（手动，可选但推荐）**

```bash
# 在确实有今日备份的前提下（或 --dry-run 已够），跑一次真实全量：
# ./scripts/nightly_test.sh
# （~20-50min，占 GPU；或交由用户手动。验证：通过则 worktree 清理、exit 0、无 issue）
```

- [ ] **Step 4: commit**

```bash
git branch --show-current
git add scripts/nightly_test.sh
git commit -m "feat(nightly-test): 核心测试流程 worktree+假HOME+pytest (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: bash — 失败分支 + issue 去重（report_failure）

**Files:**

- Modify: `scripts/nightly_test.sh`（替换 `report_failure` 占位）

**Interfaces:**

- Consumes: `python3 scripts/nightly_test_helpers.py signature`/`decide`（Task 2）、`REPO_SLUG`/`ISSUE_LABEL`/`LOG_DIR`（骨架）、`gh`（可能缺失→降级）
- Produces: 失败时按签名去重 `gh issue create`/`comment`；`gh` 不可用时降级写 `$LOG_DIR/failed-<ts>.log`

- [ ] **Step 1: 实现 report_failure**

把 Task 3 的 `report_failure` 占位替换为：

```bash
report_failure() {
  local pytest_log="$1"
  local today; today="$(date '+%F')"
  local ts; ts="$(date '+%s')"

  # 算签名 + 首个失败 + 失败数（helpers CLI）
  local sig_line sig first count
  sig_line="$(python3 "$REPO_ROOT/scripts/nightly_test_helpers.py" signature <"$pytest_log")"
  sig="${sig_line%% *}"
  first="$(printf '%s' "$sig_line" | cut -f2)"
  count="$(printf '%s' "$sig_line" | cut -f3)"

  # issue body（截断 traceback，避免巨型 issue）
  local body="$LOG_DIR/issue-body-$ts.md"
  {
    echo "## #263 夜间全量测试失败"
    echo
    echo "- 日期: $today"
    echo "- commit: \`$(git -C "$REPO_ROOT" rev-parse --short origin/main)\`"
    echo "- 失败签名: \`$sig\`（首个失败: \`$first\`，共 $count 个）"
    echo
    echo "## 失败的 test（前 10）"
    grep -E '^FAILED ' "$pytest_log" | head -10
    echo
    echo "## traceback 摘要（截断）"
    # 取失败摘要段，限 200 行 / 8KB
    sed -n '/==== FAILURES ====/,/^==== short test summary/p' "$pytest_log" | head -200 | head -c 8192
    echo
    echo "---"
    echo "完整日志: \`$pytest_log\`（本机）。由 \`scripts/nightly_test.sh\` 自动提交。"
  } >"$body"

  # gh 不可用 → 降级写本地
  if ! command -v gh >/dev/null; then
    log "WARN: gh 缺失，失败摘要写到 $body（未提 GitHub issue）"
    return 0
  fi
  if ! gh auth status >/dev/null 2>&1; then
    log "WARN: gh 未认证，失败摘要写到 $body（未提 GitHub issue）"
    return 0
  fi

  # 确保 label 存在
  gh label create "$ISSUE_LABEL" --repo "$REPO_SLUG" --color D73B3B \
    --description "夜间全量测试（#263）自动失败" --force >/dev/null 2>&1 || true

  # 去重决策：查 open issue 的 title 里有没有同签名
  local decision action num
  decision="$(gh issue list --repo "$REPO_SLUG" --label "$ISSUE_LABEL" \
                --state open --json number,title --limit 50 \
              | python3 "$REPO_ROOT/scripts/nightly_test_helpers.py" decide "$sig")"
  action="${decision%% *}"
  num="$(printf '%s' "$decision" | cut -f2)"

  if [[ "$action" == "comment" && -n "$num" ]]; then
    log "复用 issue #$num（同签名 $sig）追加评论"
    gh issue comment "$num" --repo "$REPO_SLUG" --body-file "$body"
  else
    log "新开 issue（签名 $sig）"
    gh issue create --repo "$REPO_SLUG" \
      --title "nightly-test 失败 $today [sig:$sig]" \
      --label "$ISSUE_LABEL" --body-file "$body"
  fi
}
```

- [ ] **Step 2: dry-run 验证 issue 流程（首次 create + 二次 comment）**

```bash
# 第一次 dry-run：应新开 issue
./scripts/nightly_test.sh --dry-run
ISSUE_URL=$(gh issue list --repo zhuxixi/jfox --label nightly-test-failure --state open --json url --limit 1 -q '.[0].url')
echo "新建的测试 issue: $ISSUE_URL"

# 第二次 dry-run（同人造失败→同签名）：应在同一 issue 追加评论，不新开
./scripts/nightly_test.sh --dry-run
gh issue view "$(basename "$ISSUE_URL")" --repo zhuxixi/jfox --json comments -q '.comments | length'
# 期望评论数 ≥1（说明复用了）

# 清理：手动 close/delete 这两个 dry-run 产生的测试 issue（避免污染）
gh issue close "$(basename "$ISSUE_URL")" --repo zhuxixi/jfox
# delete 需 GitHub Admin，或在网页删；或保留 close 状态
```

确认：① 第一次 create ② 第二次 comment 不新开 ③ issue title 含 `[sig:...]` ④ label 正确。

- [ ] **Step 3: 验证降级（临时把 PATH 里的 gh 屏蔽）**

```bash
# 模拟 gh 缺失：用 PATH 占位
PATH="/usr/bin:/bin" ./scripts/nightly_test.sh --dry-run 2>&1 | grep "gh 缺失"
# 期望看到 "WARN: gh 缺失..." 且生成本地 $LOG_DIR/issue-body-*.md，不报错退出码仍 1
ls "$HOME/.jfox-nightly-test/" | grep issue-body
```

- [ ] **Step 4: commit**

```bash
git branch --show-current
git add scripts/nightly_test.sh
git commit -m "feat(nightly-test): 失败分支 gh issue 去重+降级 (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 文档 + crontab 安装 + 验收清单

**Files:**

- Create: `docs/nightly-test.md`

- [ ] **Step 1: 写文档**

新建 `docs/nightly-test.md`，内容涵盖：

- **职责**：一句话说明（每周二 09:00 跑全量测试，失败开 issue）。
- **安装 crontab**：给用户执行的命令（本机，不进 PR）：

  ```
  # 编辑 crontab
  crontab -l | { cat; echo "0 9 * * 2 /home/elling/git-repo/github/jfox/scripts/nightly_test.sh >> /home/elling/.jfox-nightly-test/cron.log 2>&1"; } | crontab -
  crontab -l | grep nightly_test   # 确认
  ```

- **label**：说明 `nightly-test-failure` 首次运行时脚本自动 `gh label create`，无需手工。
- **dry-run**：`./scripts/nightly_test.sh --dry-run` 验证 issue 流程的步骤（含测试 issue 清理提醒）。
- **前置依赖**：#338 备份必须启用且每天 08:00 跑（脚本靠 `state.json` 判断）。
- **故障排查**：gh 未认证 / PATH 缺失 / 备份未跑 → 各自现象与处置。
- **验收清单**（勾选）：
  - [ ] helpers 单测全绿
  - [ ] `bash -n` 语法过
  - [ ] dry-run 首次 create、二次 comment（同签名复用）
  - [ ] dry-run 测试 issue 已 close/delete
  - [ ] 降级路径（gh 缺失）写本地告警
  - [ ] 真实成功跑一次（手动）：worktree 清理、假 HOME 删除、不碰真实配置
  - [ ] crontab 行已装

- [ ] **Step 2: commit 文档**

```bash
git branch --show-current
git add docs/nightly-test.md
git commit -m "docs(nightly-test): 安装/验收/故障排查 (#263)" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review（plan 自审）

**Spec 覆盖**：D1 bash+crontab 无 agent（整个 plan）✅ ｜ D2 crontab（Task 6）✅ ｜ D3 每周二 09:00（Task 6 crontab 行）✅ ｜ D4 备份检查 last_run+last_ok（Task 2 函数 + Task 3 调用）✅ ｜ D5 issue 去重签名（Task 1/2/5）✅ ｜ D6 daemon 复用不设 JFOX_DAEMON_PROCESS（Task 4 run_tests 未设该 env）✅ ｜ D7 假 HOME + HF_HOME（Task 4）✅ ｜ D8 不暂停（非目标，plan 无暂停步骤）✅。

**Placeholder 扫描**：无 TBD/TODO（Task 3/4/5 的 `TODO: 占位` 是待后续 task 替换的标记，非交付 placeholder，且后续 task 明确替换）。

**类型/命名一致性**：`extract_failures`/`compute_signature`/`decide_issue_action`/`check_backup_last_ok` 在 Task 1→2→5 跨任务一致；CLI 子命令 `check-backup`/`signature`/`decide` 在 Task 2 定义、Task 3/5 调用一致。

**风险点（实现时注意）**：

- `--tb=short` 下 `==== FAILURES ====` 段标题可能因 pytest 版本/locale 变化；Task 5 的 traceback 截取 sed 若抓不到，回退到整日志 `head -200`。实现时用真实 dry-run 输出校准。
- 假 HOME 下 `uv`/`git` 的全局配置（`~/.gitconfig`、`~/.config/uv`）会找不到——若 `uv sync` 或 `git fetch` 因此失败，需在 sandbox 里软链这些回真实路径，或 `export GIT_CONFIG_GLOBAL=$REAL_HOME/.gitconfig`。Task 4 实现时若命中再补。
- gh issue `--search` 未用（改用 helpers decide 精确匹配 title），避免 search 模糊。
