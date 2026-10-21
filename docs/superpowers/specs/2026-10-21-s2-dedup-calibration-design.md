# Spec — #586 S2② 判重口径与阈值标定

Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-21T00:12:00+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-21T00:38:00+08:00 (round 1: R1-G1 部分接受——驳事实前提并补加载文本验证；R1-G2 docs 再生成；R1-D1 S2④ 同步；R1-D2 失败分支验收；R1-D3 确定性 stub；R1-D4 性能门可移植性；R1-D5 U1 只读表述)
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-21T00:52:00+08:00 (round 2 收敛: R2-D1 A10 slow 双标记；R2-D2 测试命名避开自动标记；R2-D3 A7 钉 `--mode semantic`=0；R2-D4 U2 转发型 stub；R2-D5 统一 `unavailable_reason`)

## 1. 目标与非目标

**目标**：让 `jfox-session-to-permanent` 的 S2② 去重闸门在真实知识库上可用——同领域的新笔记能通过，真重复/近似重复能被识别，且判定不依赖「某个模型下拍脑袋的绝对 cosine 值」。

**做法**：把 S2② 的比较口径改成与索引一致的 `title\n正文`；新增 `jfox similarity` 命令暴露「本库最近邻分布」与候选的分位；S2② 按分位判定，三平台同步；命令不可用时 fail-closed 降人工。

**非目标**（明确不做）：

- 不改 MOC 聚类阈值与 draft 分组（#437）。
- 不做 `search` 的置信度分层 / `--min-score` 通用能力（#444）；本 issue 只提供判重专用的 `similarity` 命令。
- 不修 `suggest-links` 的 RRF 量纲（#583）。
- 不改 `jfox add` 的 0.95 与 gem_synth 的 0.88。
- 不改 #575 的自动档 rubric / 授权机制，只替换 S2② 的量具与阈值来源。
- 不做跨模型的离线标定表；分位基线运行时计算。

## 2. 证据与根因

见 `research/01-similarity-distribution.md`（#437 目录，同一批探针）与 `research/02-code-surface.md`、`03-design-history.md`。三条关键事实：

1. 入库文档是 `f"{title}\n{content}"`（`vector_store.py:125`），S2② 却用一句话摘要查询——短查询 vs 长文档系统性压低 0.15–0.20。
2. 本库摘要→库 top-1：p50 0.709、p95 0.776；`<0.5` 占 0%，`≥0.65` 占 87.2%——自动通过档不可达。
3. 正文↔正文最近邻分布：p50 0.854、p90 0.886、p95 0.897、p99 0.908；同一个 0.65 在两种口径下含义完全不同。

根因不是「阈值数字选错」，而是**口径错 + 绝对阈值不可迁移 + 没有本库基线**。因此修法是「同口径 + 分位判据」，不是换一个魔数。

## 3. 设计决策

| # | 决策 | 选择 | 否决理由 |
|---|---|---|---|
| D1 | S2② 比较什么 | 草稿的 `title\n正文`，与索引序列化完全一致 | 保留摘要口径：短查询噪声大，且真重复的短摘要可能低于同领域长摘要；改用正文可直接复用 Step 5 的草稿文件 |
| D2 | 判据 | 候选 top-1 在**本库最近邻分布**中的分位 | 绝对阈值：模型/库一变就失准（#437 office_hour 与本库差 8 倍）；成对分布：候选 top-1 是 N 次取最大，天然落在成对分布尾部，会系统性误判 |
| D3 | 判定分层 | `new` / `gray` / `covered` 三档，默认分位 50 / 90 | 两档二值：没有灰区就无法表达「拿不准」；#575 的 rubric 需要 fail-closed 的中间档 |
| D4 | 基线来源 | 现有 live permanent 向量的最近邻 top-1 分布（排除自身） | 人工标定表：跨模型/跨库不可维护；成对分布：见 D2 |
| D5 | CLI 面 | 新增 `jfox similarity stats` / `jfox similarity check` | 扩 `search`：会把「候选 vs 库」的判定逻辑塞进通用检索，且 `search` 的 score 在 hybrid/semantic 两种模式下量纲不同；独立命令把协议固化一次 |
| D6 | 命令不可用/无基线 | `verdict=unavailable` → skill 降人工（fail-closed） | 退回 0.5/0.65：会让用户以为修好了，实际仍误拦；静默放行：违反 #249/#575 的检查点约束 |
| D7 | 三平台 | pi / cc / kimi 的 S2② 条款同步改，语义一致 | 只改 pi：cc/kimi 仍走旧口径，问题原样存在 |
| D8 | #585 模板 | 本 issue 先改规范文本；#585 实现时把模板二的 `S2_PASS_MAX`/`S2_GRAY_MAX` 换成 `S2_PASS_BELOW`/`S2_GRAY_BELOW` 并改调 `similarity check` | 模板尚未落地，无法在本 PR 改；但必须在 #585 的 spec/plan 里留硬约束，否则 A7 会红 |

