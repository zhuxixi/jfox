# Issue #391 Spec：BM25 索引并发写损坏修复设计

> Draft 2026-08-16，v2（审核后修订）。调研见 `research/root-cause.md`，根因结论已评论到 issue（issuecomment-5303343120）。
> 本文件是设计草案，**未经用户确认不进入实现**。
> v2 变更：修正 reload 失败降级（原方案会写空索引）；写入顺序改为 pkl 先、metadata 后（commit point）；写入改原子替换；新增读路径 stale 检测；pending 重放合并优化；补两个测试用例与 rebuild 覆盖风险量化。

## 1. 背景与根因（摘要）

`bm25_index.pkl` 有两个写者：CLI 进程（短命，读盘→改→写回）与 jfox daemon 长进程（auto-summary 循环每写一条 session 笔记就 `save_note` → `add_document` → `_save()` 全量写回）。`BM25Index` 在 daemon 里是进程内单例，首次 load 后永不重新读盘；daemon 每次写回都把 CLI 侧的一切修改（包括全量 rebuild）覆盖回滚。

## 2. 修复目标

1. **根治旧快照覆盖**：任何进程写盘前，若发现磁盘上有别的进程写入的新状态，先合并再写（乐观并发控制）。
2. **防止写入交错**：pkl + metadata 的写操作串行化（文件锁）。
3. **防读损坏**：写盘用原子替换，读端永远只能读到完整文件。
4. **读路径不滞后**：daemon 侧搜索路径在构造引擎时自动刷新过期单例。
5. **可观测性**：`_save` 记录 doc_count 与写入版本变化日志（本次排查最缺的就是这条）。

## 3. 方案决策

| 候选 | 效果 | 成本 | 结论 |
|------|------|------|------|
| A. 乐观锁：写前比对磁盘版本，变了就 reload + 重放本地增量 | 根治回滚 | 中（BM25Index 单文件改动） | ✅ **采用（主修）** |
| B. 文件锁（filelock） | 写-写串行化 | 低 | ✅ **采用（配合 A）** |
| C. 原子替换写盘（tmp + os.replace） | 防读端读到半写文件 | 极低 | ✅ **采用（补强）** |
| D. 读路径 stale 检测（引擎构造时） | daemon 搜索不滞后 | 低 | ✅ **采用（补强）** |
| E. daemon 写路径手动 reset 单例 | 打补丁，只修 auto-summary 一条路径 | 低但脆弱 | ❌ 不采用（治标，其他 daemon 写路径仍会复发） |
| F. 单一写者：索引更新收口 daemon API | 架构级根治 | 大 | ❌ 非目标，列入后续方向 |

**选定：A + B + C + D + 日志。** filelock 已是 uv.lock 中的传递依赖（3.25.2），只需在 pyproject.toml 显式声明。

## 4. 设计细节

### 4.1 写入版本号（乐观锁令牌）

`bm25_metadata.json` 增加字段 `write_version`（int，初始 0，每次 `_save` 成功后 +1）。旧文件无此字段时视为 0，无需 pkl 格式变更。

### 4.2 BM25Index 新增状态

- `_loaded_write_version: int`——load 时记录的磁盘版本。
- `_pending_ops: List[PendingOp]`——自 load/save 以来本进程的增量操作日志，每项 `(op, note_id, content, note_type)`，`op ∈ {add, remove}`。`add_document` / `remove_document` 时记录（在内存修改的同时）。重放前按 note_id 合并：同一 id 只保留最后一个 op（`add_document` 对已存在 id 会先 remove 再 add，合并消除冗余）。
- `_dirty_full_rebuild: bool`——`rebuild_from_notes` 成功后置 True。rebuild 语义是「以我的快照为准」：save 时发现磁盘 stale 不做 merge，直接以当前内存全量覆盖并记 warning（pending 已含 rebuild 之后的本地增量，内存状态即最终状态）。

