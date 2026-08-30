# Spec：gem-synth 重构——prompt 记录与按需判断（issue #399）

日期：2026-08-30
版本：revision 6
状态：draft，待用户审阅
关联：<https://github.com/zhuxixi/jfox/issues/399>
相关 issue：#462（pi-coding-agent 侧 prompt 采集，独立处理）

## 1. 目标与边界

现有 gem-synth 的自动合成链路已经被真实使用证伪：它从少数锚点事件自动生成 candidate，产出的内容大多是对会话的重新整理，而不是值得沉淀的知识；同时，旧 dedup 会把反复澄清当作冗余丢弃。

本次重构把流程改为：

1. **记录**：Claude Code 侧全量记录每一条 `UserPromptSubmit`，保存完整 prompt，不做关键词分类、不做截断、不调用 LLM。
2. **取证**：用户需要沉淀知识时手动运行 `jfox prompts judge`，jfox 读取 transcript、永久笔记、历史 prompt 和 unresolved 条目。
3. **判断与起草**：jfox 调用可配置的外部 agent（默认 pi + 可配置模型，示例为 DeepSeek），批量分类并为 `new` 项起草 candidate。
4. **人工处理**：用户使用逐条 CLI 命令决定 promote、加入 unresolved 清单或 ignore。

本 spec 只覆盖 Claude Code 侧的记录。pi-coding-agent 侧记录单独由 #462 处理。判断不会在 hook 或 daemon 中自动运行。

### 1.1 不可违反的边界

- agent 只负责分类、给出证据和起草；不能自动晋升、自动拒绝或自动合并 candidate。
- `confidence`、prompt 相似度和任何阈值只能作为报告信息，不能替代用户决策。
- prompt 原文是 append-only 记录；合法的重复提问必须保留，不能按正文 hash 删除。
- 记录层不依赖 embedding 模型和外部 LLM；daemon 或模型故障不能使已经写入本地 spool 的 prompt 丢失。

“零信息损失”指应用层保证：只要本地 spool 原子写入成功，prompt 原文不会因网络、daemon、LLM 或判断失败而丢失。磁盘损坏、权限拒绝和磁盘耗尽属于不可消除的硬故障，必须报告，不能伪装成功。

## 2. 已确认决策与工程契约

D1-D10 是用户已经确认的产品决策；D11-D18 是本轮 review 固化的工程契约。

| 编号 | 决策点 | 结论 |
|---|---|---|
| D1 | 判断层执行主体 | jfox 负责编排、校验、落盘和 CLI；判断调用可配置外部 agent。jfox 不变成通用 agent |
| D2 | 模型接入 | 默认可启动 pi 并指定模型，模型/provider 可配置；不把 jfox 绑死在 `claude -p` 或 DeepSeek |
| D3 | 旧流程退役 | 新流程上线后停止旧的自动合成运行路径，一刀切，不保留 daemon 自动合成 |
| D4 | unresolved 产物 | 每个 KB 使用一条带 `unresolved-problems` 标签的 permanent 聚合笔记；同库辅助表只做幂等索引 |
| D5 | 存量 candidate | 约 240 条存量 candidate 继续按 jfox-promote 三模式处理，不自动重判或清理 |
| D6 | 判断触发 | 用户手动运行 `jfox prompts judge`，在需要沉淀知识时触发；hook 和 daemon 不运行判断 |
| D7 | 记录存储 | 复用 `fragments.db`，新增 `user_prompts`、`prompt_judgments`、`unresolved_items` |
| D8 | judge 交互 | 批量报告 + 逐条命令，不做 TUI |
| D9 | 新知识落盘 | `new` 先落 `candidate`，人工审阅后再 promote |
| D10 | unresolved 写入 | judge 只报告；用户显式运行 unresolved 命令确认后才写入 |
| D11 | 旧 fragment 采集 | 停止新增 correction/decision/tool_call/session_summary；hook 只采集 UserPromptSubmit，历史行保留 |
| D12 | 可靠记录 | hook 先原子写本地 spool，再尽力 POST daemon；失败保留 spool |
| D13 | 判断作用域 | prompt record 全局共享；judgment 和 unresolved 按 `(kb_name, prompt_id)` 隔离 |
| D14 | 候选去重 | 新流程不做自动 dedup、merge、confidence 过滤或自动 reject |
| D15 | 不确定性 | `needs_review` 是合法成功分类；证据不足或非知识 prompt 不强行归类、不生成 candidate |
| D16 | runner 安全 | 默认 pi runner 关闭工具、session、extensions、skills、项目上下文和 approval；prompt 只走 stdin |
| D17 | 幂等恢复 | judge、candidate 创建、unresolved 写入和重试都可恢复，不产生第二个 candidate 或重复条目 |
| D18 | 人工覆盖 | 默认动作前置条件严格校验；用户可显式 `--force --reason` 覆盖分类建议，覆盖必须留痕 |

## 3. 当前基线与证据

当前链路为：

```text
CC hook（UserPromptSubmit/PostToolUse/Stop）
  → /api/fragment
  → detector 关键词分类
  → session_fragments（fragments.db）
  → daemon 每 30 分钟取 correction/decision/AskUserQuestion 锚点
  → transcript 单轮反查
  → permanent grounding
  → claude -p 合成
  → dedup
  → candidate
```

当前实现中有几个直接影响新设计的事实：

