# Issue #401 Spec：PR #396 cc round-4 遗留修复设计

> 2026-08-20。来源：#396 合并前 20 分钟 cc bot Round-4 review 的 7 条 open issue（issue-20~26）。
> 前序：#391（根因）、#396（主修复，已合并）、本 issue（收尾加固）。

## 1. 背景

#396 的乐观并发控制（filelock + write_version + 增量重放 + tmp 孤儿信号）合并后，cc round-4 复审发现 7 条边界问题。本 spec 覆盖全部 7 条的修法。

## 2. 修复项与方案

### 2.1 clear() 改为原子写空快照（issue-20，真 bug）

**问题**：clear() 是唯一不持锁的共享状态变更入口——不取 `_mem_lock`（与 in-flight `_save` 交错丢重置）、不取 filelock（跨进程删除-复活竞态：daemon 旧单例下次 save 把清空前数据写回）、内存重置先于删文件（Windows unlink 失败留中间态）。

**方案**：clear() 不再删文件，改为**原子写空索引快照**（复用 `_save` 通道）：

```python
def clear(self) -> bool:
    """清空索引：写空快照并递增 write_version（纳入乐观锁体系）。

    相比删文件：其他进程后续 save 看到更高版本走 merge 采纳空索引，
    不会用旧内存复活已清空数据；无 unlink，无 Windows 占用中间态。
    """
    with self._mem_lock:
        self._reset()
        self._pending_ops.clear()
        self._dirty_full_rebuild = True  # 覆盖语义：clear 以本地空快照为准
        return self._save()
```

- `_dirty_full_rebuild=True` 使 stale 时走覆盖分支（clear 语义=清空一切，含别进程刚写的），记 warning。
- 调用方核对：CLI 无 BM25Index.clear 直接调用方（仅测试），语义变化安全。

### 2.2 孤儿自愈条件放宽（issue-24，真 bug）

**问题**：自愈分支仅在「index 与 metadata 双文件皆无」时才清理 tmp 继续；但「pkl 存在、metadata 缺失、tmp 残留」单边态（首次建索引崩溃 / clear 中途崩溃）会永久僵死：每次 save 进孤儿分支 → `_load()` 因 metadata 缺失恒 False → 不满足双文件皆无 → return False。

**方案**：自愈条件放宽为「**metadata 缺失即自愈**」（清理 tmp + 按内存状态写入；pkl 单边数据放弃，BM25 是派生缓存可 rebuild 恢复）：

```python
if not self._load():
    if not self.metadata_path.exists():
        logger.warning("BM25 孤儿 tmp 残留且 metadata 缺失，清理 tmp 后按内存状态写入")
        self._metadata_tmp_path.unlink(missing_ok=True)
    else:
        return False
```

### 2.3 孤儿 tmp 信号的只读路径消费闭环（issue-21）

**问题**：(a) 真孤儿残留期间 check_stale_and_reload 每次都全量 unpickle + rebuild（tmp 永不消失）；(b) 他进程正常 save 的写窗口期 tmp 短暂存在 → 读端假阳触发整轮 reload。

**方案**：读路径采纳孤儿后**持 filelock 完成 commit**（把写者未完成的 tmp→metadata 最后一步补上，tmp 被消费）：

```python
def _commit_orphan_tmp(self) -> None:
    """只读路径消费孤儿 tmp：持 filelock 确认无在途写者后，把 tmp 提升为正式 metadata。

    锁拿不到 = 在途写者活跃（窗口期假阳），跳过下次再试——绝不在无锁时删/replace tmp。
    """
    try:
        with FileLock(str(self.index_dir / self.LOCK_FILENAME), timeout=0):
            if self._metadata_tmp_path.exists():
                self._replace_with_retry(self._metadata_tmp_path, self.metadata_path)
                self._fsync_dir(self.index_dir)
                logger.info("BM25 孤儿 tmp 已由读路径提交（消费）")
    except Timeout:
        pass
```

check_stale_and_reload 在 reload 采纳后调用它。效果：真孤儿只触发一次全量 reload，之后 tmp 消失、检测归 False；窗口期假阳在拿锁时被双重检查拦掉（在途写者持锁 → Timeout → 跳过）。

### 2.4 测试修正（issue-25/26）

- `test_orphan_tmp_self_heal_branch_direct`：末条断言（tmp 不存在）无判别力——改用 caplog 断言「自愈分支的 warning 日志出现」+ save 成功。
- `test_orphan_tmp_residue_self_heals_without_clear`：docstring 改为实际行为（只读采纳 + filelock 内消费 tmp）；补断言 tmp 被消费。

### 2.5 注释同步（issue-22）

- `_save` docstring、batch docstring、测试 docstring 的「mtime 检测」改为 tmp 哨兵表述。
- `_disk_has_orphan_pkl` docstring 声明修正：tmp 写成功后 pkl 替换前中断同样残留 tmp（此时数据未落盘，保守 reload 幂等安全）；不写「精确零假阳」。

### 2.6 删死代码（issue-23）

删除 `_atomic_write_text`（全仓无调用方；`git grep` 验证）。

> **注**：§2/§4 中的代码块与用例清单为设计时快照，实现经 pi-cr 多轮复审持续演进
> （如 `_commit_orphan_tmp` 新增了 tmp 内容校验与 pkl 落盘检查两重防护、返回 bool、
> warning 文案按实际比较关系生成等）。**实现细节以代码为准**，spec 保留设计意图。

## 3. 非目标

- issue-6（写路径持锁阻塞查询）：已 acknowledged，不改。
- 向量库 collection 失效：另行立项。

## 4. 测试策略

新增/修正（tests/unit/test_bm25_concurrency.py）：

1. `test_clear_writes_empty_snapshot`：clear 后文件存在且为空索引、write_version 递增、他进程视角 merge 采纳不复活。
2. `test_orphan_metadata_missing_pkl_present_self_heals`：单边态（pkl 在、metadata 缺、tmp 残留）→ save 成功不僵死。
3. `test_orphan_tmp_consumed_by_read_path`：check_stale_and_reload 采纳孤儿后 tmp 被消费、metadata 提交。
4. 修正既有两条测试的断言/docstring（2.4）。

回归：test_bm25_concurrency.py + test_bm25_batch.py 全绿；`tests/unit/ -m "not embedding and not slow"` 全绿。

## 5. 风险

- clear() 语义变化（删文件 → 写空快照）：无 CLI 调用方，测试已适配；用户若依赖文件消失需 rebuild 后自行清理（文档化）。
- 读路径新增 filelock 短获取：Timeout 跳过，不阻塞查询。
