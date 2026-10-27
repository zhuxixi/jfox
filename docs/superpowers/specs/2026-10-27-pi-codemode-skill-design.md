# Spec — #585 用 pi codemode 封装 jfox-session-to-permanent 的机械步骤

Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-20T22:45:00+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-20T23:05:00+08:00 (round 1: jq 处数更正、A6 谓词收窄、codemode 默认关闭)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-20T23:10:00+08:00 (round 2: U1/U2 部署前置与隔离库、D3 修正为按模板分治)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-20T23:14:00+08:00 (round 3: U2 播种步骤、技能加载路径更正为 settings packages)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-20T23:25:00+08:00 (round 4: duplicate 分支拆出 U3、补 codemode 硬前置)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-27T23:14:00+08:00 (v7 重新基线化：按 #586 的 `jfox similarity check` 分位判定重写模板二与验收，删除阈值常量与 A7，见 §10)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-27T23:20:00+08:00 (v8 第 5 轮: MOC 信号来源修正、补 daemon 前置、版本判据改能力判据、A7 收窄)

## 1. 目标与非目标

**目标**：让 pi 副本的 `jfox-session-to-permanent` 在机械步骤上用 codemode 一次完成，减少模型往返轮次与上下文体积，并把「落库前重查 → 写入」压进同一脚本；同时保留完整 bash 流程作为 fallback。

**非目标**（明确不做）：

- 不改 jfox Python 代码或 CLI 行为（输出裁剪选项不在本 issue 范围）。
- 不改 cc-plugin / kimi-plugin 副本的 codemode 相关内容（那两个平台没有 codemode）。
- **不改判重判定逻辑本身**：S2② 的语义由 #586 的 `jfox similarity check` 决定，本 issue 只调用它。
- 不调分位策略参数（`pass_below` / `gray_below`，初始 50/90）——那是 #586 的 dogfood 校准范围。
- 不改流程语义：Step 2 判定表、S1–S5 判定标准、Step 4 审阅硬约束、一事实一笔记等规则一字不改。
- 不引入通用封装库、不新增依赖、不提供可执行脚本文件。
- 不消除 #528 的并发竞态，只收窄窗口。

## 2. 设计决策

| # | 决策 | 选择 | 备选与否决理由 |
|---|---|---|---|
| D1 | codemode 内容放在哪 | 新增独立一级段 `## codemode 加速（pi 专属）`，位置在「五步流程」之后、「命令参考」之前；Steps 内只加 3 行指针 | ①就地替换 bash 示例 → 丢掉 fallback，非 pi 读者拿到不可用内容；②每步写双路径 → 规则与机制交织、文档翻倍 |
| D2 | 给几个模板 | 2 个（批量去重查询、自动档原子落库）+ 1 张封装点映射表 | 模板过多拉长文档；codemode 脚本对模型是普通代码，其余封装点现场仿写即可 |
| D3 | 脚本是否内嵌判定规则 | **都不内嵌**。模板一只产数据；模板二只读 `jfox similarity check` 返回的 `verdict` 做分派。判定逻辑全部留在 jfox 内部 | v6 曾因「原子性要求脚本自己判阈值」而内嵌常量，与「单一事实源」冲突。#586 把判定收进 CLI 后，原子性不再需要脚本复制规则：脚本顺序执行「check → add」即可，矛盾消失 |
| D4 | 自动档脚本是否传 `--force` | 禁止传。收到 `skipped: duplicate` 即降级人工 | 传 `--force` 会掀掉 #383 防重闸门 |
| D5 | fallback 怎么表达 | 段首一句「`codemode` 工具不可用时整段跳过，按上文 bash 流程执行，语义不变」；不写运行时探测代码 | pi 没有检测 codemode 可用性的命令。**codemode 默认不启用**（不在 `defaultTools` 中），所以 fallback 是常态路径 |
| D6 | 三平台差异怎么处理 | pi 副本段标题带「（pi 专属）」；cc/kimi 不改；加静态测试防止内容被盲 copy 过去 | 回避差异会让后来者以为三平台等价（#528/#451 都强调过对等） |
| D7 | 是否顺带解 #558 的 pi 侧 jq 依赖 | 是。Step 5 的 **1 处** jq（`SKILL.md:270`）改为 `jfox show <id> > file` 重定向 | 已实测：`jfox show` 输出无 ANSI 原始 Markdown，`edit --content-file` 输入归一化剥 frontmatter 与 H1，回灌不产生重复 H1（#200/#451 一致）。去 jq 后 fallback 无外部依赖 |
| D8 | 模板是否复用 `jfox similarity check` 而非自己算分 | 复用。模板一、模板二都调用它 | #586 已提供分位判定；自己算分等于复制判定逻辑，且会重新引入绝对阈值问题（#586 立项的直接原因） |

## 3. 内容契约（要写进 SKILL.md 的东西）

### 3.1 新增段骨架

```
## codemode 加速（pi 专属）

<一句话：本段只提供执行机制，规则仍以五步流程为准；codemode 不可用时整段跳过。>

### 封装点映射
| 步骤 | 能否封装 | 收益 |
（Step 2 去重 / Step 3.5 S1 / S2 / S5 / Step 5 批量落库 / Step 1·3·4 不封装）

### 模板一：批量去重查询（Step 2）
<JS 模板>

### 模板二：自动档原子落库（Step 5，仅高确信 + 已授权）
<JS 模板>

### verdict 到结局的映射
<四态表格，见 §3.4>
```

### 3.2 模板一契约（批量去重查询）

- 输入：候选列表（`{title, summary}` 内联在脚本里，不读外部文件）。
- 每条候选并行跑三条命令：
  1. `jfox search "<summary>" --top 10 --json` —— **不加 `--type`**：这是唯一能同时拿到两类信号的查法。`metadata.type == "permanent"` 的命中是「已覆盖」候选；`metadata.type == "structure"` 的条目是 MOC 信号。加 `--type permanent` 会把 structure 过滤掉（`models.py` 的 NoteType 过滤），MOC 信号就无源了。
  2. `jfox similarity check --title "<title>" --content "<summary>" --json` —— 拿 `verdict` 与 `top1`。
  3. `jfox search "<summary>" --type candidate --json` —— S2③ 的 pending 检查。
- **不调用 `jfox suggest-links`**：其语义分支恒空（#583），分数是关键词比率，不能当 MOC 信号源。MOC 信号改由第 1 条命令的结果按 `metadata.type` 拆分获得，语义职能交给 `similarity check`。
- 输出（每条候选一条）：`title`、`permanent_hits[]`（id/title）、`verdict`、`top1{id,title,score,percentile}`、`moc_signals[]`（第 1 条结果里 `type == structure` 的 id/title/score）、`pending_candidates[]`、`error`。
- 脚本**不**输出 `document` 字段，**不**输出 `baseline` / `matches` 全量，**不**做分档判定。
- 禁止出现 `--mode semantic`（由 `tests/unit/test_session_dedup_skill_docs.py` 对三份 SKILL.md 全局断言）。
- `timeout_ms: 180000`；单条失败走 `allSettled`，记 `error` 不中断整批。

### 3.3 模板二契约（自动档原子落库）

- 前置：Step 3.5 已判为高确信 + 用户会话内已授权。
- 每条候选的流水**顺序固定**（不能并行交错，否则 `add` 会引用未落盘的草稿）：
  1. `tools.write` 把草稿写到临时文件（沙箱无文件系统，必须经工具写盘）；
  2. `jfox similarity check --title <t> --content-file <tmp> --json`（S2④ 重查）；
  3. 读 `verdict`：`new` → 继续第 4 步；`gray` / `covered` → 终止，结局 `needs_manual`；`unavailable` / 字段缺失 / 非零退出 → 终止，结局 `signal_missing`；
  4. `jfox add --content-file <tmp> --title <t> --type permanent --tag auto-distilled --tag <主题> --json`（**不带 `--force`**）；
  5. 解析返回：`success: true` → `added`；`skipped: duplicate` → `duplicate`（带 `matched_id`）；其他 → `error`。
- 多条候选之间用 `Promise.allSettled` 并行，每条内部保持上面的顺序。
- 输出：逐条 `{title, outcome, note_id?, matched_id?, verdict?, reason?}` + 汇总计数。
- 非零退出码不视为脚本失败（`bash` 工具返回 `exit_code`，脚本按字段判读）。

### 3.4 verdict 到结局的映射（写进 SKILL.md 的表格）

| `similarity check` 返回 | 模板二动作 | 结局 |
|---|---|---|
| `verdict=new` | 继续执行 `jfox add` | `added`（或 `duplicate`，见下） |
| `verdict=gray` | 不写入 | `needs_manual` |
| `verdict=covered` | 不写入，提示按「可补充/已覆盖」走原流程 | `needs_manual` |
| `verdict=unavailable` | 不写入（fail-closed） | `signal_missing` |
| 无 `verdict` 字段 / 非零退出 | 不写入（fail-closed） | `signal_missing` |
| `add` 返 `skipped: duplicate` | 不再重试 | `duplicate`（带 `matched_id`） |

### 3.5 指针行（Steps 内，各一行）

- Step 2 末尾：`> pi 平台可用 §codemode 加速 的模板一把全部候选的查询合并为一次调用。`
- Step 3.5 S1/S2/S5 末：`> pi 平台可用 §codemode 加速 批量执行本节机械检查。`
- Step 5 自动档末：`> pi 平台可用 §codemode 加速 的模板二把「重查 → 写入」压进同一脚本。`

## 4. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|---|---|---|---|---|
| A1 | pi 副本新增 codemode 段且含 fallback 声明 | 自动化（unit） | 新增 `tests/unit/test_pi_codemode_skill_docs.py` | 段标题、fallback 关键词、两个模板标题均存在 |
| A2 | cc/kimi 副本未被注入 codemode 内容 | 自动化（unit） | 同上，参数化三份文件 | 两份副本均不含 `codemode` |
| A3 | 既有三平台契约不回归 | 自动化（unit） | `uv run pytest tests/unit/test_moc_skill_docs.py tests/unit/test_session_dedup_skill_docs.py` | 全部通过 |
| A4 | 改动文档通过 markdownlint | 自动化（static） | `npx --yes markdownlint-cli2 <三份文件>` | 0 issues |
| A5 | pi 副本 bash 路径不再依赖 jq | 自动化（static） | 新测试断言 pi SKILL.md 不含 `jq` 调用 | 通过 |
| A6 | 自动档模板不掀防重闸门 | 自动化（static） | 新测试只扫「自动档落库」小节内的**围栏代码块**，断言命令不含 `--force` | 通过（正文「不传 `--force`」合法） |
| A7 | 模板不复制判定逻辑 | 自动化（static） | 新测试只断言模板层：模板二围栏代码块含 `similarity check` 与 `verdict`；模板一围栏块不出现 `--type permanent` 与 `--mode semantic` | 通过。全文级的「禁止遗留写法」由既有 `test_session_dedup_skill_docs.py:33-34` 负责，本测试不重复其断言 |
| A8 | 模板一不内嵌分档判定 | 自动化（static） | 断言模板一围栏代码块不含 `document` 输出与分档词「已覆盖」「可补充」「未记录」 | 通过 |
| U1 | 模板一在真实 pi 会话可用 | 用户实测 | 按模板跑一批 ≥5 条候选的去重 | 单轮返回；输出体积显著小于原始 JSON；每条候选都有 `verdict` 与 `top1`；分档结果与人工判断一致 |
| U2 | 模板二 `new → added` 主路径可用 | 用户实测 | ①确认 daemon 在跑 ②隔离库播种 **≥30 条主题多样的** permanent ③对一条全新候选跑模板二 | 该候选结局 `added`；全程无 `--force`；真实默认库笔记数不变；测完清理临时目录 |
| U3 | 模板二 `covered → needs_manual` 可触发 | 用户实测 | 在同一隔离库，用一条与已播种笔记**近乎相同**的候选跑模板二 | 返回 `verdict=covered`；结局 `needs_manual`；**未写入** |
| U4 | `unavailable` 与 `duplicate` 两分支读解正确 | 用户实测 | ①空库（<30 条）跑一次 → 期望 `unavailable`；②对已存在标题执行模板二第 4 步那条 `jfox add` | ①结局 `signal_missing` 且未写入；②返回 `skipped: duplicate` + `matched_id`，脚本归类 `duplicate` 而非 `error` |

### 4.0 U1–U4 的部署前置与执行时机（必读）

- **硬前置一：`jfox similarity` 子命令可用**。判据是能力而不是版本号：`jfox similarity check --help` 成功即可（本机 1.17.0 实测成功）。不要用 `jfox --version` 判——main 的 `pyproject.toml` / `__init__.py` 版本号仍停在 1.16.3，按版本号会把已含该命令的 checkout 误判为 `blocked`。命令不存在时 U2–U4 记 `blocked`，不得退回绝对阈值流程。
- **硬前置二：embedding daemon 必须在跑**。`similarity check` 走 `daemon_only=True` 路径，daemon 不在时恒返 `verdict=unavailable`；播种的笔记若没向量，也会因「没有带 embedding 的 permanent」而 `unavailable`。启动方式见 `jfox-common` 的 daemon 节；`jfox daemon status` 可确认。
- **硬前置三：codemode 必须已启用**。codemode 默认不在 `defaultTools` 里（需显式开启，或由 MCP server 的 exposure 自动激活）。工具列表里没有 `codemode` 时 U1–U4 无法执行，应记 `blocked`，不得用 bash 冒充模板验证。
- **硬前置四：隔离库至少 30 条 permanent，且主题要多样**。`similarity check` 的分位基线要求 ≥30 条永久笔记（`MIN_BASELINE_NOTES = 30`），否则恒返 `unavailable`（`unavailable_reason: "baseline needs at least 30 permanent notes"`）。另外 percentile 是相对 baseline 分布算的（`searchsorted`），**30 条同质种子会让 `new` 和 `covered` 都不可靠**——播种需覆盖多个主题，才能让「全新候选」落进 p50 以下、「近乎相同候选」落进 p90 以上。
- **技能的真实加载路径**：jfox 的 pi 技能由 `~/.pi/agent/settings.json` 的 `packages` 声明 `"../../work/git-repo/jfox"`（指向**主 checkout**）加载，该包 `package.json` 里 `pi.skills = ["./skills-recommend/pi"]`。
- **唯一可用时机**：PR 合并 → 主 checkout `git pull` → 新开会话或 `/reload`（`docs/skills.md:89`）。合并前，改动对任何会话都不可用。
- **明确禁止的验证方式**：在 worktree 内启动 pi 跑 U1–U4（worktree 未被 `packages` 声明，会静默加载旧技能，得出假「通过」）；也不得为验收临时把 `packages` 改指向 worktree。
- **隔离库用法**：命令前缀 `ZK_CONFIG_PATH=/tmp/u-585/config.json ZK_KB_ROOT=/tmp/u-585/kbroot`。`ZK_CONFIG_PATH` 指向不存在的文件时 `_load()` 会自动造出 `default` 条目（`jfox/global_config.py:615–617`），所以**不需要**先跑 `jfox init`（跑了反而报 `already exists`）。
- **副作用声明**：U2–U4 会真实写入隔离库，不碰 `~/.zettelkasten/default`；断言方式为对比运行前后真实库笔记数不变；结束时 `rm -rf /tmp/u-585`。

### 4.1 可测性拆分设计（A1/A2/A5/A6/A7/A8）

静态文档契约，不依赖知识库、embedding、网络。拆成纯谓词 + 参数化测试：

| 单元 | 形式 | 测什么 |
|---|---|---|
| `_read(path)` | 纯函数 | 读文本（UTF-8） |
| `has_codemode_section(text)` | 纯谓词 | 存在 `## codemode 加速` 与 fallback 关键词 |
| `has_both_templates(text)` | 纯谓词 | 两个模板标题存在 |
| `uses_jq(text)` | 纯谓词 | 出现 `jq` 命令行调用 |
| `_fenced_blocks(text)` / `_section_blocks(text, heading)` | 纯函数 | 切出围栏代码块 / 指定小节的围栏代码块 |
| `auto_tier_code_blocks_use_force(text)` | 纯谓词 | 自动档小节围栏块内出现 `--force`（正文说明合法，不计入） |
| `template_two_uses_verdict(text)` | 纯谓词 | 模板二围栏块含 `similarity check` 与 `verdict` |
| `forbidden_legacy_forms(text)` | 纯谓词 | 全文出现 `--mode semantic`、`0.5–0.65`、`S2_PASS_MAX` 任一 |
| `template_one_is_data_only(text)` | 纯谓词 | 模板一围栏块不含 `document` 输出与分档词 |
| `test_*` | 参数化 | 对三份 SKILL.md 分别断言（A2 只对 cc/kimi） |

测试边界：只管「文档是否声明了该做的事」，不管脚本运行时行为——后者归 U1–U4（pi 运行时不进 CI）。这一点明说，避免用静态测试冒充运行时验证。

测试文件标记：`pytestmark = [pytest.mark.unit, pytest.mark.fast]`——已在 `tests/conftest.py:236`、`:244` 注册，符合 `pytest.ini` 的 `--strict-markers`。

## 5. 数据流

```
模型（Step 2）
  └─ codemode 脚本（模板一）：每条候选并行跑 search + similarity check + candidate 查
       └─ 模型按 Step 2 判定表分档（已覆盖/可补充/未记录）
            └─ 模型起草（Step 3）→ 用户审阅（Step 4）
                 └─ codemode 脚本（模板二，逐条顺序）：写盘 → similarity check → 读 verdict
                      ├─ new → add（无 --force）→ added / duplicate
                      └─ gray / covered / unavailable → needs_manual / signal_missing
```

## 6. 降级路径

| 失效情形 | 行为 |
|---|---|
| `codemode` 工具不可用（**默认状态**） | 整段跳过，走既有 bash 流程，语义不变 |
| `jfox similarity` 不存在（< 1.17.0） | 该批降级人工并记 `blocked`；不得退回绝对阈值 |
| 脚本内某条命令失败 | `allSettled` 捕获，该条记 `error`，其余继续；fail-closed 不把 error 当「无重复」 |
| `verdict=unavailable`（基线不足 / daemon 异常） | 该条 `signal_missing`，不写入 |
| `search_mode` 全为 `keyword` | S5 判定通道退化 → 该批降级人工 |
| `add` 返回 `skipped: duplicate` | 该条降级人工，其余候选不受影响 |
| 脚本超时 | 报告未完成条目，剩余走 bash 路径 |

## 7. 风险

| 风险 | 缓解 |
|---|---|
| `similarity check` 的分位策略参数（50/90）仍会 dogfood 校准 | 模板不复制参数，只读 `verdict`，所以参数变化不影响文档；若判定语义变化（新增 verdict 取值），§3.4 映射表需同步，A7 会因缺少 `verdict` 断言而提示 |
| 隔离库播种 ≥30 条使 U2 实测成本上升 | 播种用循环脚本（`jfox add` ×30，无需人工），并且**必须主题多样**（同质种子会让 percentile 判定失真）；这是基线硬要求，不能绕过 |
| pi codemode API 变动导致模板失效 | 段内注明依据 pi docs/codemode.md 的 `tools` / `Promise.allSettled` / `timeout_ms` 语义；模板只用最稳定接口 |
| 模型照抄模板但不懂为何不传 `--force` | 模板内注释写明「保留防重闸门」，A6 用测试固化 |
| 文档膨胀 | 新增内容目标 ≤ 120 行；其余封装点只给一句话模式描述 |
| 静态测试造成虚假安全感 | §4.1 明确测试边界，U1–U4 单独跟踪运行时验证 |

## 8. 受影响文件

- `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`（新增段 + 3 处指针 + Step 5 去 jq）
- `tests/unit/test_pi_codemode_skill_docs.py`（新增）
- 不改：`packages/cc-plugin/skills/session-to-permanent/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`

## 9. 遗留

- #558 的 cc/kimi 两份副本 jq 依赖仍在（各自范围，不在本 issue）。
- 运行时行为（U1–U4）需在真实 pi 会话验证，无法进 CI；且只能在 PR 合并后跑。
- **判重判定侧已由 #586 解决**：S2② 改为 `jfox similarity check` 分位判定，绝对阈值 0.5/0.65 已从三份 SKILL.md 移除。本 issue 只调用该命令，不复制其逻辑。
- **#437 仍 OPEN，但范围已收敛到 MOC 侧**（`moc diagnose` 输出分布与推荐阈值、draft 分组修复、kNN 评估），与本 issue 无关。
- **#444 仍 OPEN**（搜索置信度分层 / `--min-score`）；`similarity check` 的 `unavailable` 只覆盖判重场景的降级，不覆盖「搜索无匹配」的表达。与本 issue 无关。
- `jfox init` 在 `ZK_CONFIG_PATH` 指向不存在文件时必然报 `already exists`（`global_config.py:615–617` 自动造 default 条目），文档里的隔离用法建议同步修正。

## 10. v6 → v7 变更摘要（重新基线化，2026-10-27）

变更来源 #586（PR #587，v1.17.0）把 S2② 从「绝对阈值 0.5/0.65」换成「库内分位判定」，并新增契约测试 `tests/unit/test_session_dedup_skill_docs.py`，其中断言三份 SKILL.md 中 `--mode semantic` 出现次数为 0、且不得出现 `0.5–0.65`。v6 的模板二正是按旧写法设计的，直接实现会与既有契约测试冲突。本版据此重写：

| 变更点 | v6 | v7 |
|---|---|---|
| D3 | 模板二内嵌阈值常量（为原子性） | 模板二只读 `verdict`，不内嵌任何判定逻辑 |
| §3.2 模板一 | 用 `search --mode semantic` 取最高分 | 改用 `jfox similarity check`，且禁止 `--mode semantic` |
| §3.3 模板二 | 先 check 后写盘，比较 0.5/0.65 | 先写盘 → `similarity check` → 读 verdict → 写；顺序修正 |
| §3.5 | 阈值常量块 | 删除，替换为 verdict→结局映射表 |
| A7 | 常量与 S2② 文本一致性 | 模板不复制判定逻辑（含 `similarity check` + `verdict`，且无遗留写法） |
| U2/U3/U4 | 播种 2–3 条即可 | 必须 ≥30 条（基线要求）；新增 `covered` 分支验收；`unavailable` 与 `duplicate` 合并为 U4 |
| §9 | 待 #437/#444 修 | #586 已解决判重侧；#437/#444 与本 issue 解耦 |

### v7 → v8（第 5 轮复核）

| 发现 | 级别 | 修正 |
|---|---|---|
| `moc_signals[]` 无来源 | 真缺口 | 模板一第 1 条命令去掉 `--type permanent`（会把 structure 过滤掉），改为按 `metadata.type` 拆出 permanent 命中与 MOC 信号；不再依赖已知失准的 `suggest-links`（#583） |
| 缺 daemon 前置 | 细化 | §4.0 增加「embedding daemon 必须在跑」：`similarity check` 走 `daemon_only`，daemon 缺席恒返 `unavailable` |
| 播种同质会导致分位失真 | 细化 | §4.0 与 U2 要求播种覆盖多主题，否则 `new` / `covered` 都不可靠 |
| 版本判据与仓库不符 | 细化 | 硬前置改为能力判据（`jfox similarity check --help` 成功），不用 `jfox --version`——main 的版本号仍停在 1.16.3 |
| A7 与既有测试重复 | 细化 | A7 收窄到模板层；全文级禁令归 `test_session_dedup_skill_docs.py` |