- `UserPromptSubmit` 的完整原始事件在 `session_fragments.metadata_json` 中保存，包含完整 `prompt`；但 `content` 被统一截断到 500 字符。历史回填必须读 `metadata_json.prompt`，不能读 `content`。
- 当前 hook 使用 `curl -m 1 || true`，daemon 不可用时会丢 prompt；新方案必须先写 spool。
- 当前 `transcript.py` 已有 `extract_turn_around`，但只支持单轮文本匹配；新流程需要安全的 full/targeted/prompt-only 三种上下文模式。
- 当前 `llm.py` 直接绑定 `claude -p`；新流程保留超时、进程组清理和 JSON 容错思想，但改为可配置 runner。
- 当前 candidate CLI 位于 `gem_synth/cli.py`；新流程需要把 candidate 公共能力与自动合成运行路径分离。
- 当前存量 candidate 过审由 jfox-promote skill 完成；该人工流程不随新判断层废弃。

## 4. 总体架构

```text
Claude Code UserPromptSubmit
  │
  ├─ 原始 event → 本地 prompt-spool/<capture_id>.json（先写、可恢复）
  │
  └─ 尝试 POST /api/prompt
                    │
                    ▼
         fragments.db.user_prompts
                    │
          jfox prompts drain
                    │
          jfox prompts judge（手动）
                    │
       按 session 读取 transcript 与证据
                    │
       可配置外部 runner（默认 pi + 配置模型）
                    │
       prompt_judgments + new 类 candidate
                    │
       批量报告，不执行用户 disposition
                    │
       用户逐条执行：
         prompts promote
         prompts unresolved
         prompts ignore
```

### 4.1 代码边界

新增 `jfox/prompts/`，不再把新流程塞回自动合成模块：

| 路径 | 职责 |
|---|---|
| `jfox/prompts/store.py` | 新表、spool drain、历史回填、claim、状态机和对账 |
| `jfox/prompts/judge.py` | prompt 选择、session 分组、证据组装、结果落盘 |
| `jfox/prompts/runner.py` | 外部 agent argv、超时、进程组和输出限制 |
| `jfox/prompts/transcript.py` | transcript 解析、occurrence 定位和上下文预算 |
| `jfox/prompts/grounding.py` | permanent evidence 与 unresolved evidence |
| `jfox/prompts/lifecycle.py` | candidate 直接 promote/reject 后同步 judgment |
| `jfox/prompts/cli.py` | `jfox prompts` 命令组 |
| `jfox/candidates/service.py` | 从旧 gem_synth 提取 candidate 公共落盘/查询适配 |
| `jfox/candidates/cli.py` | 保持现有 `jfox candidates` 命令和参数 |

`jfox/fragment/store.py` 继续提供历史 `session_fragments` 只读/兼容访问；新表与旧表共用同一个 SQLite 文件，但新语义只由 `jfox/prompts/store.py` 负责。

## 5. 记录层

### 5.1 `user_prompts` 表

```sql
CREATE TABLE IF NOT EXISTS user_prompts (
    prompt_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key            TEXT NOT NULL UNIQUE,
    capture_id            TEXT UNIQUE,
    source                TEXT NOT NULL DEFAULT 'claude-code',
    source_fragment_id    INTEGER UNIQUE,
    source_message_uuid   TEXT,
    session_id            TEXT NOT NULL,
    session_seq           INTEGER NOT NULL,
    captured_at           TEXT NOT NULL,
    prompt                TEXT NOT NULL,
    prompt_hash           TEXT NOT NULL,
    transcript_path       TEXT,
    transcript_user_index INTEGER,
    session_title         TEXT,
    cwd                   TEXT,
    metadata_json         TEXT,
    UNIQUE(source, session_id, session_seq)
);
CREATE INDEX IF NOT EXISTS idx_prompts_session
    ON user_prompts(source, session_id, captured_at, prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompts_hash
    ON user_prompts(prompt_hash, captured_at);
CREATE INDEX IF NOT EXISTS idx_prompts_source_fragment
    ON user_prompts(source_fragment_id);
CREATE INDEX IF NOT EXISTS idx_prompts_transcript
    ON user_prompts(transcript_path, transcript_user_index);
```

当 `transcript_path` 和 `transcript_user_index` 都可靠存在时，额外建立唯一 occurrence 索引：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_prompts_transcript_occurrence
    ON user_prompts(transcript_path, transcript_user_index)
    WHERE transcript_path IS NOT NULL AND transcript_user_index IS NOT NULL;
```

字段和幂等规则：

- `source_key` 是来源级幂等键：实时 spool 使用 `capture:<uuid>`，历史碎片使用 `fragment:<fragment_id>`，transcript 扫描使用 `transcript:<canonical-path>#<message-uuid-or-index>`。
- `capture_id` 在同一个 hook 调用、spool 文件、HTTP 重试和 SQLite 导入之间保持不变。按 `source_key` 先查再插入，重复提交返回已有 `prompt_id`。
- `source_fragment_id` 只表示旧 `session_fragments` 行号，绝不能当作新的 `prompt_id`。合法重复提问不因 `prompt_hash` 相同而合并。
- `session_seq` 是同一 source/session 下的稳定摄入序号，由 SQLite `BEGIN IMMEDIATE` 事务分配；它不是 transcript 消息位置。transcript 定位优先使用 `transcript_user_index`。
- `captured_at` 优先使用可验证的事件时间，否则使用 UTC ISO-8601 摄入时间。展示排序使用 `captured_at`、`session_seq`、`prompt_id` 的组合。
- `prompt_hash` 对 Unicode NFKC、首尾空白和连续空白规整后的文本计算 SHA-256，只用于历史证据查询，不用于删除、合并或拒绝。
- `metadata_json` 默认保存完整原始 event，报告和外部 runner 不发送它。关闭 `retain_raw_event` 时仍保存完整 `prompt` 及索引字段。
- occurrence 唯一键冲突时，若 source/session/prompt 能证明是同一 transcript 消息，复用已有行并补齐缺失字段；无法证明时报告冲突，不自动覆盖或删除任一行。
- transcript path 只有在允许的 Claude transcript 根目录内、且没有通过符号链接逃逸时才允许读取；不安全 path 仍可记录，但判断只能使用 prompt-only context。