## 4. 组件契约

### 4.1 文档序列化

新增纯函数 `serialize_document(title: str, content: str) -> str`，返回值必须逐字节等于 `vector_store.add_note` 的 `f"{note.title}\n{note.content}"`。实现处加注释互链，并用单测锁定两者一致（A2）。

### 4.2 基线（Baseline）

**输入**：当前 KB 的 live permanent 向量。

**过滤口径**（与 `moc diagnose` 一致）：

- 只取 `type == permanent` 且未归档的笔记；
- 排除 Chroma 中磁盘已不存在的 ghost 行；
- 排除重复 ID 行（保留第一条，按 note_id 排序）。

**统计量**：对每条笔记，计算它与其余笔记的最大 cosine（排除自身）= 最近邻 top-1；输出该分布的 p50 / p75 / p90 / p95 / p99 与样本数。

**最小样本**：`note_count < 30` → 基线不可用（`unavailable`），因为分位太粗。30 是初始值，可在 plan 阶段调。

**实现口径**：

- N ≤ 5000：逐块计算 top-1（每块 ≤ 512 行 × N 列，避免 N×N 全矩阵常驻内存）；
- N > 5000：按 note_id 排序等距抽样 512 条作为查询行，统计量标注 `sampled: true`；
- 不做 embedding 调用，只读已存向量；daemon 不参与基线计算。

**纯函数边界**：

- `nearest_neighbor_scores(matrix: np.ndarray) -> np.ndarray`（排除自身；零范数行返回 0）
- `quantiles(values: np.ndarray, ps: Sequence[float]) -> Dict[str, float]`
- `baseline_is_usable(note_count: int) -> bool`

### 4.3 `jfox similarity stats`

```
jfox similarity stats [--kb NAME] [--json] [--refresh]
```

JSON（稳定契约）：

```json
{
  "success": true,
  "kb": "default",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimension": 512,
  "note_count": 211,
  "sampled": false,
  "baseline": {
    "p50": 0.854, "p75": 0.874, "p90": 0.886, "p95": 0.897, "p99": 0.908
  },
  "policy": {"pass_below": 50, "gray_below": 90},
  "cached": true,
  "computed_at": "2026-10-21T00:10:00+08:00",
  "unavailable_reason": null
}
```

- 基线不可用时 `baseline: null`、`unavailable_reason` 给原因，`success` 仍为 `true`（命令本身成功）。
- `--refresh` 强制重算并覆盖缓存。
- `model` 取 `backend.model_name or config.embedding_model`；`dimension` 取矩阵列数。二者只作展示与缓存键的一部分。

### 4.4 `jfox similarity check`

```
jfox similarity check (--content-file PATH | --content TEXT) [--title TEXT]
                       [--exclude-id ID] [--top 3] [--pass-below 50] [--gray-below 90]
                       [--kb NAME] [--json] [--refresh]
```

- `--content-file` 与 `--content` 二选一，同时给报错。
- `--title` 可选；缺省时 JSON 带 `warnings: ["title missing; comparison may be less accurate"]`（索引文档总是含标题）。
- `--exclude-id` 用于 edit 场景：从匹配结果与 top-1 中排除该 ID；基线不排除。
- `--pass-below` / `--gray-below` 为 0–100 的整数分位，校验 `0 ≤ pass < gray ≤ 100`；正常 skill 流程不传，用默认值。
- 候选文本用 `serialize_document(title, content)` 生成，再经 daemon 编码；**`daemon_only=True`**，daemon 不可用直接 `unavailable`，不回退本地模型加载（与 #383 红线一致）。
- 查询向量维度必须等于基线维度，否则 `unavailable`（模型切换未重建索引的典型症状）。

JSON：

