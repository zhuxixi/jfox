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
