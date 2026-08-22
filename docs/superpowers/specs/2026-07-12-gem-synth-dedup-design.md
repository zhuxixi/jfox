# gem-synth 合成去重（dedup）设计

**日期**：2026-07-12
**目标 PR 分支**：`feat/gem-synth-dedup`（main 受保护，必须新分支 + PR）
**关联**：根因①（candidate 积压诊断，见 memory `candidate-promote-backlog`）；补 #291（#291 只挡同锚点重处理，不挡不同锚点产出同知识）

## 1. 问题

`synthesis_log` 现以 **`anchor_fragment_id`（输入）** 为去重键：`find_anchors` 用 `NOT EXISTS` 子查询排除已处理锚点。这挡住了"同一碎片被合成两次"，但挡不住**不同碎片产出同一知识点**。

实测存量 754 条 candidate 里：

- 142 条**逐字同标题**（如「cc-plugin 版本号需同步更新三处字段」出现 3 次，来自 3 个不同锚点碎片）
- ~150 条**同主题改写**（Zima 双 Bot babysit 293 条、DeepSeek 批量 43 条等同事实改写）
- 时间分布坐实 runaway loop：07-08/10/11 三天各产 200+ 条

根因：dedup 键在输入（fragment），没看输出（candidate 知识点）。

## 2. 目标 / 非目标

**目标**

- gem-synth 在**存盘前**用正文 embedding 余弦检查：若与已有 candidate 或已晋升 permanent 重复，**不存盘**，锚点记 `duplicate` 状态。
- 从源头不再产生重复 candidate（forward-going）。
- 一次性 backfill 命令把现有 candidate + permanent 灌入 dedup 库，让新机制起步就有对比集。

**非目标**

- 不改 LLM prompt（合成质量另算）。
- 不自动清理 702 条历史 pending（那是 L5 过审的活，本特性只管 forward + 提供 backfill 让对比集就位）。
- 不改主搜索索引（candidate 仍 `add_to_index=False`，不污染搜索）。

## 3. 架构

新增一个**自包含 dedup 子系统**（方案 A：sqlite + numpy），与主 ChromaDB 解耦，数据落在 gem_synth 自己的 `synthesis_log.db` 旁。

### 数据流（单锚点合成）

```
synthesize_anchor(anchor):
  … transcript / grounding / llm 合成 …（不变）
  llm_result = synthesize_with_llm(…)            # 不变
  if llm_result is None: mark_failed; return     # 不变

  # ★ 新增：存盘前去重检查
  if cfg.dedup_enabled:
      dup_of = dedup_check(llm_result["content"])
      if dup_of:
          log.mark_duplicate(anchor["fragment_id"], dup_of)
          return None                              # 不存盘，锚点算处理完

  note_id = _save_candidate_note(llm_result, anchor)   # 不变
  if note_id: dedup_store.upsert(note_id, "candidate", llm_result["content"])  # ★ 存盘成功后入 dedup 库
  log.mark_processed(…)                           # 不变
```

检查点选 **post-LLM / pre-save**：此时已有合成的 title/content 可比，准确率最高；代价是每个 dup 仍跡一次 LLM 调用（可接受——daemon 有 time-budget throttle，且 dedup 命中后锚点不再重试）。

### 组件

| 组件 | 位置 | 职责 |
|---|---|---|
| `DedupStore` | `jfox/gem_synth/dedup.py`（新文件） | 维护 `dedup_embeddings` 表：upsert/delete/query；query 返回 max 余弦对应的 note_id |
| `dedup_check` | `dedup.py` | `encode_single(content)` → query 表（note_type ∈ candidate/permanent，排除 archived）→ max ≥ threshold 返回 dup_of |
| `mark_duplicate` | `store.py::SynthesisLog` | synthesis_log 记 `status='duplicate'` + `dup_of` |
| `_check_duplicate` 调用 | `synthesizer.py::synthesize_anchor` | hook 点 |
| backfill 命令 | `cli.py` | `jfox gem-synth dedup-backfill` 一次性灌现有 candidate + permanent |

### 余弦计算

- <1k 向量 × 1024 维（~3MB），**numpy 暴力余弦**即可（微秒级），无需 ANN。
- embedding 经现有 `EmbeddingBackend.encode_single()` 获取（走 daemon，已在跑）。

### embedding 内容口径（避免元数据扭曲余弦）

- **新 candidate**：embed `llm_result["content"]`（干净合成正文，**不含** `_save_candidate_note` 后面追加的 `## 来源`/`## 置信度`/`## 参考的永久笔记` 元段落）。
- **backfill 现有 candidate**：从文件正文里**剥掉**上述 3 个元段落（按 `## 来源`/`## 参考的永久笔记`/`## 置信度` 标题截断）再 embed，与新 candidate 口径一致。
- **permanent**：embed 正文全文（permanent 无元段落问题）。
- 统一截断到前 ~2000 字（防超长正文 + 省 daemon 吞吐），与现有 `EmbeddingConfig.max_content_chars` 风格一致。

## 4. Schema 变动