```json
{
  "success": true,
  "kb": "default",
  "candidate": {"title": "…", "chars": 812},
  "top1": {"id": "…", "title": "…", "score": 0.883, "percentile": 82.5},
  "matches": [
    {"id": "…", "title": "…", "score": 0.883, "percentile": 82.5}
  ],
  "baseline": {"p50": 0.854, "p90": 0.886, "p95": 0.897, "p99": 0.908, "note_count": 211},
  "policy": {"pass_below": 50, "gray_below": 90},
  "verdict": "gray",
  "unavailable_reason": null,
  "warnings": []
}
```

- `verdict` ∈ `new | gray | covered | unavailable`。
- 空库 / 基线不可用 / daemon 不可用 / 维度不匹配 → `success: true, verdict: "unavailable", unavailable_reason: ...`（原因字段名固定为 `unavailable_reason`）。
- 输入错误（文件不存在、两个内容源都缺、分位非法）→ `success: false` + 非零退出码。

### 4.5 判定策略

```
percentile = 100 * (#{nn < top1} / N)
verdict = "new"     if percentile <  pass_below
          "gray"    if percentile <  gray_below
          "covered" otherwise
```

- 默认 `pass_below=50`、`gray_below=90`：初始值，U1 dogfood 校准；改动只改默认常量，不改协议。
- 并列值用严格 `<` 计数；`percentile` 保留 1 位小数。
- 纯函数 `classify_verdict(percentile, pass_below, gray_below) -> str`，单测覆盖边界（等于阈值、0、100）。

### 4.6 缓存与失效

- 路径：`<KB>/.zk/similarity_stats.json`；原子写（temp + `os.replace`），失败只告警不阻塞（下次重算）。
- 缓存键：`model`、`dimension`、`note_count`、`index_state.last_rebuild`（`load_index_state`）。
- 失效条件：任一键变化、`computed_at` 超过 7 天、`--refresh`。键变化时删除旧文件再写。
- 统计只依赖向量快照；笔记正文改了但没 reindex 时缓存仍可能旧——7 天上限是兜底，文档里写明。

### 4.7 三平台 skill 集成

三份 SKILL.md 的 S2② 行改为（措辞按平台微调，语义一致）：

```
② 追加 `jfox similarity check --title "<草稿标题>" --content-file <草稿正文文件> --json`：
   verdict=new → 通过；gray → 灰色区降人工；covered → 降人工并按「可补充/已覆盖」走原流程；
   unavailable / 命令不存在 / 无 verdict 字段 / 非零退出 → 信号缺失 → 降人工（fail-closed）。
```

- 草稿正文在 Step 3 已生成；Step 3.5 前写入临时文件供本命令与 Step 5 的 `jfox add --content-file` 复用。
- **S2④ 同步**：S2④「落库前重跑一次 search」与 Step 5 自动档代码块里的「落库前重跑 search 复核去重结论」都改为重跑 `jfox similarity check`（基线有缓存，成本低）。复核必须使用与 S2② 相同的口径，否则复核的不是产生结论的信号。
- 删除旧文本中的 `0.5` / `0.65` 与「阈值为初始值，dogfood 校准」；改为「分位阈值由 `jfox similarity stats` 暴露，初始值 50/90，dogfood 校准」。
- 命令参考补一行：pi `jfox-common` §7、cc `manage`、kimi `jfox-manage` 各加 `jfox similarity stats|check` 的用途与一个示例。
- #585 的实现约束写进本 spec §12：模板二的常量与调用必须同步，否则 A7 红。

## 5. 数据流

```
Step 3 起草（title + body）
  └─ 写临时文件 draft.md
       └─ Step 3.5 S2②：jfox similarity check --title T --content-file draft.md --json
            ├─ daemon 编码 serialize_document(T, body)
            ├─ 读/算基线（live permanent 最近邻分位）
            ├─ top-1 → percentile → verdict
            └─ new → 通过；gray/covered/unavailable → 降人工
                 └─ Step 5：jfox add --content-file draft.md（无 --force）
                      └─ add 的 0.95 正文防重仍是最后一道机器防线
```

## 6. 降级路径