### 5.2 本地 spool

当前 hook 的 `curl -m 1 || true` 是 best-effort，无法满足记录层要求。本版固定采用“先 spool、后 HTTP”：

1. hook 只接受 `UserPromptSubmit`，校验非空字符串 `session_id` 和 `prompt`。
2. 为该调用生成 UUID `capture_id`，把完整 payload 写入 `prompt-spool/<capture_id>.json.tmp`。
3. 文件 flush + fsync 后原子 rename 为 `.json`；目录和文件使用用户私有权限，文件名只接受 UUID。
4. spool 成功后尝试 POST `/api/prompt`。只有收到 `stored` 或 `duplicate` 确认才删除 spool 文件。
5. daemon 超时、HTTP 错误、数据库锁、daemon 未运行或 API 返回 5xx 时保留 spool，`jfox prompts drain` 可再次导入。
6. spool 写失败、payload 超过上限或 spool 总量超过上限时不截断、不把 prompt 写入日志、不伪造成功；尽力写只含 capture ID 和错误原因的诊断 sidecar，`jfox prompts status` 报告失败。

默认路径为 `~/.zettelkasten/prompt-spool/`，可用 `JFOX_PROMPT_SPOOL_DIR` 覆盖。默认单请求上限 16 MiB、spool 总量上限 1 GiB；超过上限拒绝整条数据，不保存半截内容。

### 5.3 daemon API

新增 `POST /api/prompt`，请求为 Claude Code 原始 event 加 `jfox_capture_id`。服务端必须：

- 校验对象 JSON、`hook_event_name=UserPromptSubmit`、非空 `session_id`、字符串 `prompt` 和合法 capture ID；
- 保存完整 prompt，不使用 `FragmentCaptureConfig.max_content_chars`；
- 对同一 capture 返回 `{status: "duplicate", prompt_id}`，不重复插入；新写入返回 `{status: "stored", prompt_id}`；
- 对非法请求和超限请求返回结构化 4xx，不保存半截数据；
- 用 SQLite busy timeout 和事务分配 `session_seq`，不静默覆盖并发写入；
- daemon 启动时先初始化 PromptStore/FragmentStore，再加载 embedding 模型。embedding 加载失败时，prompt API 和 `jfox prompts drain` 仍可用，embedding endpoint 单独返回 degraded/503；
- 只监听本机默认地址，保持现有 daemon 的本地服务边界。

旧 `POST /api/fragment` 仅保留兼容窗口：

- 旧插件的 `UserPromptSubmit` 转发到新 prompt 记录路径，并标记 `source=legacy-cc`；
- `PostToolUse`、`Stop` 返回 retired/410，不再写新 `session_fragments`；
- `GET /api/fragments` 和 `jfox fragments list/show` 保留为历史只读入口。

### 5.4 CC plugin

`packages/cc-plugin/hooks/hooks.json` 只保留 `UserPromptSubmit`。`fragment-capture.sh` 删除 PostToolUse/Stop 分支、Stop 摘要输出和关键词分类，改为 spool + `/api/prompt`。

`JFOX_INTERNAL_SESSION` 继续过滤 `auto-summary`、`gem-synth`，并新增 `prompt-judge`。runner 启动外部 agent 时设置 `JFOX_INTERNAL_SESSION=prompt-judge`，防止判断 agent 自己触发 Claude Code hook 后形成反馈循环。

### 5.5 历史回填

新增 `jfox prompts backfill`：

- 只读取旧 `session_fragments` 中 `source_event='UserPromptSubmit'` 的行，不论旧 `fragment_type` 是 correction、decision 还是 user_input；
- 从 `metadata_json.prompt` 读取完整 prompt，不使用旧 `content`；
- 保存旧 session、时间、transcript path、session title、cwd，并填入 `source_fragment_id`；
- 使用 `source_key=fragment:<fragment_id>`，重复运行不会重复插入；
- `--dry-run` 报告可回填、空 prompt、非法 metadata、缺 transcript 和不安全 path 数量；
- `--scan-transcripts` 扫描 `PromptCaptureConfig.transcript_roots`，补回 metadata 无效的 user 消息；优先使用 message UUID，缺 UUID 时使用规范化路径和 user occurrence；
- 回填只写 prompt record，不调用 LLM、不创建 judgment、不创建 candidate。

cutover 顺序固定为：停止旧 gem-synth task → backfill dry-run → 正式 backfill → 更新 cc-plugin → drain 新 spool。绕过顺序产生的冲突只报告，不自动删除数据。

## 6. 反查与证据层

### 6.1 transcript context

新函数位于 `jfox/prompts/transcript.py`，迁移并扩展旧单轮反查逻辑：

