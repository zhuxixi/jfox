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
  # 建 fresh worktree（基于 origin/main，绝不 checkout 本地 main）
  local ts; ts="$(date +%s)"
  # NOTE: wt/sandbox 故意不写 local —— cleanup EXIT trap 在 run_tests 返回后
  # 才触发（脚本退出时），local 变量届时已出栈，set -u 下会报 unbound variable。
  wt="$LOG_DIR/worktree-$ts"
  git -C "$REPO_ROOT" fetch -q origin main
  git -C "$REPO_ROOT" worktree add -q --detach "$wt" origin/main

  # 换假 HOME 沙箱，但 HF 缓存指回真实路径（避免重下 bge-m3 ~2GB）
  sandbox="$(mktemp -d "$LOG_DIR/home-XXXXXX")"
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

# --- 失败分支（Task 5 实现）---
report_failure() {
  # $1 = pytest 输出文件路径
  local pytest_log="$1"
  local today; today="$(date '+%F')"
  local ts; ts="$(date '+%s')"

  # 算签名 + 首个失败 + 失败数（helpers CLI）
  local sig_line sig first count
  sig_line="$(python3 "$REPO_ROOT/scripts/nightly_test_helpers.py" signature <"$pytest_log")"
  sig="${sig_line%%	*}"
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
    # head 提前关闭管道会让 grep 在 pipefail 下退出码非 0（SIGPIPE）。
    # 当前调用点（report_failure ... || log）下 bash 自动禁用函数体内 set -e，实际不会中断；
    # || true 防御性保留：若将来调用点移除 || 或本函数被独立调用，保证 SIGPIPE 不致中断。
    grep -E '^FAILED ' "$pytest_log" | head -10 || true
    echo
    echo "## traceback 摘要（截断）"
    # 取失败摘要段，限 200 行 / 8KB；|| true 防御性保留（同上：head 关闭管道触发 SIGPIPE，
    # 当前调用点下 set -e 已被禁用，仅防未来调用点变更或独立调用）
    sed -n '/==== FAILURES ====/,/^==== short test summary/p' "$pytest_log" | head -200 | head -c 8192 || true
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
  action="${decision%%	*}"
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
