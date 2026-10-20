# Session 笔记记录 Agent 类型与 Session 文件路径（含 pi 来源接入）

Issue: [#578](https://github.com/zhuxixi/jfox/issues/578)

Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-19T08:28:42+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-19T08:45:00+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-19T09:05:00+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-19T09:20:00+08:00

## 1. 背景与问题

session 笔记是「AI Agent 会话记录」，但目前无法回答两个问题：会话由哪个 coding agent 产生、原始 transcript 在哪。具体缺口：

1. `jfox-session-summary` skill 调 `jfox add --type session`，只写 `title` / `topic` / `tags`，没有 agent 类型与会话文件信息。
2. `jfox auto-summary` 的 `_compose_note_body()` 元数据 footer 只写 cwd、分支、时间、轮次、`session_id`、`project_dir_name`；`- 来源: jfox auto-summary` 表达的是生产通道而非 agent 类型，也没有文件绝对路径。
3. pi 不是合法 session 来源：`AutoSummaryConfig.session_sources` 默认 `["claude", "kimi"]`，`get_sources()` 只分支 claude / kimi。

实测还确认：pi 的 session 文件**不保证**在官方目录。本 issue 所在的 agent-board 托管会话，文件位于 `~/.pi/agent/agent-board/sessions/view_62063a3a03.jsonl`，官方 `~/.pi/agent/sessions/` 下不存在同名文件、不存在首行 id 匹配文件、也不是硬链接。

## 2. 目标 / 非目标

**目标**

- G1 session 笔记结构化记录 `agent` / `session_file` / `agent_model` 三个字段，覆盖手工与自动两条写入路径。
- G2 pi 作为第三种 `SessionSource` 接入 auto-summary，扫描官方目录与 agent-board 目录，产出与其他来源一致的 session 笔记。
- G3 定位逻辑对「官方目录 / agent-board 目录 / 自定义 session dir」都成立，禁止从文件名推断 session id。

**非目标**

- N1 不回填历史 session 笔记。
- N2 不扫描 `~/.zima/temp/pjobs/*/pi-sessions/`（临时目录，会被清理）。
- N3 不改动正文现有「元数据」footer 的字段集合（新字段只进 frontmatter）。
- N4 不做「按 agent 类型检索/过滤」的新能力；但 `to_dict()` 会新增可选键，因此 `list` / `search` 的 `--json` 输出对含新字段的笔记会多出 `agent` / `session_file` / `agent_model`（属于 schema 扩展，需同步 `docs/json-schemas.md`，见 §4）。
- N5 不做配置自动迁移：`~/.zk_config.json` 里已显式物化的 `session_sources` 保持原样，用户需自行加入 `pi`（见 §9）。

## 3. 数据模型变更

`jfox/models.py` 的 `Note` 新增三个可选字段，均只在非空时序列化：

| 字段 | 类型 | 含义 | canonical 值 |
|---|---|---|---|
| `agent` | `Optional[str]` | 产生该会话的 coding agent | `claude-code` / `kimi-code` / `pi-coding-agent` |
| `session_file` | `Optional[str]` | 原始 session 文件绝对路径 | 任意绝对路径 |
| `agent_model` | `Optional[str]` | 会话所用模型 | `provider/modelId` |

改动点（四处必须同步，缺一即字段丢失）：

1. `Note.to_markdown()`：`if self.agent: frontmatter["agent"] = self.agent`，其余同理。
2. `Note.from_markdown()`：`agent=fm.get("agent")`、`session_file=fm.get("session_file")`、`agent_model=fm.get("agent_model")`。
3. `Note.to_dict()`：非空时写入（与 `source_fragments` 同款条件写法）。
4. `Note.to_show_dict()`：沿用现有「可选附加字段」分支，非空时写入。

命名理由：`agent` 比 `agent_type` 短且语义明确；`agent_model` 避免与向量模型 / 模板变量里的 `model` 混淆；`session_file` 与 issue 用语一致。

兼容性：老笔记无这三个键 → `None` → 不写回，`update_note` 重写不会产生字段噪音。

`to_dict()` 同时是 `list` / `search` 的 `--json` 输出来源，因此这次改动也是一次输出 schema 扩展：含新字段的笔记会多出三个可选键（边界见 N4）。

## 4. CLI 契约：`jfox add`

新增三个选项，与既有 `--source` 同构（都是「参数 → frontmatter」），不参与模板渲染：

```
--agent TEXT          产生该会话的 coding agent（canonical: claude-code / kimi-code / pi-coding-agent）
--session-path PATH   agent 原始 session 文件绝对路径
--agent-model TEXT    该会话使用的模型（provider/modelId）
```

校验规则（纯函数，见 §7）：

| 输入 | 规则 | 失败行为 |
|---|---|---|
| `--agent ""` / 全空白 | `strip()` 后必须非空 | `ValueError("--agent 不能为空")` |
| `--agent` 未知值 | 不校验枚举（允许未来 agent），仅原样存储 | — |
| `--session-path` 相对路径 | `Path(v).expanduser()` 后必须 `is_absolute()` | `ValueError("--session-path 必须是绝对路径")` |
| `--session-path` 文件不存在 | **不校验存在性**（历史记录，文件可能已删除） | 正常写入 |
| `--agent-model ""` | `strip()` 后为空则视为未提供 | 不写字段 |

传输链路：`add()` → `_add_note_impl()` → `create_note(..., agent=, session_file=, agent_model=)`。`--template` 分支在渲染后应用这三个字段，不把字段注入模板变量。

`--json` 输出：`_add_note_impl()` 的 `result["note"]` 当前只有 `id/title/type/filepath/links`，**本 issue 显式扩展该对象**——三个新字段非空时加入（不回填 `source`，避免夹带扩张）。`show --json` 走 `to_show_dict()`，同样按非空条件输出。`docs/json-schemas.md` 的 `add` 行与 `show` 行都必须更新。

## 5. pi 来源设计

### 5.1 配置

```python
session_sources: List[str] = ["claude", "kimi", "pi"]   # 默认加 pi（用户已确认）
pi_session_dirs: Optional[List[str]] = None             # None → 见下
```

**`from_dict()` 必须同步改两处**（只改 dataclass 默认值不够，生产读取路径走 `from_dict`）：

1. `session_sources` 的 else 分支字面量 `["claude", "kimi"]` 改为 `["claude", "kimi", "pi"]`；
2. 新增 `pi_session_dirs=data.get("pi_session_dirs")`，非 list 视为 `None`（与 `session_sources` 的 `isinstance` 写法一致）。

这条改动**覆盖** `docs/superpowers/specs/2026-06-16-kimi-code-auto-summary-design.md:110` 钉住的旧 fallback 契约（旧决策是「默认都开」，本次只是把新来源纳入同一决策）。`tests/unit/test_auto_summary_config_sources.py` 中三处断言旧默认（第 6 / 13 / 26 行）需同步更新。

`update_auto_summary_config()` 走 `asdict → from_dict → _save` 全量写回，因此 `from_dict` 不接 `pi_session_dirs` 的话，用户配置会在下一次 `auto-summary enable` 时被静默丢弃。

`pi_session_dirs` 为空时按顺序解析两个根，去重后返回：

1. `$PI_CODING_AGENT_SESSION_DIR`（若设置），否则 `~/.pi/agent/sessions`
2. `$AGENT_BOARD_ROOT/sessions`（若设置），否则 `~/.pi/agent/agent-board/sessions`

两个根都允许用户通过 `pi_session_dirs` 显式覆盖。`sessionDir` 这类写在 pi settings 里、没有环境变量的自定义目录不在自动发现范围内，需用户显式配置（写入 §9 的边界）。

### 5.2 扫描（`PiCodeSource.iter_sessions`）

对每个根目录，只枚举两层：

- `root/*.jsonl`（agent-board 的扁平布局）
- `root/*/*.jsonl`（官方按 encoded-cwd 分组的布局）

不递归更深层，避免把 `sessions/<viewId>/<uuid>/run-0/session.jsonl` 这类 subagent transcript 当作独立会话。

每个候选文件依次过滤：

1. 后缀 `.jsonl` 且为普通文件；
2. `size` 落在 `[min_session_size_kb*1024, max_session_size_mb*1024*1024]`；
3. `mtime` 距今 ≥ `idle_threshold_minutes`，且 `skip_after_days>0` 时不超龄；
4. 读首行 JSON，要求 `type == "session"` 且 `id` 为非空字符串；
5. 首行 `cwd` 命中 `DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS`（`jfox-auto-summary-runs` / `jfox-gem-synth-runs` / `auto-session-summary`）→ 跳过，用于阻断反馈循环；
6. 同一 `session_id` 出现多次时保留 mtime 最新的一份，其余记 debug 日志。

产出 `SessionFile(session_id=<首行 id>, project_dir_name=<见下>, path=..., mtime=..., size_bytes=..., source="pi", agent="pi-coding-agent")`。

`project_dir_name` 取**首行 `cwd` 的目录名**（`Path(cwd).name`），取不到时回退 `path.parent.name`。原因：agent-board 是扁平布局，`path.parent.name` 恒为 `sessions`，会让 ledger 的 project 字段与笔记 footer 的「项目目录」对数百个会话失去区分度。

**明确禁止**：从文件名解析 uuid。agent-board 的 `view_<hash>.jsonl`（本机 394 个）文件名与 session id 无关；42 个时间戳式文件全部是带 `parentSession` 的 fork 子会话，文件名里的 uuid 恰是它自己的 id，但不能依赖此规律。

### 5.3 提取（`extract_pi_dialog(path)`）

pi session 是 v3 树结构（条目含 `id` / `parentId`）。提取分三步：

1. **读条目**：逐行 `json.loads`，坏行跳过并 debug 记录；首行必须是 `type == "session"`。
2. **取活跃分支**：从最后一个带 `id` 的条目出发沿 `parentId` 回溯到 `None`，反转得到线性历史；任一父节点缺失时回退为文件顺序（记 debug），保证不因异常文件丢内容。
3. **抽对话**：按条目类型处理
   - `model_change`：记录 `f"{provider}/{modelId}"`，**后者覆盖前者**（多模型会话取最后一次）
   - `message`：角色与内容都在**嵌套的 `message` 子对象**里——`entry["message"]["role"]` / `entry["message"]["content"]`（pi 官方 `session-format.md:45` 与本机实机文件一致）；`user` → `用户: <text>`，`assistant` → `助手: <text>`，只取 `content` 里 `type == "text"` 的块，丢弃 `thinking` / `toolCall` / 图片；`system` / `toolResult` 角色跳过
   - `custom` / `thinking_level_change` / `session_info` 跳过

输出 `ExtractedDialog`：`cwd`（首行）、`started_at`（首行 timestamp）、`ended_at`（最后一条 message 的 timestamp）、`project_dir_name`、`user_turn_count`、`assistant_turn_count`、`agent_model`、`dialog_text`（超过 `DEFAULT_MAX_DIALOG_CHARS` 时沿用 `_truncate` 截断并置 `truncated`）。

### 5.4 工厂与 ledger

- `get_sources()` 增加 `elif name == "pi"` 分支：没有任何根目录存在时 `logger.info` 跳过（与 claude / kimi 同款 auto-detect）。
- `extract_dialog_for()` 增加 `source == "pi"` 分支，直接构造 `PiCodeSource`，不依赖目录存在性。
- ledger key 复用 `session_key()` → `pi:<session_id>`，无需迁移。

## 6. 写入链路

### 6.1 自动路径

`SessionFile` 增加 `agent: str = "claude-code"`（默认值保持 claude 行为不变）与 `agent_model: Optional[str] = None`；kimi source 显式传 `agent="kimi-code"`。

`runner.summarize_one()` 调 `_save_session_note(content, title, tags, topic, target_kb, agent=sf.agent, session_file=str(sf.path), agent_model=extracted.agent_model)`，`_save_session_note` 透传给 `create_note(...)`。

`ExtractedDialog` 增加 `agent_model` 字段，三个来源分别填充：

| 来源 | 取值 |
|---|---|
| pi | 最后一次 `model_change` 的 `provider/modelId` |
| claude | 最后一条 assistant message 的 `message.model`（本机实测存在该字段） |
| kimi | 优先 `llm.request` 的 `provider` + `model`；否则 `profile.bind.modelAlias` |

取不到则留空，不阻塞写入。

**摘要 prompt 的措辞**：`runner.SYSTEM_PROMPT` 与 `_build_user_prompt()` 的开头目前写死「Claude Code 会话」。接入 pi 后改为来源无关措辞（如「一段 coding agent 会话的对话记录」）；`jfox/prompts/` 下若有同类措辞一并检查。

**topic 兜底**：`runner.py` 在 LLM 未返回 topic 时兜底 `"claude-code-session"`，改为 `f"{sf.agent}-session"`（claude 保持原值，pi / kimi 不再被错标）。

**新增 pi 会话路径 vs 现有 footer**：footer 保持原样（含 `session_id`），路径只进 frontmatter，避免双写。

### 6.2 手工路径（skills）

| 平台 | 命令片段 |
|---|---|
| pi | `--agent pi-coding-agent --session-path "$PI_SESSION_FILE" --agent-model "$PI_PROVIDER/$PI_MODEL"`；env 未设置时省略后两个 |
| Claude Code | `--agent claude-code`；无法稳定取得 transcript 路径时省略 `--session-path` |
| Kimi Code | `--agent kimi-code`；同上 |

需要更新的 skill：`skills-recommend/pi/jfox-session-summary/SKILL.md`、`skills-recommend/kimi-cli/jfox-session-summary/SKILL.md`、`packages/cc-plugin/skills/session-summary/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-summary/SKILL.md`；`jfox-common` 的 `jfox add` 参数清单同步补三项。

## 7. 可测性拆分设计

| 拆分单元 | 位置 | 类型 | 职责 | 覆盖验收 |
|---|---|---|---|---|
| `normalize_agent(value)` | `jfox/cli.py`（或 `jfox/utils.py`） | 纯函数 | trim + 非空校验 | A2 |
| `resolve_session_path(value)` | 同上 | 纯函数 | expanduser + 绝对路径校验 | A2 |
| `parse_pi_header(line)` | `jfox/auto_summary/pi_source.py` | 纯函数 | 解析首行，校验 type/id | A3 / A4 |
| `active_branch(entries)` | `jfox/auto_summary/pi_extractor.py` | 纯函数 | parentId 链回溯 + 断链回退 | A3 |
| `dialog_from_branch(branch, max_chars)` | 同上 | 纯函数 | 按 `entry["message"]` 嵌套读取角色/内容块 → 文本 + 计数 + 截断 | A3 |
| `model_from_branch(branch)` | 同上 | 纯函数 | 最后一次 `model_change` | A3 |
| `extract_pi_dialog(path)` | 同上 | I/O 薄层 | 读文件后串起上述纯函数 | A7 |
| `resolve_pi_session_dirs(cfg)` | `jfox/auto_summary/sources.py` | 纯函数（读 env） | 两个根的默认解析与去重 | A5 |
| `iter_pi_session_files(roots, cfg)` | `pi_source.py` | I/O 薄层 | stat + 首行 + 过滤 + 同 id 去重 | A4 |

测试边界：所有判定逻辑（分支、角色、模型、blocklist、路径校验）落在纯函数，I/O 层只做「读文件 + 调用纯函数 + 产出 dataclass」，因此 A2/A3/A4/A5 全部可用 tmp_path 构造 fixture，不加载 embedding、不触碰真实 `~/.pi`。

## 8. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|---|---|---|---|---|
| A1 | `Note` 三字段 read/write 对称 | 自动化验证（unit） | `uv run pytest tests/unit/test_note_agent_fields.py -q` | 三字段非空时写入 frontmatter、解析回来相等；空值不产生键；旧笔记（无字段）解析为 None |
| A2 | `jfox add` 三参数与校验 | 自动化验证（unit，CLI subprocess） | `uv run pytest tests/unit/test_add_agent_fields.py -q` | 三字段落到 frontmatter、`add --json` 的 `note` 对象与 `show --json` 顶层；空 agent 与相对路径报错；`~` 被展开；字段为空时不出现在任何输出；指向不存在文件的绝对路径被接受且照写 |
| A3 | pi 条目解析（header / 分支 / 对话 / 模型） | 自动化验证（unit） | `uv run pytest tests/unit/test_pi_extractor.py -q` | `view_` 风格会话能被解析；fork 文件只取活跃分支；`thinking`/`toolCall` 被丢弃；多 `model_change` 取最后一次；断链回退文件顺序；fixture 必须按 `entry["message"]["role"/"content"]` 嵌套形态构造 |
| A4 | pi 扫描过滤 | 自动化验证（unit） | `uv run pytest tests/unit/test_pi_source.py -q` | 官方两层布局与 agent-board 扁平布局都能扫到；id 取自首行；size/idle 过滤生效；cwd 命中 blocklist 被跳过；同 id 保留最新；`project_dir_name` 取首行 cwd 目录名（agent-board 扁平布局不等于 `sessions`） |
| A5 | 配置默认值与工厂 | 自动化验证（unit） | `uv run pytest tests/unit/test_auto_summary_config_sources.py tests/unit/test_session_source.py -q` | `AutoSummaryConfig()`、`from_dict({})`、`from_dict({"session_sources": None})` 三条路径默认都含 pi；`pi_session_dirs` 能从 dict 读入且在 `asdict → from_dict` 后保留；默认根目录解析的 env 覆盖与去重正确；根目录缺失时跳过不报错 |
| A6 | runner 透传与来源默认值 | 自动化验证（unit） | `uv run pytest tests/unit/test_auto_summary_runner.py -q` | note 的 `agent` / `session_file` / `agent_model` 与 `SessionFile` / `ExtractedDialog` 一致；claude 来源 agent 默认 `claude-code`；模型缺失时为 None；`SYSTEM_PROMPT` 与用户 prompt 标题不含 `Claude Code` 字样；LLM 未返回 topic 时兜底为 `<agent>-session`（claude 仍为 `claude-code-session`） |
| A7 | 端到端 pi 总结 | 自动化验证（integration） | `uv run pytest tests/integration/test_auto_summary_pi.py -q` | 构造临时 pi 会话 → scan → summarize（mock LLM）→ 笔记三字段正确，ledger 记为 `pi:<id>` |
| A8 | 静态检查（对齐 CI Fast） | 自动化验证（static） | `uv run ruff check jfox/ tests/`、`uv run black --check jfox/ tests/`、`npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"`、`uv run python scripts/generate_docs.py` 后 `git diff --exit-code` | 前三条退出码 0；生成器跑完无 diff、无未跟踪生成物 |
| A9 | skill 文档与参数清单 | 自动化验证（unit，文本断言） | `uv run pytest tests/unit/test_session_summary_skill_docs.py -q` | 4 份 `jfox-session-summary` SKILL.md 与 4 处 `jfox add` 参数清单都出现 `--agent` / `--session-path` / `--agent-model`；pi 文档含 `pi-coding-agent` 与 `$PI_SESSION_FILE`；`docs/json-schemas.md` 的 `add` / `show` 两行含三个字段名 |
| U1 | 手工 skill 真实落库 | 用户实测 | **前置**：把 worktree 的 venv 放到 PATH 首位（`export PATH=<worktree>/.venv/bin:$PATH`）——skill 里是裸 `jfox`，不绑定就会解析到全局旧版、Typer 对未知选项直接报错；把更新后的 `skills-recommend/pi/jfox-session-summary/` 复制到 `~/.pi/agent/skills/`（当前为空），复制后**新起一个 pi 会话**（pi 只在启动时扫描 skill 目录）。**时机**：实现合并前、worktree 内验证。**步骤**：在新会话中执行该 skill，随后在同一 PATH 环境执行 `jfox show <id> --json` | `agent == "pi-coding-agent"` 且 `session_file` 等于 `$PI_SESSION_FILE`，`agent_model` 为 `$PI_PROVIDER/$PI_MODEL` |
| U2 | 真实 auto-summary 扫描 | 用户实测 | **前置**：本机 `~/.zk_config.json` 已物化 `session_sources: ["claude","kimi"]`，先备份再把 `pi` 加入该列表（`auto-summary enable` 当前没有 `--sources` 选项，只能直接改 JSON）；用 worktree 代码运行。**步骤**：`jfox auto-summary status --format json` 检查 `config.session_sources` 含 pi → `jfox auto-summary run --dry-run` → 真实 run | 该会话出现在待处理列表并被总结；cwd 含 `jfox-auto-summary-runs` 的内部会话不被列出 |

## 9. 边界、降级与风险

| 场景 | 行为 |
|---|---|
| 会话文件已被删除 / 移动 | `session_file` 照写（历史指针），不校验存在性；笔记仍可读 |
| ephemeral 会话（`--no-session`） | 没有文件，不进入扫描；`PI_SESSION_FILE` 未设置时手工路径也拿不到路径 |
| fork / 多分支会话 | 只取活跃分支；`parentId` 断链时回退文件顺序并留 debug 日志 |
| 写在 pi settings 的自定义 `sessionDir` | 无环境变量可读，自动发现覆盖不到；需用户配置 `pi_session_dirs` |
| agent-board root 被 `AGENT_BOARD_ROOT` 改写 | 默认解析尊重该变量；显式 `pi_session_dirs` 优先级最高 |
| 同一 session id 多份文件 | 取 mtime 最新，其余跳过 |
| auto-summary 自身产生的 pi 会话 | 由 cwd blocklist 拦截（与 #297 / #303 同款防线） |
| 未来新 agent | `--agent` 不收窄枚举，直接存字符串 |
| 已有配置文件 | `session_sources` 的显式列表优先于新默认值（N5），用户需手动加入 `pi` |

## 10. 影响文件

- `jfox/models.py` — Note 三字段与四处序列化
- `jfox/cli.py` — `add` / `_add_note_impl` 参数与校验
- `jfox/note.py` — `create_note` 签名
- `jfox/global_config.py` — `session_sources` 默认值、`pi_session_dirs` 解析
- `jfox/auto_summary/scanner.py` — `SessionFile.agent` / `agent_model`
- `jfox/auto_summary/sources.py` — pi 分支、根目录解析、`extract_dialog_for`
- `jfox/auto_summary/pi_source.py`（新增）— `PiCodeSource` + 扫描
- `jfox/auto_summary/pi_extractor.py`（新增）— 条目解析纯函数
- `jfox/auto_summary/extractor.py` — `ExtractedDialog.agent_model`、claude 模型提取
- `jfox/auto_summary/kimi_source.py` — kimi 模型提取
- `jfox/auto_summary/runner.py` — 三字段透传、prompt 措辞、topic 兜底
- 测试：`tests/unit/test_note_agent_fields.py`、`test_add_agent_fields.py`、`test_pi_extractor.py`、`test_pi_source.py`、`test_session_summary_skill_docs.py`（均新增）+ 既有 config/source/runner 测试扩充；`tests/integration/test_auto_summary_pi.py`（新增）
- skills：4 个平台的 `jfox-session-summary` SKILL.md；`jfox add` 参数清单共 4 处——`skills-recommend/pi/jfox-common`、`skills-recommend/kimi-cli/jfox-common`、`packages/cc-plugin/skills/manage/SKILL.md` §4.2、`packages/kimi-plugin/skills/jfox-manage/SKILL.md` §4.2
- 文档：`README.md`、`docs/cli-reference.md`、`docs/json-schemas.md`（`add` 与 `show` 两行）、`docs/cli-descriptions.yaml`（auto-summary 描述写的是 "Claude Code sessions"）、`CLAUDE.md:86`（auto_summary 范围仍写为只扫 `~/.claude/projects/`，随本 PR 更新）