### 4.1 `synthesis_log` 表（迁移）

现有 `status` 取值 `success` / `failed`，新增 **`duplicate`**；新增列 **`dup_of TEXT`**（被重复的 note_id）。

迁移沿用 `store.py::_maybe_migrate` 模式：`PRAGMA table_info` 查列，缺则 `ALTER TABLE … ADD COLUMN`，`duplicate column` 错误视为已迁移（幂等）。

### 4.2 新表 `dedup_embeddings`（同库）

```sql
CREATE TABLE IF NOT EXISTS dedup_embeddings (
    note_id      TEXT PRIMARY KEY,
    note_type    TEXT NOT NULL,        -- 'candidate' | 'permanent'
    content_hash TEXT NOT NULL,        -- 内容变更检测，变则重算 embedding
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    emb          BLOB NOT NULL         -- np.float32[1024].tobytes()
);
```

## 5. 同步事件（保持 dedup 库与笔记一致）

| 事件 | 动作 |
|---|---|
| candidate 存盘成功（synthesizer） | `upsert(note_id, "candidate", content)` |
| candidate → permanent（note.py::promote_note） | `update note_type='permanent'`（留在表里，事实仍占位） |
| candidate reject/archive | `delete(note_id)`（**让该事实可被重试合成**——reject 是针对本条质量，非事实本身） |
| permanent 手动新建/编辑 | 暂不自动入表（量小，靠 backfill 命令定期补） |

**注**：promote_note / reject 已是现成入口，在它们末尾各加一行 dedup 同步调用即可。

## 6. 配置（`GemSynthesisConfig`）

```python
dedup_enabled: bool = True
dedup_threshold: float = 0.88   # 同事实重复阈值（高）；link-suggest 的 0.6 是"相关"，dedup 要"同一"
```

- `dedup_threshold` 默认 0.88：实测逐字重复 ≈0.95+、同事实改写 0.88-0.95、仅相关 0.6-0.8。0.88 取改写下沿。
- 配置走 `~/.zk_config.json` 的 `gem_synthesis` 段，沿用现有 `_safe_int`/`_safe_float` 解析模式。

## 7. Backfill 命令

`jfox gem-synth dedup-backfill [--kb <name>]`

- 扫 `<kb>/notes/candidate/`（排除 archived/rejected）+ `<kb>/notes/permanent/` 全部 .md
- 对每条 `encode_single(content)` → upsert（content_hash 命中则跳过，省 daemon 调用）
- 幂等、可重跑；输出 `已灌入 N 条（candidate X / permanent Y）`
- 解决 702 存量 + 让新机制起步就有对比集

## 8. 可观测

`jfox gem-synth status` 的 `status_counts()` 现返回 `{success, failed}`，加 **`duplicate`** 计数，与 success/failed 并列展示。`status --failed` 不含 duplicate（已区分）。

## 9. 测试策略（快速单测，可自主跑）

- `tests/unit/test_dedup.py`（新）：
  - `dedup_check` 逐字重复 → 命中（mock encode_single 返回相同向量）
  - 高相似改写（cos=0.9）→ 命中；低相似相关（cos=0.5）→ 不命中
  - threshold 边界（0.88 上下）
  - archived/rejected candidate 不参与对比
- `tests/unit/test_synthesizer_dedup.py`（新）：
  - mock dedup_check 返回 dup_of → 不调 `_save_candidate_note`，调 `mark_duplicate`
  - dedup_check 返回 None → 走原存盘路径
- schema 迁移：旧 `synthesis_log`（无 dup_of 列）→ 迁移后含列，幂等
- **不**跑 embedding 真模型（mock backend），符合 CLAUDE.md「快速单测可自主跑」

集成/daemon 路径提供命令让用户手动验证（不自主跑全量）。

## 10. 实施顺序（writing-plans 会细化）

1. `dedup.py`：DedupStore + dedup_check（含 numpy 余弦 + mock-friendly）
2. `store.py`：加 `mark_duplicate` + schema 迁移（dup_of 列）
3. `synthesizer.py`：hook `_check_duplicate` + 存盘后 upsert
4. `note.py::promote_note` + reject/archive：同步 dedup 库
5. `global_config.py`：加 dedup_enabled / dedup_threshold
6. `cli.py`：`dedup-backfill` 命令 + status 展示 duplicate
7. 单测 + `uv run pytest tests/unit/test_dedup*.py -v`
8. 新分支 + PR（CR 走 zima 双 bot + CI 绿后合，见 [[Zima PR Monitor：标签驱动的 CR 监听循环]]）

## 11. 风险 / 回退

- **误判（假阳性）**：threshold 太高漏改写重复、太低误杀新知识。默认 0.88 + 可配置；初期可配 0.92 观察一段时间再降。
- **daemon 假设 embedding daemon 在跑**：dedup_check 若 daemon 不可用应**降级跳过 dedup**（log warning）而非阻塞合成——否则 dedup 故障会卡住整个合成循环。
- **回退**：`dedup_enabled=False` 完全关闭，回到原行为；dedup_embeddings 表可 drop，不影响其它。
