# Nightly Embed Env 修复实现计划（#559）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-559-nightly-embed-env`（所有路径基于此 worktree，禁碰 main checkout）

**Goal:** nightly 全量测试脚本的安装面补齐 `[embed]` extra、加环境 fail-fast 守卫与 `--ref` 调试模式，使 #559 的 9 个失败回绿并有静态测试防回归。

**Architecture:** 三层修复——helpers 纯函数层（可注入 importer 的探测函数 + CLI 子命令）、bash 编排层（nightly_test.sh 的安装行/守卫/主流程 rc 分支/--ref 参数）、静态契约层（单测解析并断言脚本文本与设计文档）。不碰产品代码。

**Tech Stack:** bash（set -euo pipefail 脚本）、Python 3.10+ stdlib（helpers 保持零第三方依赖）、pytest（unit/static 层）。

**Spec:** `docs/superpowers/specs/2026-10-09-nightly-embed-env-design.md`（验收矩阵 A1-A6/U1-U2 见其 §5）

## Global Constraints

- 只允许改动 5 个文件：`scripts/nightly_test.sh`、`scripts/nightly_test_helpers.py`、`docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md`、`tests/unit/test_nightly_script_env.py`（新建）、`tests/unit/test_nightly_test_helpers.py`。不碰 `jfox/`、`pyproject.toml`、`.github/`、任何现有测试的断言与 marker。
- `scripts/nightly_test_helpers.py` 保持 stdlib-only（cron 极简环境）。
- 脚本内调 helpers 一律 `uv run --no-sync python scripts/nightly_test_helpers.py …`（防 `uv run` 反向重同步掉 extra）。
- 退出码语义：`4` = 环境失败（不提 issue）；cron 不传参时行为与现状逐字节等价（默认 ref `origin/main`、走备份检查、失败提 issue）。
- Python 行宽 100（black/ruff）；所有 git 跟踪 md 须过 `npx --yes markdownlint-cli2`。
- worktree 内跑测试统一 `uv run --extra dev --extra embed pytest …`（不带 `--extra` 的裸 `uv run` 会把环境同步回无 extra，KB 已知坑）。
- `git add` 按文件 stage，禁止 `git add -A`；commit message 用英文 conventional 格式。

---

### Task 1: helpers 纯函数 + `check-embed-env` 子命令 [A1, A2]

**Files:**

- Modify: `scripts/nightly_test_helpers.py`（顶部 import 区 + 新函数 + `_cli()` 新分支）
- Test: `tests/unit/test_nightly_test_helpers.py`（追加两个测试类）

**Interfaces:**

- Consumes: 现有 `_cli()` argv 分发模式（`scripts/nightly_test_helpers.py`）
- Produces: `embed_components_available(import_module: Callable[[str], Any] = importlib.import_module) -> tuple[bool, list[str]]`；`_cli()` 支持 `check-embed-env`：齐→return 0 无输出，缺→return 1 且 stdout 打印 `missing: torch, sentence_transformers`（固定探测顺序 torch → sentence_transformers）

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/test_nightly_test_helpers.py` 末尾；同时把顶部 import 区改为下面的完整形态）

```python
# 顶部 import 区改为（在既有 sys.path.insert 之后）：
import nightly_test_helpers
from nightly_test_helpers import (
    check_backup_last_ok,
    compute_signature,
    decide_issue_action,
    embed_components_available,
    extract_failures,
)
```

```python
class TestEmbedComponentsAvailable:
    """A1: embed 组件探测纯函数（假 importer 注入，不碰真实环境）。"""

    @staticmethod
    def _fake_importer(available: set[str]):
        def _import(name: str):
            if name not in available:
                raise ImportError(f"No module named {name!r}")
            return object()

        return _import

    def test_all_present(self):
        ok, missing = embed_components_available(
            self._fake_importer({"torch", "sentence_transformers"})
        )
        assert ok is True
        assert missing == []

    def test_all_missing(self):
        ok, missing = embed_components_available(self._fake_importer(set()))
        assert ok is False
        assert missing == ["torch", "sentence_transformers"]

    def test_partial_missing_keeps_order(self):
        ok, missing = embed_components_available(self._fake_importer({"torch"}))
        assert ok is False
        assert missing == ["sentence_transformers"]