### 4.3 `_save()` 新流程

**任何一步失败都不写盘**——这是本次修订的铁律（原方案的「reload 失败继续写」会把 `_reset()` 清空后的空索引覆盖到磁盘，必须杜绝）。

```
1. 获取文件锁 FileLock(index_dir/"bm25_index.lock")，timeout=5s
2. 读磁盘 metadata，得到 disk_version（损坏/缺失视为 0，但标记 metadata_broken）
3. if disk_version > self._loaded_write_version 且非 dirty_full_rebuild:
       # 磁盘有别的进程写入的新状态 → 先合并
       reload_ok = 重新 _load()   # 拿到磁盘最新状态与版本
       if not reload_ok:
           释放锁；logger.error("磁盘版本较新但 reload 失败，放弃本次 save"); return False
       合并重放 _pending_ops（同 id 合并后按序 apply）
       logger.warning(f"BM25 merge: 磁盘版本 {disk_version} > 本地 {loaded}，重放 {len(ops)} 条本地操作后合并写入")
   else if disk_version < self._loaded_write_version:
       # 异常：磁盘比本地旧——仍按当前内存写，记 warning
4. 原子写 pkl：写 bm25_index.pkl.tmp → os.replace 到 bm25_index.pkl
5. 原子写 metadata（write_version = max(磁盘, 本地) + 1、doc_count）：
   写 bm25_metadata.json.tmp → os.replace
   ——写入顺序 pkl 先、metadata 后：metadata 的 write_version 是 commit point，
     「版本号上涨」一定意味着「pkl 已完整落盘」，崩溃窗口内最坏只是版本号没涨
     （等价于本次写未发生，下次 save 重试即可），不会出现版本号与数据错位。
6. 更新 _loaded_write_version、清空 _pending_ops / _dirty_full_rebuild
7. logger.info(f"Saved BM25 index: {len(doc_ids)} documents (write_version={v}, prev={prev})")
8. 释放锁（上下文退出）
```

锁与乐观检查顺序不可交换：先拿锁再读 disk_version，保证「读版本→重放→写盘」原子。

### 4.4 重放语义（冲突裁决）

- 同一 note_id 的 add/remove 冲突：重放按 pending 顺序（同 id 已合并），后操作覆盖前操作（last-writer-wins）。这是并发 CRUD 的最终一致语义，远好于现在「丢整个索引」。
- `rebuild_from_notes`：见 4.2，stale 时覆盖式写盘并记 warning。

### 4.5 读路径 stale 检测（补强 D）

`HybridSearchEngine.__init__` 中，`get_bm25_index()` 之后、needs_rebuild 检查之前，调 `bm25_index.check_stale_and_reload()`：

```python
def check_stale_and_reload(self) -> None:
    """轻量 stale 检查：磁盘 write_version 比内存新就 reload。
    用于长驻进程（daemon）的查询路径，避免搜索长期基于过期快照。"""
    try:
        读 metadata（小文件 IO）得 disk_version
        if disk_version > self._loaded_write_version:
            self._load()
    except Exception:
        pass  # 读失败不阻塞查询，用内存快照兜底
```

粒度设计：gem_synth grounding 每轮 tick 构造新 `HybridSearchEngine`（`grounding.py:26`），等于每轮自动刷新一次；CLI search 每次新进程本来就读最新盘。不做「每次 search 都检查」（频率过高、收益小）。

### 4.6 daemon 侧自动修复

无需改 auto_summary/gem_synth 代码——daemon 内存单例的下一次 `_save` 走 4.3 流程：检测到磁盘被 CLI 写过 → reload → 重放 daemon 自己的 pending（这轮 add 的 session）→ 合并写入。旧快照回滚被根治。

## 5. 降级策略