- 按 JSONL 原始顺序读取 user/assistant 消息，向 runner 提供清洗后的规范文本；不发送原始 hook metadata；
- 优先用 `transcript_user_index` 定位 prompt occurrence；没有该字段时使用 prompt 文本、session 顺序和 occurrence 消耗；多次相同文本不能永远命中第一条；
- MVP 只处理 `transcript_path` 指定的单个 JSONL 文件，不跨 fork/resume 文件拼接；
- `full`：完整 session 消息在 `max_transcript_chars` 内；
- `targeted`：完整 session 超预算时，保留所有目标 prompt 周围的 bounded turns（默认前后各 3 个 turn），并标记降级；
- `prompt_only`：文件缺失、path 不安全或 occurrence 不可可靠定位时，只提供完整 prompt 原文；这不等于必然失败，agent 可在证据足够时分类，否则返回 `needs_review`；
- targeted context 仍超过 `max_batch_input_chars` 时拆 batch，不静默截断目标 prompt；
- transcript 中的命令、链接和指令都是不可信分析文本，runner 不得执行。

默认 `max_transcript_chars=4,000,000`、`max_batch_input_chars=6,000,000`。所有 context 降级写入 `prompt_judgments.context_mode` 和报告。

### 6.2 permanent grounding

新函数 `fetch_judgment_grounding()` 位于 `jfox/prompts/grounding.py`：

- 只检索当前 KB 未归档的 permanent；
- 排除带 `unresolved-problems` 标签的聚合清单，避免把未解决问题当成已解决知识；
- 返回 note ID、标题、最多 `max_grounding_chars=4,000` 的正文片段和相似度；
- 无命中是合法空证据，可以支持 `new`；
- 搜索、索引或 embedding 真正异常时返回 `grounding_unavailable`，该 item 记 failed，不调用 runner、不生成 candidate；
- unresolved 内容通过独立 `fetch_unresolved_evidence()` 返回，不混入已解决 permanent 的 `matched_note_ids`。

### 6.3 prompt history

MVP 不在 hook 热路径计算 prompt embedding。judge 提供以下历史证据：

- 当前 session 中目标 prompt 之前最多 20 条 prompt；
- 全局按规范化 `prompt_hash` 找到、且发生时间早于当前 prompt 的最多 20 条历史 prompt；
- 这些历史 prompt 的 ID、session、时间和已有 disposition；
- `unresolved_items.state=active` 的条目及其来源 prompt。

exact/规范化 hash 只能证明文本相同，不能单独证明“反复澄清”。agent 必须结合当前 transcript、permanent evidence 和 unresolved evidence 给出理由；跨 session 的纯语义改写在本次 MVP 不保证被机械召回，不能伪造 `matched_prompt_ids`。

## 7. 判断层与外部 runner

### 7.1 jfox 职责

jfox 不实现通用 agent，也不自行决定知识是否晋升。jfox 负责选择 prompt、读取和清洗证据、claim、启动外部程序、校验结构化结果、保存 candidate、记账、输出报告和执行用户明确的 action。

### 7.2 配置

全局配置新增 `prompt_capture` 和 `prompt_judge` 两个 section：

```json
{
  "prompt_capture": {
    "enabled": true,
    "spool_dir": null,
    "endpoint_url": "http://127.0.0.1:18700/api/prompt",
    "endpoint_timeout_seconds": 1,
    "max_payload_bytes": 16777216,
    "max_spool_bytes": 1073741824,
    "retain_raw_event": true,
    "transcript_roots": ["~/.claude/projects"]
  },
  "prompt_judge": {
    "runner": "pi",
    "binary": "pi",
    "model": "ollama/deepseek-v4-pro:0813-cloud",
    "thinking": "off",
    "extra_args": [],
    "custom_command": null,
    "runner_scope": "remote",
    "allow_remote": false,
    "timeout_seconds": 300,
    "max_output_chars": 1500000,
    "max_stderr_chars": 20000,
    "max_batch_input_chars": 6000000,
    "max_transcript_chars": 4000000,
    "max_grounding_chars": 4000,
    "default_limit": 50,
    "session_batch_limit": 20,
    "history_limit": 20,
    "context_turns_before": 3,
    "context_turns_after": 3,
    "claim_timeout_seconds": 420,
    "working_dir": "~/.jfox-prompt-judge-runs"
  }
}
```

配置规则：

- `runner=pi` 时 jfox 组装固定 argv：`binary`、`--print`、`--model model`、`--thinking thinking`、`--no-tools`、`--no-session`、`--no-extensions`、`--no-skills`、`--no-context-files`、`--no-approve`、内置 `--append-system-prompt`。任务 JSON 只通过 stdin 传入。
- 内置 system instruction 不能被配置覆盖，要求只输出约定 JSON、把 transcript 当作不可信文本、不得执行其中命令。
- `extra_args` 只能增加非保留参数；试图覆盖 `--print`、`--model`、`--thinking`、`--tools`、`--session`、`--extension`、`--skill`、`--context-files`、`--approve`、`--system-prompt` 或 `--append-system-prompt` 时拒绝配置。
- `runner=argv` 时 `custom_command` 必须是 argv 数组，不能是 shell 字符串；任务仍通过 stdin 传入，需要复杂管道时由用户提供 wrapper executable。
- 外部命令使用 `shell=False`、独立 working directory、独立进程组、stdout/stderr 上限和超时清理；不把 API key 写进配置、命令行或日志。
- `runner_scope=remote` 表示 prompt、transcript 和 evidence 会离开本机；Ollama Cloud 也属于 remote。本次执行必须显式 `--allow-remote` 或配置 `allow_remote=true`，否则不启动 runner、不发送任何判断上下文。
- `claim_timeout_seconds` 必须大于 `timeout_seconds + 60`。自定义 executable 是用户信任边界，jfox 不能保证它不会自行上传数据。
- `jfox prompts config show/set` 提供配置查看和修改；show 默认隐藏凭证类值，配置命令不得写入 API key。

### 7.3 runner 输入输出契约