| 情形 | 行为 |
|---|---|
| `jfox similarity` 命令不存在（旧 CLI） | S2② 信号缺失 → 降人工；文档显式写「不要退回 0.5/0.65」 |
| daemon 未启动 / 编码失败 | `verdict=unavailable` → 降人工 |
| 空库 / permanent < 30 | `unavailable` → 降人工 |
| 维度不匹配（换模型未重建索引） | `unavailable` → 降人工；提示 `jfox index rebuild` |
| 基线缓存损坏 | 忽略缓存并重算；重算失败 → `unavailable` |
| `similarity check` 返回非 JSON / 缺 `verdict` | 信号缺失 → 降人工 |
| 候选标题缺失 | 仍计算，但带 warning；skill 流程总是传标题 |

## 7. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|---|---|---|---|---|
| A1 | 纯函数：最近邻分数、分位、分档 | 自动化（unit） | 新增 `tests/unit/test_similarity.py`：构造小矩阵（3×3、零范数行、并列值），断言 `nearest_neighbor_scores` / `quantiles` / `classify_verdict`；**测试函数名避开 `vector`/`semantic`/`embedding`/`search` 子串**（conftest 自动标记规则会把它踢出 Fast CI） | 数值与边界符合 §4.2/§4.5 |
| A2 | 序列化与索引一致 | 自动化（unit） | 断言 `serialize_document(t, c) == f"{t}\n{c}"`；并用 mock `add_note` 捕获 document 做对照 | 逐字节相等 |
| A3 | 基线过滤口径 | 自动化（unit） | 用 fixture 构造 permanent/archived/ghost/重复 ID 向量，断言只保留 live permanent | 计数与 ID 集合符合 §4.2 |
| A4 | 缓存与失效 | 自动化（unit） | 注入临时 `.zk`：命中、`--refresh`、note_count 变化、model/dimension 变化、超过 7 天、**缓存文件损坏（非法 JSON / 缺字段）** | 命中不重算；任一失效条件或损坏触发重算；损坏不抛异常 |
| A5 | `similarity stats` JSON 契约 | 自动化（integration） | 临时 KB + **确定性 stub 后端**（文本→固定向量，沿用 `tests/unit/test_add_dedup.py:35` 模式），`CliRunner` 跑 `stats --json` | 字段齐全；<30 条时 `baseline=null` + `unavailable_reason` |
| A6 | `similarity check` 三档 + unavailable | 自动化（integration） | 确定性 stub：明显远/中/近三档；空库；维度不匹配；`--exclude-id`；**daemon 不可用（stub 抛错）**；**`--title` 缺省** | `verdict` 分别为 new/gray/covered/unavailable；exclude 生效；daemon 不可用返回 `unavailable`；缺标题带 `warnings` 且仍出 verdict |
| A7 | 三平台 S2② 条款 | 自动化（static） | 新测试 grep 三份 SKILL.md：含 `jfox similarity check`、四档处置、`fail-closed`；不含 `0.5–0.65` 旧阈值文本；**且 `--mode semantic` 出现次数为 0**（现各 2 处：S2② 行 + Step 5 自动档代码块，改后归零） | 三份全命中，旧文本 0 命中，`--mode semantic` 0 命中 |
| A8 | 命令注册与帮助 | 自动化（unit） | `CliRunner` 跑 `jfox similarity --help` / `stats --help` / `check --help` | 退出码 0；子命令存在 |
| A9 | 文档通过 markdownlint | 自动化（static） | `npx --yes markdownlint-cli2` 三份 SKILL.md + 三份命令参考 | 0 issues |
| A10 | 性能护栏 | 自动化（performance + slow 双标记；Fast CI 靠 `slow` 排除，`performance` 标记本身不被 Fast 选择器排除） | 5000×512 合成矩阵测 `nearest_neighbor_scores`（chunk 路径）；结构断言：峰值缓冲 ≤ `chunk_size × N` 浮点（不物化 N×N）；时间用 `time.perf_counter`；`pytestmark = [pytest.mark.performance, pytest.mark.slow]`（对齐 `tests/performance/test_performance.py:316` 惯例） | 结构断言通过；本机 CPU 单次 < 10s（CI 不硬门禁） |
| A11 | 生成文档无 drift | 自动化（static） | `uv run python scripts/generate_docs.py && git diff --exit-code docs/cli-reference.md docs/plugin-inventory.md`；并断言 `docs/cli-descriptions.yaml` 含 `jfox similarity` / `jfox similarity stats` / `jfox similarity check` 三条英文描述 | diff 为空；三条描述存在；生成器校验通过 |
| U1 | 真实库 dogfood | 用户实测 | 在 default KB 用 ≥20 条真实候选跑 `similarity check`，记录 verdict/percentile 与人工判断；**不会改笔记或索引**，只可能写 `.zk/similarity_stats.json` 缓存（可事后删除） | 同领域新笔记多数 `new`；真重复/同义改写落 `gray/covered`；据此确认或调整 50/90 |
| U2 | 旧 CLI 降级 | 用户实测 | 用**转发型** `jfox` wrapper 模拟「旧 CLI 缺 similarity 子命令」：非 `similarity` 参数 `exec` 真实 jfox；首个参数为 `similarity` 时输出 `No such command` 并非零退出（不要用遮蔽全部命令的 stub，否则 S2① 与 Step 5 一起失败，测不到目标分支）；或直接安装当前已发布版本的 jfox-cli | `similarity` 缺失时 S2② 全部降人工，S2①/Step 5 仍正常；无静默通过 |
| U3 | 三平台生效 | 用户实测 | pi：`git pull` + 新会话/`/reload`（本机为本地路径包）；若用户是 `pi install git:…` 的包缓存安装，则先更新包。**验证时让会话输出 S2② 新条款原文（含 `jfox similarity check`）**；cc/kimi 各自发版后同样验证 | 命令可调用；会话引用的是新条款原文；三平台输出一致。仍显示 `0.5/0.65` → 未生效，记 blocked |

