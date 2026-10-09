# Spec: nightly 全量测试环境补齐 [embed] extra（issue #559）

- 日期：2026-10-09（rev2，应「说清楚怎么修、本地怎么调」重写）
- 状态：**draft，待用户确认**
- 根因报告：`research/01-root-cause-timeline.md`、`research/02-fix-surface-and-constraints.md`
- 类型：bug（CI/测试基建）· systematic-debugging Phase 1-2 已完成（根因已复现）

## 1. 背景、根因、修什么（一段话版）

issue #519（PR #537，2026-09-20）把 sentence-transformers 拆为可选 `[embed]` extra 时更新了
GitHub CI 与安装文档，但漏了第二个安装消费方——本地 cron 的 `scripts/nightly_test.sh`
（L119 仍是 `uv sync --frozen --extra dev`）。nightly 全量跑（无 marker 过滤），轻装环境
下 9 个测试失败（4× `patch("sentence_transformers.…")` 导入失败、4× `patch("torch.…")`
导入失败、1× `bulk-import` 契约测试命中 `embed_dependency_missing` 拒绝路径）。
**修的是 nightly 脚本的安装面与失败报告面，不改任何产品代码和现有测试。**

## 2. 目标 / 非目标

目标：

1. nightly 安装面对齐 CI Full job（`--extra dev --extra embed`），全量回绿；
2. 环境漂移 fail-fast：embed 组件缺失时在安装段立即报错退出，不进 pytest、不开垃圾 issue；
3. 静态防回归：脚本/文档的 extra 约定有单测守护；
4. （待批准 D7）脚本支持 `--ref` 调试模式，本地可在合并前对修复分支跑完整 nightly 流程。

非目标：

- 不改 pyproject / CI workflow / 产品代码（`jfox/`）/ 任何现有测试的断言与 marker；
- 不给 8 个模块依赖测试加 importorskip（nightly 是哨兵，环境再漂移应当响亮失败）；
- 不给 nightly 加 marker 过滤（违反 #263 全量章程）；
- 不重构 auto-issue 流程（仅加「环境失败不开 issue」一个分支）；
- 不处理 #478 / #533 等其它签名的历史失败。

## 3. 逐文件修复内容（before → after）

### 3.1 `scripts/nightly_test.sh` — 三处改动

**(a) L119 安装面**（run_tests 子壳内）：

```bash
# before
    uv sync --frozen --extra dev
    uv run pytest tests/ -v --tb=short -ra

# after
    # 守 lockfile，不漂移依赖；#519 拆出 [embed] 后全量测试须显式装（#559）
    uv sync --frozen --extra dev --extra embed
    # #559 fail-fast：embed 组件缺失立即失败，避免 9 个误导性测试失败 + 垃圾 issue
    if ! uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; then
      log "ERROR: 全量环境缺 embed 组件——检查 uv sync 是否带 --extra embed（#519/#559）"
      exit 4
    fi
    uv run pytest tests/ -v --tb=short -ra
```

要点：守卫用 worktree 内相对路径（被测代码自身的 helpers）；`--no-sync` 必须——
`uv run` 不带 `--extra` 时会把环境反向同步回无 extra（KB 已知坑），守卫就会测错环境。

**(b) 主流程尾部：rc==4 不提 issue**（关键修正，rev1 漏了）：

现状主流程是 `run_tests` 非零即 `report_failure`。若守卫 `exit 4` 不加区分，
report_failure 会对着没有 FAILED 行的日志算签名（`sha1("")` 固定值）→ **必开一个
「共 0 个失败」的垃圾 issue**。这也是现状的潜伏缺陷（uv sync 失败同样会触发）。
改为：