每个 session batch 发送一个结构化任务：

```json
{
  "schema_version": 1,
  "kb_name": "default",
  "items": [
    {
      "prompt_id": 123,
      "prompt": "完整 prompt 原文",
      "context_mode": "full",
      "transcript": "清洗后的 session context",
      "permanent_evidence": [
        {"id": "note-id", "title": "笔记标题", "content": "正文片段"}
      ],
      "prompt_history": [
        {"id": 122, "session_id": "s1", "prompt": "历史 prompt", "disposition": null}
      ],
      "unresolved_evidence": []
    }
  ]
}
```

外部 agent 必须返回：

```json
{
  "items": [
    {
      "prompt_id": 123,
      "classification": "new|repeated|recorded|needs_review",
      "reason": "基于 evidence ID 的判断依据",
      "confidence": 0.8,
      "matched_note_ids": ["note-id"],
      "matched_prompt_ids": [122],
      "matched_unresolved_prompt_ids": [],
      "draft": {
        "title": "候选笔记标题",
        "content": "Markdown 正文",
        "knowledge_type": "factual|procedural|preference|constraint",
        "grounded_by": ["永久笔记标题"]
      }
    }
  ]
}
```

校验规则：

- 每个目标 prompt 必须恰好出现一次；未知、重复或缺失 ID 不能按数组位置猜测。
- `new` 必须有非空 title、content、knowledge_type；其他分类不得生成 draft。`needs_review` 即使带 draft 也丢弃，不落 candidate。
- `matched_note_ids` 只能引用本批提供的已解决 permanent evidence；`matched_prompt_ids` 只能引用提供的历史 prompt；`matched_unresolved_prompt_ids` 只能引用 active unresolved evidence。
- `draft.grounded_by` 必须是 evidence 对应的精确永久笔记标题；jfox 校验 ID 到标题的映射后才写入 candidate。
- `confidence` 必须是有限的 `[0, 1]` 数值；缺失、字符串、NaN 或越界使 item failed，不自动填默认值。
- JSON 可容忍少量前后解释文本，但最终必须通过严格 schema 校验。整体解析失败时本 batch 全部 failed，单 item 不合规时只失败该 item。
- `reason`、title、content 分别限制 4,000、200、50,000 字符；超限失败而不是截断。prompt 原文存储不受这些输出上限影响。

### 7.4 分类标准

| 分类 | 判定条件 | 默认结果 |
|---|---|---|
| `new` | 已解决 permanent 没有覆盖该 prompt 的可复用知识，且 prompt 与回复中有事实、规则、决策、约束或可复用方法 | 起草 pending candidate |
| `repeated` | 已有 permanent 或 active unresolved 涉及该主题，但当前 prompt 仍在追问、纠正、澄清，或暴露答案不可用 | 报告列出，用户确认后加入 unresolved |
| `recorded` | 已有 permanent 能够回答当前 prompt，当前输入只是查找、回忆或确认，没有新知识增量 | 用户显式 ignore |
| `needs_review` | 证据不足、证据冲突、纯闲聊/临时操作、prompt-only 信息不足，或 agent 无法给出可辩护分类 | 不生成 candidate，用户 ignore 或 retry |

分类优先级固定为：证据不足/冲突先 `needs_review`；active unresolved 且问题未解决为 `repeated`；已解决 permanent 完整覆盖且没有新信息为 `recorded`；只有同时满足“无覆盖”和“有可复用知识”才为 `new`；其他情况为 `needs_review`。

## 8. 判断记账与人工闭环

### 8.1 `prompt_judgments` 表

```sql
CREATE TABLE IF NOT EXISTS prompt_judgments (
    kb_name                       TEXT NOT NULL,
    prompt_id                     INTEGER NOT NULL,
    judgment_state                TEXT NOT NULL,
    classification                TEXT,
    disposition                   TEXT,
    candidate_note_id             TEXT,
    reason                        TEXT,
    confidence                    REAL,
    matched_note_ids              TEXT,
    matched_prompt_ids            TEXT,
    matched_unresolved_prompt_ids TEXT,
    context_mode                  TEXT,
    runner_id                     TEXT,
    model_id                      TEXT,
    attempt_count                INTEGER NOT NULL DEFAULT 0,
    claim_token                   TEXT,
    claimed_at                    TEXT,
    last_error                    TEXT,
    judged_at                     TEXT,
    handled_at                    TEXT,
    manual_override               INTEGER NOT NULL DEFAULT 0,
    manual_reason                 TEXT,
    PRIMARY KEY (kb_name, prompt_id)
);
CREATE INDEX IF NOT EXISTS idx_prompt_judgments_state
    ON prompt_judgments(kb_name, judgment_state, disposition);
CREATE INDEX IF NOT EXISTS idx_prompt_judgments_candidate
    ON prompt_judgments(kb_name, candidate_note_id);
```

允许值：

- `judgment_state`：`processing`、`succeeded`、`failed`。
- `classification`：`new`、`repeated`、`recorded`、`needs_review`；技术失败时为空。
- `disposition`：成功判断后为 `pending`、`promoted`、`unresolved`、`ignored`、`rejected` 或 `resolved`；技术失败时为空。
- `matched_*_ids` 是 JSON 数组，保留判断证据；不保存完整模型原始输出。
- claim 完成或失败收口后清空 `claim_token`/`claimed_at`。只有超过 runner timeout 加宽限和 claim lease 的 stale processing 才能回收。

状态流转：