## 8. 可测性拆分设计

**纯函数（`jfox/similarity.py`，不读盘/不调模型）**：

| 单元 | 签名 | 测试要点 |
|---|---|---|
| `serialize_document` | `(title, content) -> str` | 与 `vector_store` 逐字节一致；空标题/空正文 |
| `nearest_neighbor_scores` | `(matrix) -> np.ndarray` | 对角线排除；零范数行得 0；N=1 得 0；并列值 |
| `quantiles` | `(values, ps) -> dict` | 空数组；单值；标准分位 |
| `percentile_rank` | `(value, sorted_values) -> float` | 0/100 边界；并列；空数组 |
| `classify_verdict` | `(pct, pass_below, gray_below) -> str` | 等于阈值；0/100；非法分位抛错 |
| `baseline_is_usable` | `(note_count) -> bool` | 29/30 边界 |

**I/O 层（可注入依赖，不进纯函数测试）**：

| 单元 | 职责 | 测试方式 |
|---|---|---|
| `load_live_permanent_matrix(config)` | 读 Chroma 快照 + note_index，按 §4.2 过滤，返回 ids/titles/matrix | 单测用 fake vector store；集成测试用临时 KB |
| `load_or_compute_baseline(config, refresh)` | 缓存读写、失效判断、抽样 | 单测注入临时路径与假矩阵；不依赖 daemon |
| `check_candidate(config, title, content, ...)` | 序列化、daemon 编码、top-k、分位、分档 | 集成测试用**确定性 stub**（文本→固定向量，参考 `tests/unit/test_add_dedup.py:35`），不用 `mock_embedding_backend` 的随机向量；daemon 不可用用 fake 抛错 |

**CLI 层**：Typer 薄封装，只做参数校验、调用 I/O 层、格式化 JSON/table；错误映射为 `success: false` + 退出码。CLI 测试用 `CliRunner` + 临时 `ZK_CONFIG_PATH`/`ZK_KB_ROOT`，不碰真实库。

**测试边界**：单测不加载模型、不读写真实 KB；集成测试用 mock embedding；U1/U2/U3 是真实运行时验证，不能由静态测试替代。

**命名约束**：`tests/conftest.py:285-289` 会把 nodeid 含 `vector` / `semantic` / `embedding` / `search` 的测试自动标 `embedding`，从而被 Fast CI 的 `not embedding` 排除。A1/A3 的矩阵与零范数用例命名要避开这些子串（用 `zero_norm` / `matrix`），否则关键边界单测会静默落出 PR CI。

## 9. 部署与执行前提

