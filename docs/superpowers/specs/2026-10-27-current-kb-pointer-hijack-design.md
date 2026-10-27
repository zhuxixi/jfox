# 根因报告 / spec: 全局 current-KB 指针劫持（issue #584）

Drafted: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-27T08:10:00+08:00
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-27T08:20:00+08:00 —— spec-cross-review 第 1 轮：3 真缺口（A5 缺失 / U 项无部署前置与假阴性 / P3 取值接缝）+ 5 细化全部「接受并改」，详见 research/spec-review-round-1.md
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-27T08:32:00+08:00 —— 第 2 轮收敛（0 真缺口 / 4 通过）；5 条细化全部「接受并改」（U1 前置补 A5、版本校验改路径校验、§6 断点清单校正、A1 补第五格、行号校正），详见 research/spec-review-round-2.md

## 0. 结论（先给结论）

**直接原因：`jfox init` 的 `--default` 选项默认值为 True——任何非 pytest 调用（手动脚本、一次性复现、外部工具）执行 `jfox init --name test_xxx --path ...` 都会把全局 current-KB 切到该临时库；进程在清理前退出/崩溃时，指针就留在临时库，后续真实会话不带 `--kb` 的写入被静默导流。**

**已排除（重要纠正）**：仓库内 pytest 路径**已经隔离**——`tests/conftest.py` 自 #469（`bf270d1`，2026-08-30）起无条件设置 `ZK_CONFIG_PATH` + `ZK_KB_ROOT` 指向临时目录（`tests/conftest.py:19-26`），CLI 子进程继承（`tests/utils/jfox_cli.py:139`）。隔离本身有契约测试（`tests/unit/test_global_config.py:173-225`）。实测：跑 106 个单测后真实 `~/.zk_config.json` 的 mtime 完全未变。三个遗留 worktree（#390 / pr335 / pr344）的 conftest 无隔离，但 `.pytest_cache` 停在 2026-07/08；`jfox-mdbot/tests/conftest.py:26` 同样有隔离。

**次因**：`GlobalConfigManager.remove_knowledge_base()` 在删除当前 default 库时回退到 `next(iter(knowledge_bases.keys()))`（`jfox/global_config.py:835`，任意第一个键），而不是优先名为 `default` 的库。

**放大因素**：`jfox add/edit` 的 `--json` 输出不含**实际写入的库名**（`jfox/cli.py:746-756`），写入方无法自检。

**实施前置（最大风险）**：P1 改掉 `init` 默认切库后，`ZKCLI.init()`（`tests/utils/jfox_cli.py:193-198`）必须同步传 `--default`，否则依赖 current 指针的测试会红——见 A5。

## 1. 复现（沙箱，真实配置未被触碰）

方法：`HOME=<tmp>` 重定向后执行，隔离全局配置。

| 步骤 | 命令（HOME=沙箱） | 观察结果 |
|---|---|---|
| 1 | 首次加载 | 自动注册 `default`（路径 `<sandbox>/.zettelkasten/default`，0 条） |
| 2 | `jfox init --name test_abc123 --path <sandbox>/.zettelkasten/zk_test_abc/kb` | success；**current 立即变为 test_abc123**（`init` 的 `--default` 默认 True） |
| 3 | 模拟 crash：不执行任何 cleanup，直接 `jfox add "探针" --type fleeting` | 写入成功，落在 test_abc123 的 KB 内 |
| 4 | `jfox kb remove test_abc123 --force` | current 回退到 `default`（本次 keys 顺序恰好 default 在前；若顺序不同则回退目标不可控） |

关键结论：**劫持发生在 `init` 这一步，不需要任何测试框架参与**；`ZKCLI.init()` 只是恰好用了 `jfox init`，而 conftest 的隔离把它的影响限制在沙箱内。

## 2. 事故证据（2026-10-20）

- `~/.zk_config.json` mtime 08:36；新增 `test_82b49c03`（path `zk_test_fd39a434/kb`）与 `test_a21bca37`（path `zk_test_c6f28539/kb`），`default` 字段 = `test_a21bca37`
- 08:42–08:43 本会话 4 次 `jfox add` 的笔记全部落进 `zk_test_c6f28539/kb`；`default` 库 1074 个文件与索引未变
- 恢复：`jfox kb use default` + 在 default 重做全部写入，无数据丢失
- 同类前科：2026-10-12 的 `repro547_*` 目录与 `test_5d184fc3` / `test_4eec2fce` 两个临时库同样注册进了真实配置

## 3. 修复方案（分层，推荐 P1+P2+P3+P4）