```bash
# before
else
  rc=$?
  log "测试失败 (rc=$rc)，提 issue"
  report_failure "$PYTEST_OUT" || log "WARN: 提 issue 失败，见本地告警"
  exit 1
fi

# after
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

（子壳内 `exit 4` → run_tests 返回 4 → 此分支拦截。cron 侧只看 cron.log。）

**(c)（待批准 D7）`--ref <ref>` 调试模式**：

现状脚本硬编码 `fetch origin main && worktree add --detach origin/main`——**合并前跑
它测的是旧代码**，本地没法验证修复。加参数（默认行为完全不变，cron 不传参）：

```bash
# 参数解析处新增
    --ref) NIGHTLY_REF="$2"; shift 2 ;;   # 调试用：测指定 ref 而非 origin/main

# run_tests 内
  git -C "$REPO_ROOT" fetch -q origin main
  local ref="${NIGHTLY_REF:-origin/main}"
  git -C "$REPO_ROOT" worktree add -q --detach "$wt" "$ref"

# 备份检查处：NIGHTLY_REF 非空时跳过（调试模式不依赖备份状态）
# 主流程失败分支：NIGHTLY_REF 非空时不 report_failure（调试模式绝不动 GitHub）
```

用法：`bash <fix-worktree>/scripts/nightly_test.sh --ref issue-559-nightly-embed-env`
（必须用修复分支里的脚本跑，主 checkout 的旧脚本没有 --ref）。

### 3.2 `scripts/nightly_test_helpers.py` — 纯函数 + 子命令

对齐现有 `_cli()` 分发风格（返回 int，不 sys.exit）、stdlib-only（cron 极简环境）：

```python
import importlib  # 顶部新增

def embed_components_available(
    import_module: Callable[[str], Any] = importlib.import_module,
) -> tuple[bool, list[str]]:
    """#559: 探测全量测试所需 embed 组件是否可导入（无副作用，可注入测试）。

    Returns:
        (是否全部可用, 缺失组件清单，固定顺序 torch → sentence_transformers)
    """
    missing: list[str] = []
    for name in ("torch", "sentence_transformers"):
        try:
            import_module(name)
        except ImportError:
            missing.append(name)
    return (not missing, missing)

# _cli() 内新增分支（对齐 check-backup 的 0/1 语义）
    if cmd == "check-embed-env":
        # 退出码 0=组件齐，1=有缺失（stdout 列缺失清单）
        ok, missing = embed_components_available()
        if not ok:
            print("missing: " + ", ".join(missing))
        return 0 if ok else 1
```

### 3.3 `docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md` §6

命令同步为 `uv sync --frozen --extra dev --extra embed`，加一行注记：
「#519 拆出 [embed] 后全量测试须显式安装；曾漏改致 #559，勿再省略」。
须过 markdownlint CI 门禁。

### 3.4 `tests/unit/test_nightly_test_helpers.py` — 追加 A1/A2 用例

- `embed_components_available` 三分支（假 importer 字典驱动：全齐 / 全缺 / 缺其一）；
- `_cli()` 的 `check-embed-env` 分发（monkeypatch `sys.argv`，探测函数再打桩）。

### 3.5 `tests/unit/test_nightly_script_env.py` — 新增静态守卫

纯函数 `parse_sync_extras(script_text) -> set[str]`（只解析 `uv sync` 行）+ 断言：
脚本 sync 行 extras ⊇ {dev, embed} 且含 `--frozen`；含 `check-embed-env` 且以
`--no-sync` 调用；含 rc==4 不提 issue 分支；（D7 批准则）含 `--ref` 解析；
设计文档 §6 含 `--extra embed`。负例用合成文本测解析函数本身。

## 4. 本地调试手册（分层，从秒级到 10 分钟）

**先说清脚本结构，调试才知道在哪一层**：nightly = 备份检查 → 建 worktree(origin/main)
→ 假 HOME 沙箱（uv/HF 缓存指回真实路径）→ `uv sync`（安装段）→（修后：守卫段）
→ `uv run pytest tests/` 全量（测试段）→ 失败则算签名提/续 issue（报告段）。
下面 L0-L3 不碰脚本本体，直接复刻对应层的语义；L4 跑真脚本。

### L0 · 复现「修前红」（~1 分钟，root cause 证据）

```bash
cd <repo 或 fix-worktree>
export UV_PROJECT_ENVIRONMENT=/tmp/venv-light-559
uv sync --frozen --extra dev                       # 复刻修前安装段
uv run --no-sync python -m pytest \
  "tests/test_embedding_device.py::TestDeviceResolution::test_auto_resolves_to_cpu_when_no_cuda" \
  "tests/performance/test_performance.py::TestModelCache::test_clear_removes_cache" \
  tests/test_json_schema_contract.py -q --timeout=90