- **jfox CLI**：新命令随下一次 release 发布；用户需 `uv tool upgrade jfox-cli`。未升级时 skill 走 `unavailable` → 降人工。
- **skill（本机 pi）**：`~/.pi/agent/settings.json` 的 `packages` 以本地路径引用主 checkout（`../../work/git-repo/jfox`），`package.json` 的 `pi.skills` 指向 `./skills-recommend/pi`；因此 `git pull` + 新会话/`/reload` 加载的就是主 checkout 的新文本（本会话的 available-skills 路径亦为 `/home/elling/work/git-repo/jfox/skills-recommend/pi/...`）。**若用户以 `pi install git:github.com/zhuxixi/jfox` 安装包缓存，则 `git pull` 不刷新包缓存，需要重新安装/更新包**——U3 必须让会话引用新条款原文来证明加载的是哪份文本。
- **U1 的执行时机**：合并并升级 CLI 后，在真实会话里跑；不要在 worktree 内伪造「已生效」。
- **隔离**：集成测试用 `ZK_CONFIG_PATH` + `ZK_KB_ROOT` 指向临时目录；U1 不改真实库的笔记与索引，`similarity check` 可能写 `.zk/similarity_stats.json` 缓存（可事后删除），写库仍走正常 Step 5。

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 50/90 初始分位不合真实候选分布 | 自动档过松或过紧 | U1 dogfood ≥20 条后校准；阈值只改默认常量，协议不变 |
| 小库（<30）不可用 | 新库全部降人工 | 显式 `unavailable` + 文档说明；不静默放行 |
| 最近邻分布被库内近重复抬高 | 真重复可能落 gray 而非 covered | `add` 0.95 仍是最后防线；U1 检查误判；必要时提高 `gray_below` |
| 缓存陈旧（改文未 reindex） | 分位轻微偏移 | 7 天上限 + `--refresh`；判定只看 top-1 相对位置，偏移影响有限 |
| 新命令维护面 | 多一个公共接口 | 只暴露 `stats`/`check` 两个只读子命令；不承诺通用检索能力 |
| 发布滞后 | 合并后用户环境仍是旧行为 | §6 降级路径 + §9 部署说明；U3 跟踪 |
| #585 模板未同步 | A7 静态测试红 | #585 续做前先读 §12；模板常量换名并改调 `check` |

## 11. 受影响文件

**新增**：

- `jfox/similarity.py`（纯函数 + I/O 层）
- `jfox/similarity_cli.py`（Typer 子应用）
- `tests/unit/test_similarity.py`
- `tests/integration/test_similarity_cli.py`
- `tests/unit/test_session_dedup_skill_docs.py`（三平台 S2② 静态契约）

**修改**：

- `jfox/cli.py`（注册 `similarity` 子应用）
- `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- `skills-recommend/pi/jfox-common/SKILL.md`（命令参考一行）
- `packages/cc-plugin/skills/manage/SKILL.md`（命令参考一行）
- `packages/kimi-plugin/skills/jfox-manage/SKILL.md`（命令参考一行）
- `jfox/moc/cluster.py`（把 `classify_vector_id` 迁到 `jfox/similarity.py` 并 re-export，避免两套过滤口径）
- `docs/cli-descriptions.yaml`（新增 `jfox similarity` / `jfox similarity stats` / `jfox similarity check` 三条英文描述；缺条目生成器会报错）
- `docs/cli-reference.md`（**生成文件，禁止手改**：`uv run python scripts/generate_docs.py` 再生成并随 PR 提交）
- `README.md`（命令速查一行，可选但建议）
- `pyproject.toml` / `jfox/__init__.py` / `uv.lock`：**不改**（本 issue 不发版；发版按项目规则单独做）

## 12. 后续与遗留

- **#585**：模板二落地时，把 `S2_PASS_MAX=0.5 / S2_GRAY_MAX=0.65` 改为 `S2_PASS_BELOW=50 / S2_GRAY_BELOW=90`，并把第 1 步从 `jfox search "<摘要>" --mode semantic` 改为 `jfox similarity check --title <t> --content-file <f>`；A7 静态一致性测试随之改。
- **#444**：`search --min-score` / `no_match` / 置信度分层仍是通用能力，本 issue 不实现；若 #444 先落地，`similarity check` 可复用其分位设施（不阻塞）。
- **#437**：`similarity stats` 的基线口径与 MOC 的正文↔正文一致，后续可复用；MOC 的推荐阈值仍归 #437。
- **校准数据**：U1 的 ≥20 条真实候选分布应回填本 issue 与 #585，作为 50/90 的最终依据。
- **已知限制**：`model` 字符串在 daemon 未启动时可能是 `auto`，缓存键主要靠 `dimension + note_count + last_rebuild`；同维度换模型不会被识别，需 `--refresh` 或重建索引。