| 编号 | 层 | 改动 | 说明 |
|---|---|---|---|
| P1 | CLI（核心） | `jfox init` 的默认语义：**显式 `--default`/`--no-default` 优先；未显式指定时，仅 `name == "default"` 切 current**；`--name X` 默认不切 | 直接消灭「创建临时库即劫持路由」这一类事故。**行为变更，需用户拍板**；`--no-default` 已存在，可作为过渡/逃生舱。**实施前置：`ZKCLI.init()` 改为 `jfox init --default`（A5）** |
| P2 | 配置（防御） | `remove_knowledge_base()` 回退逻辑：优先选名为 `default` 的库；若不存在，选第一个非 `test_*`/`zk_test_*` 的库；全为测试库时直接赋值 `config.default = DEFAULT_KB_NAME`（不走 `set_default()` 的键校验），不注册该键 | 消除任意回退；纯函数可单测。**边界（明说不保证）**：① 前缀判定是启发式，命名不以 `test_`/`zk_test_` 开头的残留（#373 案例如 `bookshelf-verify-349`）不在防护内；② 悬空 default 的下游展示以 `get_default_kb_path()` 兜底（`jfox/global_config.py:769-777`，回退 `DEFAULT_KB_PATH/"default"`）；③ 用户正当命名 `test_*` 的库会被回退跳过，接受该取舍 |
| P3 | CLI（可观测） | `add/edit/promote` 的 `--json` 增加 `kb` 字段（**实际写入库名**）；写入库名匹配 `test_*`/`zk_test_*` 且未显式 `--kb` 时，`logging.warning` 输出（stderr，不污染 stdout JSON） | 让「写错库」从静默变为可发现；新增字段向后兼容。**取值接缝（钉死单一来源）**：在命令层计算 `effective_kb = kb or os.environ.get("JFOX_KB") or get_default_kb_name()`（与 `use_kb` 解析优先级一致，`jfox/config.py:172`），或让 `use_kb` yield resolved name。**禁止**用 `cfg.base_dir.name`（事故形态 `zk_test_*/kb` 的目录名恒为 `"kb"`）；也**禁止**直接用 `get_default_kb_name()`（`--kb foo` 时会谎报 default，`jfox/cli.py:896`） |
| P4 | skill（兜底） | session-to-permanent 落库前 `jfox kb current` 核对，不符预期则停并报告 | 已在 #575 讨论中记录；可随本 issue 一起落（或独立小 PR） |

不被采纳的选项：

- **只靠 conftest 隔离**：已证明覆盖不到非 pytest 调用（手动脚本/repro/外部工具）。
- **把 `temp_kb` 的 cleanup 写更强**：治不了「`init` 本身劫持 + 崩溃」。
- **删除用户测试库/自动清理**：越权且有数据风险。

## 4. 非目标

- 不改 `tests/conftest.py` 的现有隔离（已有效）；不改 `temp_kb_registered` 的 cleanup 语义。
- 不改 `jfox kb use/switch` 的显式语义（用户主动切库不受影响）。
- 不做自动删除/自动迁移笔记。
- 不动 daemon、索引、备份。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | init 默认不劫持（P1） | 自动化验证（unit + integration） | unit：`should_switch_default` 真值表五格——`("default", None)=True`、`("foo", None)=False`、`("foo", True)=True`、`("foo", False)=False`、`("default", False)=False`（显式 flag 优先）；integration：`jfox init --name X`（不带 flag）→ current 不变；`--default` → 变化；`--no-default` → 不变 | 真值表与 CLI 接线均通过 |
| A2 | remove 回退优先 default（P2） | 自动化验证（unit） | 构造 keys 顺序 `[test_a, default]`，删除 test_a（当前 default）→ current == "default"；构造仅 `test_*` 的配置 → `config.default == DEFAULT_KB_NAME` 且 `get_default_kb_path() == DEFAULT_KB_PATH/"default"` | 两条断言通过 |
| A3a | 写入库名可观测——成功路径（P3） | 自动化验证（unit + integration） | `jfox add --json` 含 `kb` 字段且等于实际写入库名；`--kb foo` 与不带 `--kb` 各验一次；写入 `test_*` 库时 WARNING 出现在 caplog、stdout JSON 仍可解析 | 字段值准确、JSON 纯净、WARNING 命中 |
| A3b | 写入库名可观测——失败分支（P3） | 自动化验证（integration） | #383 duplicate 分支的 JSON（`skipped: duplicate`，`jfox/cli.py:914-922`）同样含 `kb` 字段；WARNING 判定与成功路径一致 | 失败分支 JSON 含准确 kb 字段 |
| A4 | skill 兜底条款（P4） | 自动化验证（static） | 三文件路径：`skills-recommend/pi/jfox-session-to-permanent/SKILL.md`、`packages/cc-plugin/skills/session-to-permanent/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`；grep「`jfox kb current` 核对」+ `npx --yes markdownlint-cli2 <三文件>` | 三文件命中、语义锚定「落库（add/edit）前执行、不符即停」、lint 0 issues |
| A5 | 实施前置：ZKCLI 同步（P1 的伴生改动） | 自动化验证（integration） | `tests/utils/jfox_cli.py:193-198` 的 `init()` 显式传 `--default`；`uv run pytest tests/ -m "not embedding and not slow"`（CI Fast 口径）全绿；最小冒烟集 `uv run pytest tests/test_kb_current.py` | 全绿；`test_kb_current.py`、`tests/test_core_workflow.py::test_kb_switch_workflow` 通过 |
| U1 | 真实劫持路径回归 | 用户实测 | **时机**：修复合入 main 后（或修复 worktree 内用 `uv run jfox`）；**前置**：A5（含 CI Fast 全绿）先行通过；执行路径校验——在修复 checkout 内跑 `uv run python -c "import jfox; print(jfox.__file__)"` 确认指向修复 checkout（或 `command -v jfox` 确认非全局安装）。**注意：发版前版本号保持 1.16.3，`--version` 不能作为判据**（AGENTS.md 发版规则）。**步骤**：`jfox init --name test_probe --path ~/.zettelkasten/zk_test_probe/kb` → `jfox kb current` | current 仍为 default；`jfox kb remove test_probe --force` 后无残留 |
| U2 | 默认库初始化回归 | 用户实测 | **时机/前置同 U1**（旧构建上该断言无区分力）。**步骤**：在新 HOME 下 `jfox init`；再 `jfox init --name demo --default` | 默认库创建并切为 current；`--default` 显式切换仍生效 |

