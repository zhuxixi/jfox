# gem-synth dedup 命中时增量改写已有 candidate 设计（#309）

**日期**：2026-07-25
**目标 PR 分支**：`worktree-issue-309-dedup-incremental-merge`（main 受保护，新分支 + PR）
**关联 Issue**：#309
**前置**：PR #308（dedup 主干，已合）；本 PR 在 #308 的二值跳过基础上加「提取增量 → 补进已有 candidate」
**KB 依据**：memory `candidate-promote-backlog`（#309 短板登记）、`gem-synth-dedup-enable`

## 1. 问题

PR #308 给 gem-synth 加了存盘前去重：新 candidate 若与已有 candidate/permanent 余弦相似度 ≥0.88，**整条跳过不存盘**，记 `status=duplicate` + `dup_of`。

用户反馈：被判定「重复」的 candidate 往往是 **~80% 同一件事 + ~20% 真增量**（不同角度/补充/差异）。当前二值跳过把整条丢掉，那 20% 增量也丢了。

## 2. 目标 / 非目标

### 目标
- dedup 命中 **candidate** 时，按相似度分带决定是否花一次 LLM 提取增量；有实质增量则**补进那条已有 candidate 草稿**（in-place 追加），无实质增量维持跳过。
- 任何 LLM 失败 / 无 delta / 目标加载失败 → 一律回退当前跳过行为（`mark_duplicate`），不阻塞合成。
- 合并后重算目标 candidate 的 dedup embedding，保证后续查重口径不漂移。
- 新增 `merged` 记账状态，`gem-synth status` 可观测。

### 非目标（YAGNI / follow-up，本 PR 不做）
- **不处理 permanent**：命中 permanent 仍维持当前跳过（不动已审知识）。permanent 的「提案→待审」机制是独立大特性，开 follow-up issue 登记。
- **不建独立修订历史表**：审计靠追加进 candidate 正文的 `## 补充` 段（candidate 是草稿，L5 审阅可见），不引入新 schema。
- 不改 dedup 算法、`dedup_threshold` 默认值（0.88）、`_clean_candidate_content` 口径。
- 不暴露近逐字阈值为配置（模块常量 0.96，YAGNI）。
- 不做存量回填（已 `mark_duplicate` 的历史锚点不重新合并；只对新命中生效）。

## 3. 决策（与用户确认）

| 维度 | 决策 | 理由 |
|------|------|------|
| 范围 | 仅 candidate | 积压里 dedup 命中绝大多数是 candidate↔candidate（754 candidate vs ~65 permanent）；先吃大头价值，permanent 提案留 follow-up |
| 配置默认 | `dedup_merge_enabled = True` | #309 的目的就是增量合并，opt-in 会让多数用户继续损失增量；daemon 低频（30min/轮），多一次 LLM 成本可接受 |
| Delta 调用 | 相似度分带 | cosine ≥0.96 近逐字 → 跳过 delta 调用省成本；0.88–0.96 才调 LLM 提取增量 |

## 4. 设计

### 4.1 数据流（`synthesize_anchor` dedup 分支重写）

```
dedup_check(kb, content, threshold) → Optional[DedupHit]   # 现返回 note_id，改为返回 DedupHit
  None                          → 照常 _save_candidate_note（现行）
  hit:
    hit.note_type != "candidate"  → mark_duplicate, return None（permanent，scope 外，现行）
    hit.score >= 0.96             → mark_duplicate, return None（近逐字，省 LLM）
    cfg.dedup_merge_enabled=False → mark_duplicate, return None（现行）
    否则（candidate + 合并带 0.88–0.96）:
      existing = load_note_by_id(hit.note_id)
        existing is None / archived / type != CANDIDATE → mark_duplicate, return None（race：已被删/晋升）
      delta = extract_delta_with_llm(new=content, existing=_clean_candidate_content(existing.content), cfg, stop_event)
        delta is None              → mark_duplicate, return None（LLM 失败降级）
        delta["has_delta"] == False → mark_duplicate, return None（无实质增量）
        delta["has_delta"] == True  → _merge_delta_into_candidate(existing, delta, anchor, kb_name)
                                       成功 → log.mark_merged(fid, hit.note_id); return None
                                       失败 → mark_duplicate（降级）
```

**铁律**：合并路径上任何异常都回退 `mark_duplicate`，绝不抛穿 `synthesize_anchor`（与现有「失败即跳过」语义一致）。

### 4.2 模块改动

