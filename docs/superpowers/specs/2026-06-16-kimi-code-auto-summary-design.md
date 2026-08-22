# Design: auto-summary 支持 Kimi Code session + 总结笔记增强

- **Issue**: [#242](https://github.com/zhuxixi/jfox/issues/242)
- **日期**: 2026-06-16
- **状态**: Draft（待 review）

## 背景与动机

JFox Auto Summary 当前**只扫描 Claude Code 的会话**。用户同时使用 Claude Code 和 Kimi Code（月之暗面的 CLI）工作，Kimi Code 产生的会话完全无法进入知识库。本设计让 auto-summary 支持多来源扫描，同时顺带改进生成的总结笔记质量（当前三段式过于简陋）。

## 目标（Goals）

1. auto-summary 能扫描并提取 Kimi Code 的 session，与 Claude Code 来源共存、互不干扰。
2. 引入 `SessionSource` 抽象，使未来接入其它 CLI 来源（Gemini CLI、Cursor 等）成本可控。
3. 增强总结笔记的输出结构，使其具备「上下文感」（接近 Claude Code `/compact`），对 Claude 和 Kimi 来源同时生效。

## 非目标（Non-Goals）

- **不抽象总结生成器**：总结继续复用现有 `claude -p` 管线。纯 Kimi 环境（未安装 claude）仍无法生成总结——该问题另开 issue。
- **不扫描旧版 `~/.kimi/sessions/`**：本机已有 `.migrated-to-kimi-code` 标记，说明已迁移到 `~/.kimi-code/`；旧目录视为迁移残留，默认不扫。
- **不做来源注册表 / 配置驱动的目录-解析器映射**：目前仅两个来源，YAGNI。
- **不改 daemon 循环、CLI 子命令的主干**：`loop.py`/`cli.py` 仅透传新配置，不改交互。

## 现状分析

### auto-summary 现有管线（Claude 专用）

- **扫描**：`scanner.iter_session_files()` 硬编码 `~/.claude/projects/<proj>/<uuid>.jsonl`，按 mtime/size 过滤。
- **提取**：`extractor.extract_dialog()` 只认 Claude 字段（`type:"user"/"assistant"`、`message.{role,content}`、ISO `timestamp`、`cwd`、`gitBranch`）。
- **总结**：`runner._invoke_claude()` 调 `claude -p --output-format json`，按 `SYSTEM_PROMPT` 产出结构化 JSON（title/topic/summary_md/tags）。
- **入库**：`_save_session_note()` 写 session 类型笔记；`ledger` 以裸 `session_id`（UUID）为去重 key。
- **配置**：`AutoSummaryConfig`（`global_config.py`）显式枚举每个字段，`from_dict`/`to_dict` 需同步维护；无任何「来源」概念。

### Kimi Code session 格式（已实测验证）

**目录结构**

```
~/.kimi-code/sessions/
└── wd_<slug>_<hash>/            # slug=basename(cwd), hash=sha256(cwd)[:12]
    └── session_<uuid>/
        ├── state.json           # 会话元数据（ISO 时间戳、标题）
        └── agents/main/wire.jsonl   # 对话记录（wire 协议）
```

**wire.jsonl 事件类型**（实测 539 行会话）：

| type | 用途 |
|------|------|
| `context.append_message` | **对话消息**（`message.{role, content:[{type:text,text}]}`） |
| `turn.prompt` | **用户输入**（`input:[{type:text,text}]`） |
| `context.append_loop_event` | 工具/循环事件；**首个携带完整 `cwd`** |
| `metadata` | `created_at`(毫秒)、`app_version`、`protocol_version` |
| `usage.record` / `permission.*` / `tools.*` / `plan_mode.*` / `config.update` | 噪音，跳过 |

**state.json**：`createdAt`、`updatedAt`（ISO 字符串）、`title`、`lastPrompt`。

**关键差异（vs Claude）**

| 维度 | Claude Code | Kimi Code |
|------|-------------|-----------|
| 路径 | `~/.claude/projects/<proj>/<uuid>.jsonl` | `~/.kimi-code/sessions/wd_*/session_*/agents/main/wire.jsonl` |
| 消息行 type | `user`/`assistant` | `context.append_message`/`turn.prompt` |
| content | 文本或数组 | 始终 `[{type:text,text}]` 数组 |
| 时间戳 | ISO `timestamp` | state.json 的 ISO + 行内 `time`(毫秒) |
| cwd | 有字段 | loop_event 内有完整路径；目录名 hash 单向不可反推 |

> 已验证 `wd_<slug>_<hash>` 的 hash = `sha256(完整工作目录路径)[:12]`，slug = basename。但 SHA256 单向，**不能从 hash 反推路径**；故 cwd 一律从 wire.jsonl 的 loop_event 字段取，不依赖目录名。

## 设计

### 1. 架构与模块布局

沿用 auto_summary 现有扁平结构（不拆子包）。来源相关代码集中到两个新文件，Claude 侧仅「封装搬家、不改逻辑」以降低回归风险：

```
jfox/auto_summary/
├── sources.py        【新】SessionSource Protocol + get_sources(cfg) 工厂 + SessionFile
├── kimi_source.py    【新】KimiCodeSource：扫描 + wire.jsonl 解析
├── scanner.py        ClaudeCodeSource（封装现有 iter_session_files）
├── extractor.py      Claude extract_dialog（现有，逻辑不动）
├── runner.py         scan_pending/summarize_one 改为面向 source；SYSTEM_PROMPT 增强
├── ledger.py         key 加来源前缀 + 旧数据迁移
└── global_config.py  AutoSummaryConfig 加 session_sources / kimi_sessions_dir
```

### 2. SessionSource 协议 + 工厂

```python
# sources.py
class SessionSource(Protocol):
    name: str  # "claude" / "kimi"
    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]: ...
    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog: ...
```

- `SessionFile` 新增字段 `source: str`（来源名）。
- `get_sources(cfg)`：按 `cfg.session_sources` 取对应 source 类实例；**auto-detect 目录存在**——claude 要求 `~/.claude/projects` 存在，kimi 要求 `cfg.kimi_sessions_dir`（默认 `~/.kimi-code/sessions`）存在；不存在则跳过并 `log info`。
- 统一去重键：`key(sf) = f"{sf.source}:{sf.session_id}"`。
- `ClaudeCodeSource`：`iter_sessions` 委托现有 `scanner.iter_session_files`，`extract_dialog` 委托现有 `extractor.extract_dialog`，`name="claude"`。

### 3. 配置变更（`AutoSummaryConfig`）

```python
session_sources: list[str] = field(default_factory=lambda: ["claude", "kimi"])  # 默认都开
kimi_sessions_dir: Optional[str] = None  # None → ~/.kimi-code/sessions
```

- `from_dict`/`to_dict` 同步新增这两个字段。
- 旧配置文件无 `session_sources` → `from_dict` 用默认 `["claude","kimi"]`（向后兼容 + 符合「默认都开」决策）。
- `update_auto_summary_config` 现为 dict merge，天然兼容新字段。

### 4. 数据流

```
run_once
 └─ scan_pending
     └─ for source in get_sources(cfg):                 # 多源合并
          for sf in source.iter_sessions(cfg):
            if not ledger.is_done(key(sf)): pending.append(sf)
 └─ for sf in pending[:cfg.max_per_tick]:
     summarize_one(sf)
       ├─ source = get_source_by_name(sf.source)
       ├─ extracted = source.extract_dialog(sf)          # 按来源分发
       ├─ if extracted 无用户内容 → ledger.record_skip(key(sf))
       ├─ _invoke_claude(...)                             # 复用，不变
       └─ _save_session_note + ledger.record_success(key(sf))
```

### 5. KimiCodeSource 解析细节

**扫描**：`<kimi_dir>/wd_*/session_*/agents/main/wire.jsonl`，按 mtime/idle/size 初筛（参数沿用 cfg，size 作用于原始 wire.jsonl）。

**extract_dialog(wire.jsonl path)**：

1. **元数据（state.json）**：wire.jsonl 上三级目录即 `session_<uuid>/`（`path.parent.parent.parent`；结构为 `session_<uuid>/{state.json, agents/main/wire.jsonl}`），读其 `state.json`：
   - `started_at = createdAt`、`ended_at = updatedAt`（ISO，直接用）。
2. **wire.jsonl 逐行**：
   - `context.append_message` → 取 `message.role` + `message.content`（数组内 `type:text` 的 `text` 拼接）→ 对话主体。
   - `turn.prompt` → `input` 数组文本作为用户输入补充。
   - `context.append_loop_event` → 仅从**首个**取 `cwd`（完整路径），其余跳过。
   - 其余 type（`usage.record`/`permission.*`/`tools.*`/`plan_mode.*`/`config.update`）→ 跳过。
3. **session_id** = `session_<uuid>` 中的 uuid。
4. **轮次计数**：user/assistant 计数同 Claude 语义。

### 6. ledger 去重 key 迁移

- 新 key 格式：`{source}:{session_id}`。
- `Ledger._load` 时：旧条目（key 不含 `:`）视为 `claude:{key}` 补全——一次性、幂等（再次加载不会重复加前缀）。
- 彻底消除 Claude/Kimi UUID 理论碰撞 + 便于溯源。
- `LedgerEntry.project` 字段语义不变（记 `project_dir_name`）。

### 7. 总结笔记输出增强（中等 compact 感）

修改 `runner.SYSTEM_PROMPT` 中对 `summary_md` 的结构约束，由三段改为五段，要点允许适度展开（1-2 句技术细节）：

```
## 背景
<会话目标 / 起点状态>

## 做了什么
- <要点> + 1-2 句技术细节
- <要点> + 涉及的文件/命令

## 关键决策
- <决策> + 理由

## 技术细节
- 关键文件 / 代码片段 / 配置

## 未决事项
- <待办，没有则「无」>
```

- 保留 `title`/`topic`/`tags`/`skip` 字段不变。
- `_compose_note_body` 不改（仅拼接 summary_md + 元数据 footer）。
- **对 Claude 和 Kimi 来源同时生效**（共享总结器）。
- 权衡：`claude -p` 输出变长。中等档增量可控，默认 `claude_timeout_seconds=120` 预计仍够；若实际触发超时，调大该配置即可（不改默认值）。

### 8. 错误处理

- wire.jsonl 单行 JSON 解析失败：跳过该行继续。
- state.json 缺失/损坏：降级——`started_at`/`ended_at` 从 wire.jsonl 首尾行 `time`（毫秒→ISO）推导。
- cwd 取不到（无 loop_event）：`cwd=None`，笔记元数据省略该行（不致命）。
- `kimi_sessions_dir` 不存在：`get_sources` 跳过 kimi 来源。
- Kimi 升级导致 wire 协议漂移（出现未知 type）：容忍跳过；关键字段缺失致无用户内容 → `record_skip`。

## 测试策略

### 快速单测（可自主运行，无 embedding/ChromaDB）

- `tests/unit/test_kimi_extractor.py`：用脱敏的 wire.jsonl + state.json fixture，断言对话提取、cwd、started_at/ended_at、轮次计数、噪音过滤。
- `tests/unit/test_session_source.py`：
  - `get_sources` auto-detect（mock 目录存在/不存在）。
  - 多源 `iter_sessions` 合并去重。
  - ledger key 前缀化 + 旧裸 UUID 数据迁移幂等。
- `tests/unit/test_kimi_scanner.py`：`KimiCodeSource.iter_sessions` 的 mtime/idle/size 过滤（mock 文件树）。

### 集成测试（交用户运行）

- `tests/integration/test_auto_summary_kimi.py`：真实样例 session 跑 `scan_pending`（mock `_invoke_claude`），验证 Kimi session 进入 pending 且 key 为 `kimi:<uuid>`。

## 验收标准

- [ ] 配置启用 kimi 来源后，auto-summary 能扫到 `~/.kimi-code/sessions/**/agents/main/wire.jsonl`。
- [ ] 正确提取 `context.append_message`/`turn.prompt`，过滤工具/用量噪音。
- [ ] 生成笔记带正确时间戳（state.json ISO）与 cwd（loop_event 完整路径）。
- [ ] Claude 和 Kimi 来源可同时启用、互不干扰；ledger key 带前缀、旧数据自动迁移。
- [ ] `--dry-run` 列出各来源发现的 session 数。
- [ ] 总结笔记输出为五段结构（背景/做了什么/关键决策/技术细节/未决事项），对两类来源生效。

## 风险与权衡

| 风险 | 缓解 |
|------|------|
| Kimi wire 协议随版本变化 | extractor 对未知 type 容忍；关键字段缺失走 skip 分支 |
| Claude 侧封装搬家引入回归 | Claude 逻辑零改动，仅包一层；补 scanner/extractor 现有测试确认不破 |
| 五段结构增加 token 成本 | 中等档增量可控；超时靠 `claude_timeout_seconds` 调，不改默认 |
| 多源合并后单轮处理量上升 | 受 `cfg.max_per_tick` 约束，不变 |

## 参考

- Issue #242: <https://github.com/zhuxixi/jfox/issues/242>
- 相关代码：`jfox/auto_summary/{scanner,extractor,runner,ledger}.py`、`jfox/global_config.py`
- Kimi session 实测路径：`~/.kimi-code/sessions/wd_*/session_*/agents/main/wire.jsonl`