**可测性拆分设计**：

- P1：把「创建后是否切 current」抽成纯函数 `should_switch_default(name: str, explicit_default: Optional[bool]) -> bool`（放 `jfox/kb_manager.py` 或 `global_config.py`），CLI 只做参数映射；unit 覆盖四格真值表，integration 用 ZKCLI/CliRunner 覆盖 typer Option 接线（防「只改纯函数、CLI 仍默认 True」）。
- P2：把回退选择抽成纯函数 `pick_fallback_default(names: Iterable[str], removed: str) -> Optional[str]`，单测用字典顺序/测试前缀组合覆盖；`remove_knowledge_base` 只负责应用结果与 `_save`。
- P3：`effective_kb` 计算抽成纯函数（输入 kb/ENV/default 三个值，输出 resolved name），命令层只取值与输出；`--json` 的 `kb` 字段在 CLI 组装层加；WARNING 用 `logging.warning`（默认 stderr，JSON 走 stdout，互不污染），单测用 caplog 断言；集成测试复用 `cli` fixture 覆盖带/不带 `--kb` 两条路径 + duplicate 分支。
- P4：纯文本条款，static grep 验证。

## 6. 风险与回滚

| 风险 | 对策 |
|---|---|
| P1 行为变更：依赖 `jfox init --name X` 自动切库的脚本/文档 | 全仓 grep `jfox init` 引用（README/skills/scripts）并同步；changelog 标注；`--default` 显式逃生 |
| P1 对现有测试的影响 | **机制**：`ZKCLI._run` 对非 init/kb 命令会自动追加 `--kb <kb_name>`（`tests/utils/jfox_cli.py:66-69`），所以 add/list/search 不受影响。无条件红点是 `tests/test_kb_current.py:72`（笔记经 `--kb` 写进测试库、`total_notes >= 3` 却读 current 指向的库）及 `:24`/`:97`（current 悬空时 `kb current` 报错）；`tests/test_core_workflow.py:475-478`（`returncode in [0,1,2]`）与 `tests/test_kb_current.py:91-106` 的 add/list 断言**不依赖** current，不在断点清单。`ZKCLI.init()` 加 `--default` 可一并保住这些断言。A5 覆盖全仓 Fast 回归 |
| P3 取值接缝 | 已在 §3 P3 钉死单一来源（`--kb` > `JFOX_KB` > default），禁止 `base_dir.name` 与裸 `get_default_kb_name()`；A3a 用带/不带 `--kb` 两条路径验证 |
| P3 新增 WARNING 影响严格解析 stderr 的调用方 | WARNING 走 logging（默认 stderr），不写 stdout；JSON 纯净性由 A3a 断言。**不采纳**「仅 -v 输出」退路（与验收矛盾） |
| 回滚 | P1/P2 均为小改动，可单独 revert；P3 是新增字段/日志，删除即可 |

## 7. 关联

- #584（本 issue）、#575（U1 首跑发现；P4 与其 skill 文本同源）
- #373（测试配置隔离的既有追踪）、#469（`ZK_CONFIG_PATH` 隔离补丁）
- #528 / #385（并发写手防护系列）

## 8. 环境

jfox 1.16.3；main（PR #581 合并后）；default KB ~1074 permanent；复现于沙箱 HOME。