# 预期：3 failed —— torch 缺、sentence_transformers 缺、embed_dependency_missing
```

### L1 · 单测层（秒级）

```bash
uv run pytest tests/unit/test_nightly_test_helpers.py tests/unit/test_nightly_script_env.py -q
# 预期：全绿（A1-A4）
```

### L2 · 守卫子命令双分支实测（秒级，复用 L0 的轻装 venv）

```bash
# 分支 1：dev 环境（有 embed）→ 放行
uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; echo rc=$?
# 预期：无 missing 输出，rc=0

# 分支 2：轻装环境（L0 已建）→ 拒绝
UV_PROJECT_ENVIRONMENT=/tmp/venv-light-559 \
  uv run --no-sync python scripts/nightly_test_helpers.py check-embed-env; echo rc=$?
# 预期：stdout "missing: torch, sentence_transformers"，rc=1
```

### L3 · 修复效果验证（依赖层，缓存命中秒级）

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/venv-full-559
uv sync --frozen --extra dev --extra embed          # 复刻修后安装段
uv run --no-sync python -c "import torch, sentence_transformers; print('embed OK')"
# 重跑 L0 的三个用例 → 预期 3 passed（9 失败的三个类别全消）
```

### L4 · 全脚本 E2E（~10 分钟；依赖 D7 批准）

```bash
bash <fix-worktree>/scripts/nightly_test.sh --ref issue-559-nightly-embed-env
# 预期链路：跳过备份检查 → worktree 建在本分支 → sync 装 embed（+torch==… 或缓存命中）
# → 守卫通过 → pytest 汇总 0 failed → 退出 0；--ref 模式不提 issue、不动 GitHub
```

若 D7 不批：pre-merge 以 L0-L3 + 手动复刻子壳（cd worktree、export 沙箱变量、
跑修后的 sync+守卫+全量 pytest）为验收，E2E 留给合并后首个 cron（U2）。

### L5 · 合并后 cron 观察（U2，自然周期）

下个周二 09:00 后查 `~/.jfox-nightly-test/cron.log`（无 ERROR、测试通过）与
issue #559（无同签名新评论/新 issue）。

清理：L0/L3 的 /tmp venv 用完 `rm -rf`。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `embed_components_available` 语义 | 自动化验证（unit） | `uv run pytest tests/unit/test_nightly_test_helpers.py -q` | 假 importer：全齐→`(True,[])`；全缺→`(False,["torch","sentence_transformers"])`；缺其一→清单仅含缺项且顺序稳定 |
| A2 | `check-embed-env` 分发 | 自动化验证（unit） | 同上（monkeypatch `sys.argv` 调 `_cli()`） | 齐→0；缺→1 且打印缺失清单 |
| A3 | 脚本安装面静态契约 | 自动化验证（static） | `uv run pytest tests/unit/test_nightly_script_env.py -q` | `parse_sync_extras(当前脚本)` ⊇ {dev,embed} 且含 `--frozen`；合成负例可被识别 |
| A4 | 守卫 wiring + rc==4 分支 | 自动化验证（static） | 同 A3 文件 | 脚本含 `check-embed-env`、`--no-sync`、rc==4 不提 issue 分支 |
| A5 | 设计文档同步 + lint | 自动化验证（static+build） | A3 文件断言 + `npx --yes markdownlint-cli2` | 文档 §6 含 `--extra embed`；lint 0 error |
| A6 | 相关单测全量 | 自动化验证（unit） | `uv run pytest tests/unit/test_nightly_test_helpers.py tests/unit/test_nightly_script_env.py tests/unit/test_pyproject_embed_extra.py -q` | 全部通过 |
| U1 | 修复效果（依赖层） | 用户实测 | 手册 L0→L3 按序执行 | L0 复现 3 failed；L2 双分支 rc 符合预期；L3 三用例 3 passed |
| U2 | 全脚本/cron E2E | 用户实测 | D7 批准：L4 一次 + 合并后首个周二 cron 复核；不批：仅 cron 复核 | L4 全链 0 failed 且不提 issue；cron.log 无 ERROR；#559 无同签名复发 |