| 文件 | 改动 |
|------|------|
| `jfox/gem_synth/dedup.py` | 新增 `DedupHit` dataclass（`note_id/note_type/score`）；`dedup_check` 返回 `Optional[DedupHit]`；`DedupStore.all_embeddings` 多 select `note_type` |
| `jfox/gem_synth/llm.py` | 新增 `extract_delta_with_llm(new_content, existing_content, cfg, stop_event)` + `DELTA_SYSTEM_PROMPT`，复用 `_invoke_claude` / `_parse_json_lenient` |
| `jfox/gem_synth/synthesizer.py` | 重写 dedup 分支（4.1）；新增 `_merge_delta_into_candidate()` |
| `jfox/gem_synth/store.py` | `SynthesisLog.mark_merged(fid, target_id)` → status='merged' |
| `jfox/gem_synth/cli.py` | `gem-synth status` 显示 merged 计数；pending 扣除 merged |
| `jfox/global_config.py` | `GemSynthesisConfig.dedup_merge_enabled: bool = True` + `from_dict` |

### 4.3 关键组件契约

#### `DedupHit`（dedup.py，新）
```python
@dataclass
class DedupHit:
    note_id: str       # 命中的已有笔记 id
    note_type: str     # "candidate" | "permanent"（合成侧据此分流）
    score: float       # 余弦相似度（合成侧据此分带）
```
`dedup_check(kb, content, threshold=0.88) -> Optional[DedupHit]`：命中返回最相似那条的 DedupHit；降级/空/无命中返回 None。`all_embeddings` 返回值由 `[(note_id, emb)]` 改为 `[(note_id, note_type, emb)]`（仅 `dedup_check` 内部调用，无外部 caller）。

#### `extract_delta_with_llm`（llm.py，新）
- **签名**：`extract_delta_with_llm(new_content, existing_content, cfg, stop_event) -> Optional[Dict]`
- **输入**：`new_content`（已 H1-strip 的新 candidate 正文）、`existing_content`（已 `_clean_candidate_content` 剥元段的已有 candidate 正文）、`cfg`、`stop_event`
- **prompt 要点**：「已有笔记 X 与新候选 Y 讲同一件事。提取 Y 相对 X 的**有效增量**（新角度/补充事实/差异）。若无实质新增，`has_delta=false`。若 Y 与 X 矛盾，`conflict` 简述矛盾。」
- **输出 JSON**：`{"has_delta": bool, "delta": "markdown 增量正文（无增量则空串）", "conflict": "可选矛盾说明"}`；返回解析后的 dict（与 `synthesize_with_llm` 一致），失败返回 None
- **复用**：`_invoke_claude`（同样 `--allowed-tools ""` 禁工具、env 隔离、`_gem_synth_runs_dir` cwd）、`_parse_json_lenient`（容忍围栏/前导文本）。两层 JSON 解析（`--output-format json` 的 `result` 包装）。
- **失败**：任何异常 / 缺 `has_delta` 键 → 返回 None（调用方降级 `mark_duplicate`）。`stop_event` 透传给 `_invoke_claude`。

#### `_merge_delta_into_candidate`（synthesizer.py，新）
- **签名**：`_merge_delta_into_candidate(existing_note: Note, delta: Dict, anchor: Dict, kb: str) -> bool`
- 调用方（synthesize_anchor）已 load 并校验过 `existing_note`（非 None / 非 archived / type=CANDIDATE），本函数只负责追加 + 落盘 + 重算，不再 load：
```
delta_section = (
    f"\n\n## 补充（来自锚点 #{anchor['fragment_id']} @ {anchor['timestamp']}）\n"
    f"{delta.get('delta', '')}\n"
    + (f"\n> ⚠️ 矛盾：{delta.get('conflict')}\n" if delta.get('conflict') else "")
)
existing_note.content = _append_knowledge_section(existing_note.content, delta_section)  # 插 body 末尾、meta 之前（dedup.py）
update_note(existing_note, add_to_index=False)            # 落盘 + bump updated
upsert_dedup(kb, existing_note.id, "candidate", existing_note.content)   # 重算 embedding
return True
```
- `update_note` 复用现有原子写 + 按 title re-slug；`add_to_index=False`（与 `_persist_note` 一致，daemon 进程不触发向量/BM25 索引）。
- **重算 embedding 必须**：delta 段用 `_append_knowledge_section`（dedup.py）插在 body 末尾、元数据段落（## 来源/置信度）**之前**——`_clean_candidate_content` 从 ## 来源 截断，插在 meta 之前才能让 delta 留在 body 内 → content_hash 变 → `upsert_dedup` 重 embed。否则 delta 被剥、hash 不变、embedding 不重算（CR 发现：曾因此对后续查重失明 + 同一增量被相似锚点反复提取/追加）。喂给 delta LLM 的 existing_content 同口径，能看到已合并增量防重复提取。
- 整个函数包 try/except，异常 → return False（调用方 `mark_duplicate` 降级）。

