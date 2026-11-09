# 根因报告 / spec: suggest-links 语义分支恒空（issue #583）

Drafted: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-29T23:05:00+08:00
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-29T23:20:00+08:00 —— 第 1 轮复核：3 真缺口（测试被自动标记排除 / 接缝查不到语义库 / organize 未纳入文档范围）+ 4 细化全部「接受并改」，详见 research/spec-review-round-1.md
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-29T23:40:00+08:00 —— 第 2 轮：1 真缺口（cli_fast 子进程拿不到 mock patch → 改为全进程内入库）+ 2 细化（A4 补噪声地板表述、A4 给可执行路径与锚点）全部「接受并改」，详见 research/spec-review-round-2.md
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-29T23:55:00+08:00 —— 第 3 轮：2 真缺口（mock patch 需显式安装 / promote cc+kimi 副本漏纳入）+ 3 细化全部「接受并改」，详见 research/spec-review-round-3.md

## 0. 结论

`jfox suggest-links` 的「语义」分支在正常知识库里**永远返回零条**：它用默认 hybrid 模式搜索，而 hybrid 会把每条结果的 `score` 覆盖成 RRF 融合分（rank-1 约 0.016，双通道封顶约 0.033），再拿这个分数与 `threshold`（默认 0.6）比较——恒不通过。只有 BM25 一条结果都没有时（罕见）语义分支才保留真实 cosine 分。

后果：suggest-links 实际是纯关键词工具（输出分数为 0.3–0.6 的关键词重合率合成分），但文档、CLI help、三个 session-to-permanent skill、三个 organize skill 与 promote skill 都把它当作「语义找关联、阈值 ≥0.6」使用。换措辞的语义重复/关联因此系统性漏检——这正是知识库笔记《session-to-permanent 流程产生重复笔记的原因》记录盲区的根因。

## 1. 证据链（main@bede011 逐行核对）

| 环节 | 位置 | 事实 |
|---|---|---|
| 调用方式 | `jfox/note.py:1118` | `semantic_results = search_notes(content, top_k=top_k * 2)`，**未传 `mode`、也无 `cfg`** |
| 默认模式 | `jfox/note.py:834` | `mode: str = "hybrid"` |
| 阈值过滤 | `jfox/note.py:1123` | `if score >= threshold:`（threshold 默认 0.6，`:1093`） |
| RRF 覆盖 | `jfox/search_engine.py:347` | `data["score"] = fused_scores[note_id]` |
| RRF 公式 | `jfox/search_engine.py:304,311` | `1 / (rrf_k + rank)`，`rrf_k=60`（`:38`）→ rank1=0.0164，双通道 rank1=0.0328 |
| 唯一例外 | `jfox/search_engine.py:290-295` | `elif not bm25_results:` 才直接返回语义结果（保留 cosine）；BM25 有结果即走 RRF |
| 关键词分数 | `jfox/note.py:1161` | `keyword_score = 0.3 + (match_count / len(keywords)) * 0.3` → 0.3–0.6 |
| 关键词准入 | `jfox/note.py:1164` | `keyword_score >= threshold * 0.5`（注意：**不是** `threshold`） |

复现（main@bede011）：任取一篇文章摘要执行 `jfox suggest-links "<摘要>" --json`，返回项若存在则 `match_type` 全为 `keyword`、`score` 全在 0.3–0.6。`--threshold 0.9` 时**不保证** 0 条——关键词分支准入线降到 0.45，命中率高的 query 仍会返回 0.45–0.6 的 keyword 项；确定的是**任何阈值下都不会出现 `match_type == "semantic"` 的项**。

现有测试 `tests/test_suggest_links.py:97` 对阈值 0.9 只断言「返回项的 score ≥ 0.9」，返回空集时循环体不执行即通过——**空集空断言**，从未验证过语义路径（本 issue 得以长期潜伏的原因之一）。

旁证：issue #575 的 spec 交叉复核实证同一结论并已规避（S2② 改用 `jfox search --mode semantic` 独立量具，D11）。

## 2. 影响面