| 失败点 | 处理 |
|--------|------|
| 锁超时（5s） | **放弃本次 save，返回 False**，记 error。绝不在无锁时写盘。 |
| reload 失败（pkl 损坏/校验不过） | **中止 save，返回 False**，记 error。（原方案「继续写」会把 `_reset()` 清空后的空索引覆盖磁盘——已修正） |
| metadata 损坏/缺 write_version | disk_version 视为 0，走「磁盘较旧」分支；正常写盘顺带修复 metadata |
| 读路径 stale 检查失败 | 忽略，用内存快照兜底，不阻塞查询 |

## 6. 非目标（明确不做）

1. 向量库 collection 失效（daemon 旧 ChromaDB 句柄）——不同组件，另开 issue 处理。
2. 单一写者架构（索引更新收口 daemon API）。
3. 向量库孤儿清理（#387 已有增量 repair 立项）。
4. BM25 掉条数的自动告警/巡检（日志做好后人工可查，自动巡检另议）。

## 7. 测试策略

新增 `tests/unit/test_bm25_concurrency.py`（`BM25Index(index_dir=tmp)` 直接实例化两个实例模拟双进程，不走全局单例，无需 embedding/ChromaDB，属快速测试）：

1. **两实例交错写**：B.add+save → A.add+save → 重新 load 验证磁盘含 B 的条目（重放生效）。
2. **remove 重放**：A remove X 不 save，B add Y + save，A save → 磁盘含 Y 且不含 X。
3. **add/remove 冲突 last-writer-wins**：A 记录 remove X，B add X + save，A save → X 被移除。
4. **rebuild 覆盖语义**：A rebuild 后 B add+save，A save → 磁盘 = A 全量，B 的 add 被覆盖（文档化行为，断言 warning 日志）。
5. **write_version 递增**：连续 save 版本单调递增。
6. **锁超时**：mock 锁不可得 → save 返回 False 且**磁盘未被改动**。
7. **旧 metadata 兼容**：metadata.json 无 write_version 字段时 load/save 正常，save 后字段出现且从 1 开始。
8. **reload 失败不写盘**：构造磁盘版本较新但 pkl 损坏的场景 → save 返回 False 且磁盘保持原状。
9. **读路径 stale 检测**：B save 后，构造 HybridSearchEngine（或直调 check_stale_and_reload）→ A 实例自动拿到 B 的状态。

回归：现有 `tests/unit/test_bm25_batch.py` 及 search 相关测试全绿。

现场验证（修复发布后手动）：rebuild-bm25 → 观察 daemon 日志 24h 内 doc_count 不再被回滚；daemon 日志出现 merge 行即重放路径生效。

## 8. 风险

- **rebuild 覆盖窗口**：`rebuild-bm25`（秒级）执行期间 daemon 若 save，其增量会被 rebuild 覆盖丢失——丢失范围限定为「daemon 在 rebuild 窗口内处理的 0-N 条 session 的索引」，且 auto-summary ledger 已标记处理过、不会重试。概率低、影响小（单条 session 的 keyword 可搜性），文档化接受。
- **stale-replay（LWW 陈旧覆盖）窗口**：进程 save 失败后长期持有过期内存，其 pending 中记录的内容可能已陈旧于其他进程在此期间提交的同 id 更新——重放时 last-writer-wins 会以陈旧内容覆盖较新磁盘数据。这是乐观并发 CRUD 的固有取舍（与「丢整个索引」的现状相比严重度低一个量级），非数据损坏；需要严格一致时应走单写者架构（非目标）。
- **filelock 显式依赖**：宽松协议，已随 uv.lock 存在，风险低。
- **pending ops 内存占用**：一个进程生命周期内增量 ops 数量级为百级，每项含一段正文，可忽略。
- **行为变化面**：所有 `_save` 调用方都会走锁+版本检查；CLI 单进程场景 disk_version 通常 == loaded_version，走快路径，行为不变。
- **Windows CI**：filelock 跨平台；os.replace 在 Windows 对目标已存在文件行为正确（Python 3.3+ 语义），无平台特化代码。