class TestCliCheckEmbedEnv:
    """A2: check-embed-env 子命令分发（argv 注入 + 探测函数打桩）。"""

    def test_ok_returns_zero_without_output(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys, "argv", ["nightly_test_helpers.py", "check-embed-env"]
        )
        monkeypatch.setattr(
            nightly_test_helpers,
            "embed_components_available",
            lambda: (True, []),
        )
        assert nightly_test_helpers._cli() == 0
        assert capsys.readouterr().out == ""

    def test_missing_returns_one_and_lists_components(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys, "argv", ["nightly_test_helpers.py", "check-embed-env"]
        )
        monkeypatch.setattr(
            nightly_test_helpers,
            "embed_components_available",
            lambda: (False, ["torch", "sentence_transformers"]),
        )
        assert nightly_test_helpers._cli() == 1
        out = capsys.readouterr().out
        assert "torch" in out
        assert "sentence_transformers" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_test_helpers.py -q`
Expected: FAIL — `ImportError: cannot import name 'embed_components_available'`

- [ ] **Step 3: 最小实现**（`scripts/nightly_test_helpers.py`）

顶部 import 区改为：

```python
import hashlib
import importlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable
```

在 `check_backup_last_ok` 之后新增：

```python
def embed_components_available(
    import_module: Callable[[str], Any] = importlib.import_module,
) -> tuple[bool, list[str]]:
    """#559: 探测全量测试所需 embed 组件是否可导入（依赖注入，便于单测）。

    Returns:
        (是否全部可用, 缺失组件清单；固定顺序 torch → sentence_transformers)
    """
    missing: list[str] = []
    for name in ("torch", "sentence_transformers"):
        try:
            import_module(name)
        except ImportError:
            missing.append(name)
    return (not missing, missing)
```

`_cli()` 内、`if cmd == "decide":` 分支之后新增：

```python
    if cmd == "check-embed-env":
        # 退出码 0=组件齐，1=有缺失（stdout 列缺失清单，供 nightly 日志定位）
        ok, missing = embed_components_available()
        if not ok:
            print("missing: " + ", ".join(missing))
        return 0 if ok else 1
```

usage 行同步改为 `{check-backup|signature|decide|check-embed-env}`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_test_helpers.py -q`
Expected: PASS（既有用例 + 新增 5 个全绿）

- [ ] **Step 5: Commit**

```bash
git add scripts/nightly_test_helpers.py tests/unit/test_nightly_test_helpers.py
git commit -m "feat(nightly): add embed_components_available helper + check-embed-env subcommand (#559)"
```

---

### Task 2: 静态契约测试 + 脚本安装面/守卫/rc==4 分支 [A3, A4]

**Files:**

- Create: `tests/unit/test_nightly_script_env.py`
- Modify: `scripts/nightly_test.sh`（L117-120 区域 + 主流程尾部）

**Interfaces:**