- `jfox-session-to-permanent`（三平台）Step 2：声称「语义找关联笔记」，实际只有关键词；MOC 候选信号（`type: structure`）也只在标题/标签字面命中时出现
- `jfox-organize`（三平台）：明文以「`suggest-links` 分数 ≥ 0.6」作为 `[[wiki links]]` 候选门槛（pi 副本 `:142`、`:162`；cc/kimi 同款表述）——同样只吃关键词分
- `jfox-promote`（**三平台**：`skills-recommend/pi/jfox-promote/SKILL.md`、`packages/cc-plugin/skills/promote/SKILL.md`、`packages/kimi-plugin/skills/jfox-promote/SKILL.md`）§6 已知坑「suggest-links 漏掉语义相近的笔记」的实际根因；cc/kimi 副本还带「阈值可放宽到 0.4–0.5」与「相似度返回不到 0.6」等在新量纲下需重述的表述
- 所有把 `score` 当语义相似度的脚本/agent

## 3. 修复方案

### 方案 A（推荐）：语义分支改走纯 semantic 模式

`jfox/note.py` 的语义分支改为 `search_notes(content, top_k=top_k * 2, mode="semantic")`，其余逻辑保持不变：

- 分数变回真实 cosine（`score = 1 - distance`，collection metric = cosine，`jfox/vector_store.py:112-113,221`）
- `threshold` 随之对 cosine 生效，skill 文档里的「阈值 ≥0.6」首次成为真命题
- 混合输出的两个量纲由 `match_type`（`semantic` / `keyword`）区分；排序仍按 score 降序（cosine ≥0.6 > keyword ≤0.6，语义项自然在前）

代价与边界（如实写入文档）：

- 同库内 cosine 地板偏高（实测无关对 0.55–0.68，见笔记《jfox default 库的语义相似度地板偏高》）：0.6 只能当「噪声地板」，**不能**理解为「强相关」；调用方应看排序与 `match_type`
- **关键词分支的准入线是 `threshold * 0.5`**（`note.py:1164`），与语义分支的 `threshold` 不同口径；文档与 CLI help 必须写明，否则调用方会误读
- `cfg` 边界（**已知限制，不在本 issue 修复**）：`suggest_links(cfg=X)` 的语义分支经 `search_notes`（无 `cfg` 参数）走全局引擎/当前 KB，而关键词分支走 `X`；CLI 路径不传 `cfg`（`cli.py:2740`），两分支一致。库调用方若 `X` ≠ 当前 KB，两分支会查不同库
- embedding 不可用（#519 无 embed 组件 / daemon 宕机且无本地模型）时语义分支为空，仅剩关键词结果，沿用现有 `warnings` 降级通道（`jfox/cli.py:2737-2752`）
- 每次调用多一次 embedding 查询（daemon 在跑时毫秒级 + CLI 启动开销）

### 方案 B（最小、纯文档）：承认它是关键词工具

不改代码，把 docstring / CLI help / 六个 skill 的「语义」措辞改为「关键词」，需要语义时显式指向 `jfox search --mode semantic`。

- 优点：零行为变更、零性能影响
- 缺点：suggest-links 失去「找语义邻居」的定位；各 skill 要各写一遍 `search --mode semantic` 逻辑；#575 已有 4 处文本依赖 suggest-links 供补链，改动面反而分散

### 方案 C（激进）：语义分支改为相对排名

不按绝对阈值，而取 top-N 且 `score >= best_score - margin`（如 margin=0.08），`threshold` 保留为绝对地板。

- 优点：对齐「同库 cosine 聚集」的现实，返回真正最近的邻居
- 缺点：新增参数与语义；与 skill 既有「阈值 ≥0.6」表述冲突；超出 bug 修复必要范围

**推荐 A**：一处改动（一行参数 + 文档），让既有语义契约成立；C 留作后续质量优化 issue（若 dogfood 发现 0.6 地板噪音过大再开）。

## 4. 非目标