```text
无 judgment 行
  → processing
      ├─ runner/grounding/schema 失败 → failed
      └─ 校验成功 → succeeded + pending
          ├─ new      → promoted / rejected
          ├─ repeated → unresolved / ignored
          ├─ recorded → ignored
          └─ needs_review → ignored / retry
failed/needs_review/ignored/rejected
  → processing（仅用户显式 retry，旧 candidate 不得仍 active）
repeated + unresolved
  → resolved（仅 resolve-unresolved）
```

### 8.2 judge 批处理

一次 `jfox prompts judge`：

1. 先执行 spool drain，并报告成功、失败和滞留文件数。
2. 按目标 KB、session 和状态选择 prompt：默认选当前 KB 没有 judgment 行的 prompt；`--retry-failed` 选 failed；`--retry-needs-review` 选 pending 的 needs_review；`--session` 精确限定 session；`--limit` 按 prompt 数量；`--all` 取消总量上限但不取消单 batch 输入上限。
3. 按 source、session、captured_at、session_seq、prompt_id 稳定排序并分组。同一 session 在一次 CLI 调用中只读取一次 transcript；超过 `session_batch_limit=20` 或输入预算时拆 batch，不跨 session 拼接。
4. 用 SQLite 事务 claim 本批 prompt；并发 judge 不得重复处理同一 `(kb_name,prompt_id)`。
5. 查询 permanent grounding、active unresolved evidence 和 prompt history；grounding 正常为空是合法证据，grounding 服务异常直接使 item failed。
6. 检查 remote consent 后调用 runner，校验返回的 prompt ID、分类、证据引用和 draft。
7. `new` item 创建一个 pending candidate；其他分类只写 judgment，不自动写 unresolved 或 ignore。
8. candidate 文件成功后再写 `candidate_note_id` 和 `succeeded + pending` judgment。若中途崩溃，下次先按当前 KB 的 `source_prompts` 查找唯一未归档 candidate；找到一个则补记账，找到多个则 failed 并要求人工处理。
9. 一个 item 失败不阻塞同 batch 其他 item；清除 claim 并记录 `last_error`、`attempt_count`。
10. 输出 table 或 JSON 报告，默认只显示 prompt 预览、ID、分类、理由、context_mode 和 candidate ID；完整 prompt 用 `jfox prompts show` 查看。

### 8.3 candidate 溯源与动作

`Note` 增加跨类型保留的 `source_prompts: List[int]`，同步更新 `to_markdown()`、`from_markdown()`、`to_dict()` 和 `to_show_dict()`；现有 `source_fragments` 语义不变。

新 candidate 至少包含：

- `type=candidate`、`status=pending`、`gem_level=flawed`；
- `source_prompts=[prompt_id]`；
- `grounded_by` 为已验证的永久笔记标题列表；
- `confidence`、`knowledge_type`。

`jfox prompts promote <prompt_id>` 默认只接受当前 KB 下 `classification=new`、`disposition=pending`、唯一未归档 candidate；成功调用现有 `promote_note` 后把 disposition 改为 `promoted`。用户可用 `--force --reason` 覆盖 classification，但 candidate 存在性和未归档校验不可绕过。

`jfox prompts unresolved <prompt_id>` 默认只接受 `classification=repeated`、`disposition=pending`；可用 `--force --reason` 覆盖分类。`jfox prompts ignore` 只改变成功 judgment 的 pending disposition；已有 candidate 时必须显式 `--reject-candidate` 才同时 reject。

candidate 被直接执行 `jfox candidates promote/reject` 时，`jfox/prompts/lifecycle.py` 根据 candidate 的 `source_prompts` 和当前 KB 回写对应 judgment；旧 candidate 没有 source_prompts 时不回写新 judgment。主笔记动作成功而 judgment 回写失败时不回滚，后续 `prompts show/status` 对账修复。

## 9. CLI 契约

新增 `jfox prompts`：

| 命令 | 行为 |
|---|---|
| `jfox prompts list` | 列出当前 KB 的 prompt；支持 `--status unjudged/processing/pending/failed/all`、`--limit`、`--session` |
| `jfox prompts show <prompt_id>` | 查看完整 prompt、session、transcript 状态和当前 KB judgment；`--full` 才显示完整 metadata |
| `jfox prompts status` | 查看 spool、unjudged、processing、failed、pending 和 active unresolved 计数，不调用 LLM |
| `jfox prompts drain` | 幂等导入本地 spool，不调用 LLM |
| `jfox prompts backfill` | 从历史 `session_fragments` 回填；支持 `--dry-run`、`--scan-transcripts` |
| `jfox prompts judge` | 批量判断；支持 `--limit`、`--all`、`--session`、`--retry-failed`、`--retry-needs-review`、`--allow-remote` |
| `jfox prompts promote <prompt_id>` | 将该 prompt 对应的 candidate 晋升为 permanent；分类覆盖需 `--force --reason` |
| `jfox prompts unresolved <prompt_id>` | 用户确认后加入 unresolved 清单；分类覆盖需 `--force --reason` |
| `jfox prompts resolve-unresolved <prompt_id>` | 关闭当前 KB 中已有的 active unresolved 条目 |
| `jfox prompts ignore <prompt_id>` | 将成功 judgment 标记 ignored；有 candidate 时需 `--reject-candidate` |
| `jfox prompts retry <prompt_id>` | 显式重试 failed/needs_review/ignored/rejected judgment；旧 candidate 必须不再 active |
| `jfox prompts config show/set` | 查看或修改 prompt capture/judge 配置，敏感值默认隐藏 |

所有命令支持 `--kb` 和 `--format json`。所有写操作幂等：重复 promote 不产生第二条 permanent，重复 unresolved 不追加副本，重复 drain/backfill 不产生第二条 prompt。