- Consumes: Task 1 的 `check-embed-env` 子命令（脚本以 `uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env` 调用）
- Produces: 纯函数 `parse_sync_extras(script_text: str) -> set[str]`（test 文件内定义，仅解析 `uv sync` 命令行本体）；脚本具备属性——sync 行含 `--frozen --extra dev --extra embed`、含守卫调用与 `--no-sync`、主流程含 `"$rc" -eq 4` 分支

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_nightly_script_env.py`，完整内容如下）

```python
"""#559 nightly 脚本环境契约静态测试。

守护 scripts/nightly_test.sh 的安装面（--extra dev --extra embed + --frozen）、
embed 守卫 wiring（check-embed-env + --no-sync）、rc==4 环境失败不提 issue 分支。
仿 #519 的 test_pyproject_embed_extra.py 静态断言先例。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "nightly_test.sh"


def parse_sync_extras(script_text: str) -> set[str]:
    """提取 uv sync 命令行本体里的 --extra 值（注释与日志文案不算）。"""
    extras: set[str] = set()
    for line in script_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("uv sync"):
            continue
        for m in re.finditer(r"--extra[= ]([\w-]+)", stripped):
            extras.add(m.group(1))
    return extras


class TestParseSyncExtras:
    def test_parses_multiple_extras(self):
        assert (
            parse_sync_extras("    uv sync --frozen --extra dev --extra embed")
            == {"dev", "embed"}
        )

    def test_single_extra(self):
        assert parse_sync_extras("uv sync --frozen --extra dev") == {"dev"}

    def test_ignores_comments_and_log_text(self):
        text = (
            "# uv sync --extra old\n"
            '  log "ERROR: 检查 uv sync 是否带 --extra embed（#519/#559）"\n'
            "    uv run pytest tests/ -v --tb=short -ra\n"
        )
        assert parse_sync_extras(text) == set()


class TestNightlyScriptEnv:
    def _script(self) -> str:
        return SCRIPT.read_text(encoding="utf-8")

    def test_sync_installs_dev_and_embed_extras_frozen(self):
        text = self._script()
        assert {"dev", "embed"} <= parse_sync_extras(text)
        for line in text.splitlines():
            if line.strip().startswith("uv sync"):
                assert "--frozen" in line

    def test_embed_guard_wired_with_no_sync(self):
        text = self._script()
        assert "check-embed-env" in text
        assert (
            "uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env"
            in text
        )

    def test_env_failure_exit_code_skips_issue_creation(self):
        assert '"$rc" -eq 4' in self._script()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q`
Expected: FAIL — 3 个 `TestNightlyScriptEnv` 用例失败（当前脚本缺 extra/守卫/rc 分支），`TestParseSyncExtras` 3 个通过

- [ ] **Step 3: 修改脚本**（`scripts/nightly_test.sh`，三处）

(a) run_tests 子壳内，原两行：

```bash
    uv sync --frozen --extra dev
    uv run pytest tests/ -v --tb=short -ra
```

改为：

```bash
    # 守 lockfile，不漂移依赖；#519 拆出 [embed] 后全量测试须显式装（#559）
    uv sync --frozen --extra dev --extra embed
    # #559 fail-fast：embed 组件缺失立即失败，避免 9 个误导性测试失败 + 垃圾 issue
    if ! uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; then
      log "ERROR: 全量环境缺 embed 组件——检查 uv sync 是否带 --extra embed（#519/#559）"
      exit 4
    fi
    uv run pytest tests/ -v --tb=short -ra
```

(b) 主流程尾部（文件末尾 `else` 分支）改为：

```bash
else
  rc=$?
  if [[ "$rc" -eq 4 ]]; then
    log "环境失败 (rc=4)，不提 issue——原因见上方日志"
    exit 4
  fi
  log "测试失败 (rc=$rc)，提 issue"
  report_failure "$PYTEST_OUT" || log "WARN: 提 issue 失败，见本地告警"
  exit 1
fi
```

(c) 语法检查：`bash -n scripts/nightly_test.sh` 无输出。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q`
Expected: PASS（6 个全绿）

- [ ] **Step 5: Commit**

```bash
git add scripts/nightly_test.sh tests/unit/test_nightly_script_env.py
git commit -m "fix(nightly): install [embed] extra, fail-fast env guard, rc=4 skips issue filing (#559)"
```

---

### Task 3: `--ref` 调试模式 [A3/A4 扩展]

**Files:**

- Modify: `scripts/nightly_test.sh`（参数解析 / 备份检查 / worktree add / 失败分支）
- Test: `tests/unit/test_nightly_script_env.py`（`TestNightlyScriptEnv` 追加 2 用例）

**Interfaces:**

- Consumes: 无（纯脚本参数）
- Produces: `--ref <git-ref>` 参数；`NIGHTLY_REF` 变量；默认 `origin/main`；ref 模式跳过备份检查且失败不 `report_failure`（绝不触 GitHub）

- [ ] **Step 1: 写失败测试**（`TestNightlyScriptEnv` 类内追加）

```python
    def test_ref_debug_mode_present(self):
        text = self._script()
        assert "--ref)" in text
        assert "${NIGHTLY_REF:-origin/main}" in text

    def test_ref_mode_skips_backup_and_issue_filing(self):
        text = self._script()
        # 备份检查与提 issue 两处都必须让位于调试模式
        assert '-n "$NIGHTLY_REF"' in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q`
Expected: FAIL — 新增 2 用例失败

- [ ] **Step 3: 修改脚本**（四处）

(a) 参数解析块改为：

```bash
DRY_RUN=0
KEEP_WORKTREE=0
NIGHTLY_REF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --keep-worktree) KEEP_WORKTREE=1; shift ;;
    --ref)
      [[ $# -ge 2 ]] || { echo "--ref 需要参数" >&2; exit 2; }
      NIGHTLY_REF="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,5p' "$0" >&2
      echo "Usage: $0 [--dry-run] [--keep-worktree] [--ref <git-ref>]" >&2
      echo "  --dry-run        跳过真实 pytest，用人造失败验证 issue 流程" >&2
      echo "  --keep-worktree  跑完不删 worktree（调试）" >&2
      echo "  --ref <git-ref>  调试模式：测指定 ref 而非 origin/main（跳过备份检查、失败不提 issue）" >&2
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
```

(b) 备份检查块的条件行改为：

```bash
if [[ "$DRY_RUN" -eq 1 || -n "$NIGHTLY_REF" ]]; then
  log "调试模式（DRY_RUN/--ref）：跳过备份检查"
else
```

（原 `if`/`else` 结构不变，仅换条件行并加 log 行。）

(c) run_tests 内 worktree 建立段改为：

```bash
  git -C "$REPO_ROOT" fetch -q origin main
  local ref="${NIGHTLY_REF:-origin/main}"
  git -C "$REPO_ROOT" worktree add -q --detach "$wt" "$ref"
```

(d) 主流程失败分支（Task 2 的 (b) 之后）在 `log "测试失败 …"` 之前插入：

```bash
  if [[ -n "$NIGHTLY_REF" ]]; then
    log "--ref 调试模式：失败不提 issue（完整日志: $PYTEST_OUT）"
    exit 1
  fi
```

语法检查：`bash -n scripts/nightly_test.sh` 无输出。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q`
Expected: PASS（8 个全绿）

- [ ] **Step 5: Commit**

```bash
git add scripts/nightly_test.sh tests/unit/test_nightly_script_env.py
git commit -m "feat(nightly): --ref debug mode for local full-suite runs (#559)"
```

---

### Task 4: 设计文档 §6 同步 [A5]

**Files:**

- Modify: `docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md`（§6 装依赖行 + 流程树图）
- Test: `tests/unit/test_nightly_script_env.py`（追加 1 用例）

**Interfaces:**

- Consumes: 无
- Produces: 文档含字符串 `uv sync --frozen --extra dev --extra embed`

- [ ] **Step 1: 写失败测试**（`TestNightlyScriptEnv` 类内追加）

```python
    def test_design_doc_install_command_includes_embed(self):
        doc = (
            REPO_ROOT
            / "docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md"
        ).read_text(encoding="utf-8")
        assert "uv sync --frozen --extra dev --extra embed" in doc
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q`
Expected: FAIL — 新用例失败（文档仍是 `--extra dev`）

- [ ] **Step 3: 改文档**（两处）

§6 原行：

```markdown
6. **装依赖**：`cd worktree && uv sync --frozen --extra dev`（守 lockfile，不漂移）。
```

改为：

```markdown
6. **装依赖**：`cd worktree && uv sync --frozen --extra dev --extra embed`（守 lockfile，不漂移；issue #519 拆出 [embed] 后全量测试须显式安装，曾漏改致 #559）。装完跑 `check-embed-env` 守卫，缺组件即 rc=4 失败、不提 issue。
```

流程树图中的 `uv sync --frozen` 行同步为 `uv sync --frozen --extra dev --extra embed`。

- [ ] **Step 4: 验证通过 + lint**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_script_env.py -q && npx --yes markdownlint-cli2 "docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md"`
Expected: PASS + lint 0 issues

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md tests/unit/test_nightly_script_env.py
git commit -m "docs(nightly): sync design doc install command with [embed] extra (#559)"
```

---

### Task 5: 全量验证 + 本地手册 L0-L3 [A6, U1]

**Files:** 无新改动（纯验证；发现问题时回前面 task 修）

**Interfaces:**

- Consumes: Task 1-4 全部产物
- Produces: A6/U1 的执行记录（写进最终 PR 描述与 issue 评论）

- [ ] **Step 1: A6 全量相关单测**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_nightly_test_helpers.py tests/unit/test_nightly_script_env.py tests/unit/test_pyproject_embed_extra.py -q`
Expected: 全部 PASS

- [ ] **Step 2: U1-L0 复现修前红**（独立 venv，不动 worktree 的 .venv）

```bash
cd <worktree>
export UV_PROJECT_ENVIRONMENT=/tmp/venv-light-559
uv sync --frozen --extra dev
uv run --no-sync python -m pytest \
  "tests/test_embedding_device.py::TestDeviceResolution::test_auto_resolves_to_cpu_when_no_cuda" \
  "tests/performance/test_performance.py::TestModelCache::test_clear_removes_cache" \
  tests/test_json_schema_contract.py -q --timeout=90
# 预期 3 failed；随后保留该 venv 供 Step 3 用
```

- [ ] **Step 3: U1-L2 守卫双分支实测**

```bash
# 分支 1（worktree dev env，有 embed）→ rc=0
uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; echo rc=$?
# 分支 2（Step 2 的轻装 venv）→ rc=1 + missing 清单
UV_PROJECT_ENVIRONMENT=/tmp/venv-light-559 \
  uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; echo rc=$?
```

- [ ] **Step 4: U1-L3 修复效果（修后安装语义 + 三用例回绿）**

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/venv-full-559
uv sync --frozen --extra dev --extra embed
uv run --no-sync python -c "import torch, sentence_transformers; print('embed OK')"
uv run --no-sync python -m pytest \
  "tests/test_embedding_device.py::TestDeviceResolution::test_auto_resolves_to_cpu_when_no_cuda" \
  "tests/performance/test_performance.py::TestModelCache::test_clear_removes_cache" \
  tests/test_json_schema_contract.py -q --timeout=90
# 预期 3 passed；rm -rf /tmp/venv-light-559 /tmp/venv-full-559
```

- [ ] **Step 5: 汇总记录**（不 commit，写入 PR 描述与 issue 评论素材）：A1-A6 命令与结果、U1 各步结果、U2（L4/cron）待合并后执行的说明。

---

## Self-Review 结论

- Spec 覆盖：D1→Task 2(a)、D2→Task 1+2、D3→Task 1、D4→Task 4、D5→Task 2/3/4、D6→Task 2(b)、D7→Task 3；A1-A6 均有归属（A1/A2→T1，A3/A4→T2/T3，A5→T4，A6→T5）；U1→T5 Step 2-4，U2→合并后。
- 占位符扫描：无 TBD/TODO；所有代码步骤含完整代码。
- 类型一致性：`embed_components_available` 签名在 Task 1 定义、Task 1 测试与脚本调用一致；`parse_sync_extras` 在 Task 2 定义并仅被测试内引用。