- 不修 #575 的 S2②（已用 `--mode semantic`，独立）
- 不改任何 skill 的阈值数字（0.6 不变），只澄清「两个量纲不互通 + keyword 准入是 threshold×0.5」
- 不引入相对排名 / margin 参数（方案 C，另开 issue）
- 不改关键词分支的 `threshold * 0.5` 准入门槛（保持既有行为）
- **不修 `cfg` 跨库不一致**（语义分支忽略 `cfg`）：记为已知限制，必要时另开 issue
- 不动 `search` / `query` / `refs` 等其它命令

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 语义分支返回真实 cosine 量纲 | 自动化验证（unit，单文件直跑） | `tests/unit/test_link_assist_score_scale.py::test_link_scores_use_cosine_scale`；接缝见下方「可测性拆分」 | 至少 1 条 `match_type == "semantic"`；且其 `score > 0.1`（RRF 量级为 0.016–0.033，量纲切换得证） |
| A2 | 阈值对语义分生效（先证有、再证无） | 自动化验证（unit，单文件直跑） | 同文件：低阈值（0.05）先断言存在 `semantic` 项；高阈值（0.999）再断言 **无 `semantic` 项**（不断言整体为空——keyword 项可能仍在，其准入线是 threshold×0.5） | 两段断言都通过，且第二段显式排除「空集通过」 |
| A3 | embedding 不可用时降级不炸 | 自动化验证（unit，单文件直跑） | 同文件：`patch("jfox.embedding_backend.get_backend", side_effect=EmbedDependencyMissingError(...))` → `suggest_links` 不抛异常，返回项全为 `keyword` 或空 | 不抛异常；无 semantic 项 |
| A4 | 文档反映真实语义（九份 skill + CLI help + docstring） | 自动化验证（static） | ① 改动范围（**9 个 md + 2 处代码**）：`jfox/note.py` docstring、`jfox/cli.py:2783-2810` help/示例；`skills-recommend/pi/jfox-session-to-permanent/SKILL.md`、`packages/cc-plugin/skills/session-to-permanent/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`；`skills-recommend/pi/jfox-organize/SKILL.md`、`packages/cc-plugin/skills/organize/SKILL.md`、`packages/kimi-plugin/skills/jfox-organize/SKILL.md`；`skills-recommend/pi/jfox-promote/SKILL.md`、`packages/cc-plugin/skills/promote/SKILL.md`、`packages/kimi-plugin/skills/jfox-promote/SKILL.md`；② 可执行锚点：9 个 md 各跑 `grep -c "cosine" <file>` ≥1 且 `grep -c "match_type" <file>` ≥1；**两处代码同样加锚点**：`grep -c "match_type" jfox/cli.py` ≥1（help 文本）、`grep -c "量纲\|match_type" jfox/note.py` ≥1（docstring）；③ lint：`npx --yes markdownlint-cli2 <逐个改动的 md>` | 锚点命中；文档含五要素（semantic=cosine、keyword=关键词比率（准入 threshold×0.5）、两量纲不互通、看 match_type、0.6 为噪声地板非强相关）；lint 0 issues |
| A6 | 新测试确实被 Fast 口径收集 | 自动化验证（static） | `uv run pytest tests/ -m "not embedding and not slow" --collect-only -q \| grep -c test_link_assist_score_scale` | 结果 ≥3（A1–A3 三个用例均被收集，防命名踩中 conftest 自动标记而静默失效） |
| A5 | 既有行为回归 | 自动化验证（integration） | `uv run pytest tests/test_suggest_links.py -q` + `uv run pytest tests/ -m "not embedding and not slow" -q` | 全绿（基线 1911+） |

**可测性拆分设计**：