#### `mark_merged`（store.py，新）
```python
def mark_merged(self, anchor_fragment_id: int, target_note_id: str) -> None:
    # INSERT OR REPLACE ... status='merged', candidate_note_id=target_note_id
```
`is_processed` 仍 True（行存在）→ 锚点不重试。与 `duplicate` 区分，供 status 单独统计。无需新列（复用现有 `candidate_note_id` + `status`）。

#### `gem-synth status`（cli.py，改）
- `status_counts()` 已 GROUP BY status，自然多出 `merged`。
- `pending = max(0, total - success - failed - duplicate - merged)`。
- table 输出加一行 `合并补入（merged）`。

#### 配置（global_config.py，改）
```python
dedup_merge_enabled: bool = True  # dedup 命中 candidate 时提取增量补入（#309）；False 回 #308 二值跳过
```
`from_dict`：`dedup_merge_enabled=bool(data.get("dedup_merge_enabled", True))`。无 `__post_init__` 守卫需求（纯 bool）。

## 5. 降级与边界（验收映射）

| 情况 | 行为 |
|------|------|
| daemon 不可用 / 空内容 / 表空 | `dedup_check` 返回 None → 照常存盘（现行，#308） |
| 命中 permanent | `mark_duplicate` 跳过（scope 外） |
| 命中 candidate 且 score ≥0.96 | `mark_duplicate` 跳过（近逐字省 LLM） |
| `dedup_merge_enabled=False` | `mark_duplicate` 跳过（现行） |
| `dedup_enabled=False` | 整条 dedup 关闭，不查重不合并（现行） |
| delta LLM 失败/超时/被中断 | 返回 None → `mark_duplicate` 跳过 |
| LLM 判无实质增量 | `mark_duplicate` 跳过 |
| 目标 candidate 已被删/归档/reject | load 失败/类型不符 → `mark_duplicate` 跳过 |
| 合并存盘失败 | `mark_duplicate` 跳过 |
| 有实质增量且目标正常 | `## 补充` 段插 body（meta 前）+ 重算 embedding + `mark_merged` |
| 合并目标后续被 reject/delete | `clear_duplicates_of` 连带释放 merged 锚点（与 duplicate 同），允许重合成——否则增量随目标永久丢失（silent data loss） |

## 6. 测试

| 文件 | 新增/改 |
|------|---------|
| `tests/unit/test_synthesizer_dedup.py` | 现有 mock 由返回 `"existing-id"` 改为 `DedupHit(...)`；新增：①candidate 合并带命中→调 delta LLM→补入+mark_merged ②permanent 命中→仍 mark_duplicate、不调 delta LLM ③score≥0.96→不调 delta LLM、mark_duplicate ④delta LLM 返回 None→降级 mark_duplicate ⑤has_delta=False→mark_duplicate ⑥`dedup_merge_enabled=False`→mark_duplicate、不调 delta LLM |
| `tests/unit/test_gem_synth_dedup.py` | `dedup_check` 返回 DedupHit（含 score+note_type）；near-verbatim 与合并带边界 |
| `tests/unit/test_gem_synth_llm.py` | `extract_delta_with_llm`：围栏/前导文本解析、缺 has_delta→None、两层 result 包装 |
| `tests/unit/test_gem_synth_store.py` | `mark_merged` 写入 status='merged' + candidate_note_id；is_processed=True |
| `tests/unit/test_gem_synth_config_dedup.py` | `dedup_merge_enabled` 默认 True + from_dict round-trip |

合并带测试用真实 `update_note` + tmp KB 落盘验证（追加段 + updated bump + embedding 重算），不 mock 存储层。

## 7. 文档同步（CR 必查）

dedup 行为变更（二值跳过→分带合并）+ 新 status 计数 + 新 config 字段，需 grep 同步：
- `CLAUDE.md`：gem_synth 模块说明（`gem_synth/` 行补 dedup 增量合并）
- cc-plugin / kimi-plugin skill 文档里描述 dedup 行为处（若有）
- 不改用户向 README（dedup 是内部机制，无用户 CLI 表面变化除 status 计数）

## 8. 风险

- **多一次 LLM 调用**：仅合并带（0.88–0.96）命中才付，近逐字与无 delta 都不付；daemon 低频。可 `dedup_merge_enabled=False` 关闭。
- **合并破坏目标 candidate 正文**：低风险（candidate 是草稿、pending 待审）；追加而非改写原文；冲突内联标注由人判。
- **embedding 重算漏掉**：spec 显式要求合并后 `upsert_dedup`，测试覆盖 content_hash 变化触发重 embed。
- **并发**：daemon 单进程串行处理锚点；`update_note` 原子写；dedup store 已有锁 + WAL + busy_timeout。