自动化项均可秒级本地执行（纯函数 + 文件读取，无 subprocess、无网络、无模型）；
U1/U2 涉及真实安装与 9 分钟全量/沙箱机制，无法在 unit 层等价复现，按流程归用户实测。

## 6. 可测性拆分设计（自动化项的硬约束）

| 函数/边界 | 签名 | 纯度 | 测试方式 |
|-----------|------|------|----------|
| `embed_components_available` | `(import_module) -> tuple[bool, list[str]]` | 纯（依赖注入；固定探测顺序） | 假 importer 覆盖三分支；不碰真实 sys.modules |
| `parse_sync_extras` | `(script_text) -> set[str]` | 纯（行扫描+正则） | 真实脚本文本 + 合成正负例；忽略注释与非 sync 行 |
| `_cli()` 的 `check-embed-env` 分支 | argv → int + stdout | 壳（wiring） | monkeypatch `sys.argv`；探测语义全权委托注入点 |

实现不得把纯函数逻辑耦合进 shell 或真实 import；shell 侧只保留调用与退出码传播
（A4 静态断言锁定）。

## 7. 风险与缓解

| 风险 | 评估 | 缓解 |
|------|------|------|
| 修复后首跑在沙箱 venv 装 torch/CUDA（GB 级） | 低——`UV_CACHE_DIR` 指回真实缓存，dev 环境已装 embed，wheel 应全命中 | 未命中属一次性；L4/U2 观察安装段时长 |
| `uv run` 无 `--extra` 反向重同步 | 中——守卫会测错环境 | 强制 `--no-sync`；A4 断言锁定 |
| 守卫失败误开「0 失败」垃圾 issue | 已消——rc==4 分支拦截（3.1b）；uv sync 失败的同类潜伏缺陷暂不动（见开放问题 4） | A4 断言锁定分支存在 |
| `--ref` 改动破坏 cron 行为 | 低——默认值 origin/main，cron 不传参；路径全走既有逻辑 | A3 断言默认 ref 逻辑保留；U2 cron 复核 |
| 设计文档改动破坏 markdownlint | 低 | A5 双重验证 |
| helpers 引第三方依赖 | 低 | D 约束 stdlib-only（现状即如此） |

## 8. 变更文件清单（实现预估）

| 文件 | 改动量 |
|------|--------|
| `scripts/nightly_test.sh` | 3.1a ≈6 行；3.1b ≈5 行；3.1c（D7）≈12 行 |
| `scripts/nightly_test_helpers.py` | ≈25 行（函数 + 分支 + import） |
| `docs/superpowers/specs/2026-07-28-nightly-fulltest-design.md` | 2 行 |
| `tests/unit/test_nightly_script_env.py` | 新增 ≈90 行 |
| `tests/unit/test_nightly_test_helpers.py` | 追加 ≈40 行 |

## 9. 开放问题（需用户拍板）

1. **D7 `--ref` 调试模式**：批不批？批了 U1/U2 的 E2E 才能合并前本地跑（推荐批，
   cron 行为零变化）；不批则 E2E 只能等合并后 cron。
2. 守卫失败退出码 4 + rc==4 不提 issue 的分支（3.1b）是否认可？（rev1 的隐患修正，
   不加必开垃圾 issue。）
3. uv sync 自身失败的同类潜伏缺陷（现状会开「0 失败」垃圾 issue）要不要顺手一并
   包进 rc==4？（3 行；默认不包，守住本 issue 范围。）
4. #559 关闭时机：U1 通过随修复 PR 关闭（沿 #478 惯例），U2 留观察。