- **文件与测试命名约束（关键）**：`tests/conftest.py:290-303` 会按 nodeid 关键词自动加标记——含 `semantic`/`vector`/`embedding` → `embedding` + `very_slow`；含 `search`/`suggest`/`query` → `slow`。`-m "not embedding and not slow"`（Fast CI 与 A5 同口径）会静默 deselect。**因此新测试文件与所有测试函数名必须避开这些词**：文件名 `test_link_assist_score_scale.py`，函数名用 `link`/`score`/`cosine`/`threshold`/`fallback` 等词；文件头加一段注释说明该命名约束来自 conftest 自动标记规则，防后人改名踩坑。A1–A3 的单文件直跑命令：`uv run pytest tests/unit/test_link_assist_score_scale.py -q`。
- **接缝（必须全进程内，不能用 cli_fast 写入）**：`cli_fast` 的 mock patch 只作用于 pytest 进程（`tests/conftest.py:185-189`），而 `ZKCLI` 写笔记是 `sys.executable -m jfox` 子进程（`tests/utils/jfox_cli.py:80,103-104`）——子进程拿不到 patch：CI Fast（无 embed 组件）时 `save_note` 直接跳过向量索引（`jfox/note.py:178-182`），chroma 为空；dev 环境子进程用真实模型（512/1024 维），与进程内 384 维 mock 维度不匹配或 cosine≈0。正确接缝是**入库与查询全在同一进程、同一个 mock patch 下**：

  ```python
  import unittest.mock

  from jfox import embedding_backend
  from jfox.config import use_kb
  from jfox.models import NoteType
  from jfox.note import create_note, save_note, suggest_links
  from utils.temp_kb import temp_kb_registered

  def test_link_scores_use_cosine_scale(self, mock_embedding_backend):
      # 注意：mock_embedding_backend fixture 只返回实例、不安装 patch；
      # 必须像 cli_fast（tests/conftest.py:182-186）一样在本测试体内显式安装。
      with unittest.mock.patch.object(
          embedding_backend, "get_backend", lambda: mock_embedding_backend
      ):
          with temp_kb_registered() as kb_name:
              with use_kb(kb_name):          # 先切库：重置单例，引擎/向量库绑定该 KB
                  for title, body in corpus:  # 进程内写入
                      n = create_note(content=body, title=title, note_type=NoteType.PERMANENT)
                      assert save_note(n)     # → get_vector_store().add_note() → 已 patch 的 384 维 mock 向量
                  results = suggest_links("<摘要>", top_k=5, threshold=0.05)
  ```

  顺序关键：先 `use_kb`（触发 `_reset_singletons()`，`jfox/config.py:196-213,131-145`）再写再查，否则 `get_vector_store()` 单例仍绑定 import 时的 `config` 快照目录。
- **kimi-cli 目录的排除口径**：`skills-recommend/kimi-cli/` 下也有 organize 副本，但 README 已标记它由 `packages/kimi-plugin` 新版插件取代（`skills-recommend/README.md:8`，或 `:38-40` 的「Kimi Code CLI（推荐新版插件）」节），**本 issue 不更新**；其余仅引用命令语法、不解释 score 语义的文件（jfox-search ×4、jfox-manage ×2、jfox-common ×2、using-jfox、`docs/cli-reference.md:1299` 参数表、`docs/json-schemas.md` schema 表）同样不改。
- **mock 后端的已知局限（必须写进断言注释）**：`MockEmbeddingBackend.encode` 返回 `np.random.rand` 全正随机向量（`tests/conftest.py:95-99`），任意两段文本的 cosine 约 0.75（集中 ±0.02），**无区分度**——「相近/无关」的排序在该 mock 下不可断言。因此 A1/A2 只证明「量纲切换 + 阈值生效」，不证明语义排序正确性；排序质量由真实模型环境（`embedding` 标记的 Full job）或后续 eval issue 覆盖。
- **阈值断言必须两段**（先证有再证无），避免重蹈 `test_suggest_links_respects_threshold` 的空集空断言（本 issue 的成因之一）。

## 6. 风险与回滚

| 风险 | 对策 |
|---|---|
| 语义分支复活后 0.6 地板在成熟库返回大量「弱相关」邻居，噪音上升 | 文档明确「0.6 是噪声地板不是强相关」；dogfood 反馈噪音过大则按方案 C 另开 issue |
| embedding 不可用时语义分支为空，调用方误以为「无关联」 | 沿用现有 `warnings` 降级信号（`_suggest_links_impl` 已实现）；A3 覆盖 |
| 新测试被 conftest 自动标记而排除出 Fast CI | 命名约束 + 文件头注释 + A5 与 A1–A3 显式给出直跑命令 |
| 每次调用多一次 embedding 查询 | daemon 在跑时毫秒级；无 daemon 时异常捕获降级 |
| 回滚 | 单行参数改动，可单独 revert；无数据/索引迁移 |

## 7. 关联

- #583（本 issue）、#575（发现与规避来源）
- #528（去重竞态）、#444（搜索置信度分层）
- KB 笔记：《suggest-links 语义分支恒空：分数是关键词比率而非语义相似度》（202610200843425615）、《jfox default 库的语义相似度地板偏高》（202610260842281710）、《session-to-permanent 流程产生重复笔记的原因》（202608270835202888）

## 8. 环境

jfox main@bede011（PR #598 合并后）；default KB ~1074 permanent；Python 3.10+；测试用 mock embedding fixture。