## 10. unresolved permanent 清单

### 10.1 笔记形式

首次执行 `jfox prompts unresolved <prompt_id>` 时，在当前 KB 创建或定位固定 permanent 笔记：

- 标题：`JFox 待解决问题清单`；
- 类型：`permanent`；
- 标签必须包含 `unresolved-problems`；
- 同标题存在多个笔记，或同标题笔记没有该标签时，命令报冲突并停止，不覆盖用户笔记。

这是用户可见的聚合清单，不是“已经解决的知识”。正常 grounding 排除该标签；judge 通过 `unresolved_items` 和专用 evidence 通道读取 active 条目。

### 10.2 `unresolved_items` 表

```sql
CREATE TABLE IF NOT EXISTS unresolved_items (
    kb_name           TEXT NOT NULL,
    prompt_id         INTEGER NOT NULL,
    note_id           TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'active',
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    resolved_at       TEXT,
    resolution_reason TEXT,
    PRIMARY KEY (kb_name, prompt_id)
);
CREATE INDEX IF NOT EXISTS idx_unresolved_active
    ON unresolved_items(kb_name, state, last_seen);
```

每个用户确认的 prompt occurrence 是一个独立条目，本次 MVP 不做跨 prompt 主题聚合。清单用机器 marker 保证幂等：

```markdown
<!-- jfox-unresolved: kb=default prompt=123 state=active -->
- **Prompt #123**（2026-08-30，session `abc`）：安全转义后的短预览
  - 原因：已有知识未解决/答案不可用
  - 相关 permanent：`note-title`
<!-- jfox-unresolved-end -->
```

用户输入只作为转义后的文本，不能生成 wiki-link、HTML 或 Markdown 链接；真正的 wiki-link 只来自已验证的 permanent 标题。完整 prompt 永远保存在 `user_prompts`。

`unresolved` 命令的顺序是：获取 per-KB 文件锁 → 对账 marker 与 `unresolved_items` → 原子更新同一 prompt ID 条目 → 写辅助表 → 更新 judgment disposition。任一步失败都不报告成功。进程崩溃后下次先对账：一边有 marker/active 行而另一边缺失时补齐；两边内容冲突时停止并报告，不自动覆盖。

`resolve-unresolved` 只接受 active 条目，将 marker、辅助表和 judgment 标为 resolved，保留历史 prompt，不删除记录。resolved 条目不再进入 active evidence，也不进入已解决 permanent grounding。

## 11. 旧 gem-synth 退役与迁移

### 11.1 退役运行路径

新流程上线时停止并删除自动合成路径：

- `gem_synth/anchors.py` 和锚点查询；
- `gem_synth/synthesizer.py` 的自动合成、前置 dedup 和增量 merge；
- `gem_synth/loop.py` 及 daemon 中 `_maybe_start_gem_synth()` / `_maybe_stop_gem_synth()`；
- `gem_synth/dedup.py` 的新流程写入路径和旧 dedup lifecycle 注册；
- `fragment/detector.py` 的关键词分类；
- `gem_synth/cli.py` 中旧 `gem-synth status`、`dedup-backfill` 等自动合成进度命令；
- `jfox/__init__.py` 对旧 `gem_synth.lifecycle` 的导入。

candidate 公共 CLI/服务先迁移到 `jfox/candidates/`，保持 `jfox candidates list/show/promote/reject` 的命令、参数和行为不变。旧代码不得继续被 daemon、CLI 或包初始化导入。

### 11.2 历史数据保留

- `fragments.db` 的 `session_fragments` 历史行不删除，`jfox fragments list/show` 作为历史只读入口保留；
- `synthesis_log.db`、`dedup_embeddings` 和旧 candidate 文件不删除，也不被新流程写入；
- 旧 correction/decision/tool_call/session_summary 只作为历史数据，不再是新判断的锚点来源；
- 存量 candidate 继续按 jfox-promote 三模式过审，新 judge 不自动重判、去重或清理。

### 11.3 配置兼容与 cutover

`GlobalConfig.from_dict()` 兼容读取旧 `fragment_capture` 和 `gem_synthesis`：

- 新配置没有 `prompt_capture` 时，从旧 `fragment_capture.enabled` 继承启用状态；
- 旧关键词、`max_content_chars` 和 gem-synthesis 运行字段只读兼容并输出一次 warning，不再驱动新流程；
- 写回配置时保留未知用户字段和历史数据文件，不删除旧 section 对应的数据库；
- 新配置默认开启 prompt capture，judge runner 默认使用 pi 配置，实际模型 ID 必须可修改。

cutover 顺序：

1. 发布新表、spool、drain/backfill、judge 和 candidate 迁移代码；
2. 停止或重启 daemon，确认没有旧 gem-synth task/tick；
3. 运行 `jfox prompts backfill --dry-run`，检查数量和异常，再执行正式 backfill；
4. 更新 cc-plugin，只保留 UserPromptSubmit；
5. 运行 `jfox prompts drain`，确认 spool 归零或剩余文件有明确错误；
6. 首次使用 remote runner 时显式 `jfox prompts judge --limit 50 --allow-remote`；
7. 用户逐条处理 candidate、unresolved 和 ignore。

## 12. 错误处理、恢复与隐私

- spool 写失败：不截断、不在日志输出 prompt、不伪造成功；只报告 capture ID 和错误原因；
- daemon 不可用：已经原子写入的 spool 保留，CLI drain 直接打开 `fragments.db`；
- 数据库锁或磁盘满：不删除 spool，下一次 drain 重试；
- transcript 缺失/path 不安全：prompt-only 并在报告标记，不删除 record；
- grounding 无命中：视为合法空证据；grounding 服务异常：item failed，不调用 runner；
- runner 找不到、超时、非零退出或输出超限：清理整个进程组，记 failed，不阻塞其他 item；
- JSON/schema 错误：不能验证的 item 不落 candidate；未知/重复/缺失 prompt ID 不能按位置猜测；
- candidate 已落盘而 judgment 未写入：下次按 `source_prompts` 对账，找到唯一 candidate 就补记账；多个匹配转人工处理；
- candidate 直接 promote/reject 后同步失败：不回滚主笔记动作，下次 show/status 对账修复；
- unresolved 写入失败：disposition 保持 pending，文件锁、原子写和辅助表对账保证重试不重复；
- remote runner 首次使用必须提示 transcript 可能含代码、路径、个人信息或秘密；未经 consent 不发送 prompt、transcript、grounding 或 unresolved evidence；
- spool、judge working directory 和 fragments.db 使用用户私有权限；API key 不写入代码、配置或日志。

## 13. 测试与验收标准

### 13.1 记录与迁移

- 超过 500 字符的中文、英文、换行、代码和 Unicode prompt 完整 round-trip；数据库正文和 metadata 均无截断；
- daemon 停止或 embedding 加载失败时 hook 仍生成 fsync + 原子 rename 的 spool，随后 drain 恢复；
- 同一 capture 重试、重复 drain、重复 backfill 不产生重复行；合法相同 prompt 多次出现仍保留多行；
- 非 UserPromptSubmit、内部 session、空 session ID、非字符串 prompt、非法 capture ID 和超限 payload 有结构化错误；
- 历史回填使用完整 `metadata_json.prompt`，不使用旧 `content`；dry-run 数量准确；
- occurrence 冲突、session_seq 并发分配、数据库锁和 spool 超限可诊断。

### 13.2 证据与判断

- 同一 session 的多个 prompt 在一次 judge 调用中只读一次 transcript；超出上下文预算时正确拆 batch；
- 相同文本多次出现时 occurrence 不总是第一条，无法定位时标记 prompt-only；
- full、targeted、prompt-only 三种 context_mode 均有测试和报告标记；
- 空 grounding 允许 new，grounding 异常不调用 runner、不生成 candidate；
- session history、规范化 hash history、active unresolved evidence 和 permanent evidence 正确进入输入；
- runner 返回结果按 prompt ID 映射，未知/重复/缺失 ID、伪造 evidence、缺 draft、confidence 越界均不会产生 candidate。

### 13.3 状态、runner 与人工动作

- runner 使用 argv + `shell=False`，prompt 不进入命令行；超时/超限能清理整个进程组；
- 默认 pi runner 关闭 tools/session/extensions/skills/context files/approval，并设置 thinking=off；保留参数不能重新打开；
- remote consent 未通过时不会启动 runner或发送上下文；
- 两个 judge 并发运行不会重复 claim 同一 prompt；stale claim 仅在 lease 条件满足后恢复；
- failed、needs_review 和显式 retry 的状态转移正确，succeeded 不被普通 judge 重复判断；
- candidate 创建与 judgment 写入之间模拟崩溃后可恢复，不产生第二个 candidate；confidence/cosine 不自动 reject；
- prompts promote/unresolved/ignore/retry 的前置条件、`--force --reason` 留痕和幂等性正确；
- unresolved 清单创建、追加、对账、resolve 幂等；正常 grounding 排除清单；
- 旧 candidates CLI、jfox-promote 三模式和存量 candidate 不回归；daemon 不再创建 gem-synth task。

快速单元测试覆盖纯逻辑、SQLite、runner mock 和 CLI；涉及真实 daemon、transcript 目录、embedding 或完整历史回填的集成测试按项目现有纪律人工执行，本 spec 阶段不运行全量测试。

## 14. 实施切片（供后续 plan 使用）

1. **记录切片**：PromptStore/schema、spool、`/api/prompt`、CC hook、backfill/drain。
2. **证据切片**：transcript context、strict grounding、prompt history 和隐私边界。
3. **判断切片**：runner adapter、JSON schema、claim/state machine、batch judge。
4. **人工闭环切片**：candidate 溯源、promote/reject lifecycle、unresolved 清单、CLI actions。
5. **cutover 切片**：candidate CLI 提取、daemon 旧 task 删除、旧配置迁移、历史数据保留和回归测试。

以上切片是实现顺序，不重新打开产品决策；每个切片完成后必须运行对应的快速验证，再进入下一切片。

## 15. 非目标

- 不在 hook 或 daemon 自动运行 judge，不恢复 30 分钟 gem-synth 循环；
- 不做交互式 TUI，报告 + 逐条命令是固定交互模型；
- 不做 pi-coding-agent 侧 prompt 采集（见 #462）；
- 不让 jfox 变成通用 agent，不内置工具调用框架；
- 不在本次实现 DeepSeek 原生 API client，DeepSeek/其他模型通过 runner 配置接入；
- 不在 hook 热路径计算 embedding、调用 LLM 或做语义 dedup；
- 不做 candidate 自动 dedup、自动 merge、confidence 阈值拒绝或自动晋升；
- 不做 tool_call 审计，旧 tool_call 只保留历史；
- 不删除历史 fragments、candidate、synthesis_log 或 dedup 数据；
- 不做 prompt 内容编辑/删除、跨 session 主题聚类或 prompt embedding 全量索引；
- 不做 unresolved 主题自动合并。
