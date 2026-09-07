# Spec: #482 全新 KB 首写 BM25 metadata 缺失的日志级别语义修正

状态：**draft（等用户确认）** · 2026-09-07 · repo: zhuxixi/jfox

## 背景与定位

#482 原主体（`--json 2>&1` 被 WARNING 污染）已被 #483 的 `logging.disable(logging.CRITICAL)`
顺带修复（实测确认）。本 spec 处理残余：全新 KB 首写是预期路径，但
`_read_disk_write_version()` 对不存在的 metadata 报 `WARNING + "Failed to read"`，
与 `_load()` 同毫秒发出的 `INFO "BM25 index not found, will create new index"` 语义矛盾。
影响面：人肉终端输出与 daemon auto-summary 日志的假告警噪声。定级 P3。

## 设计

单点改动：`jfox/bm25_index.py` `_read_disk_write_version()`（L239-246）按异常类型分流：

```python
def _read_disk_write_version(self) -> int:
    """读磁盘 metadata 的 write_version；损坏/缺失视为 0（异常留痕便于追踪）"""
    try:
        with open(self.metadata_path, "r", encoding="utf-8") as f:
            return int(json.load(f).get("write_version") or 0)
    except FileNotFoundError:
        # 全新 KB 首写是预期路径（_load() 同场景发 INFO），非异常——与先例对齐降级
        logger.info("BM25 metadata not found (fresh KB), write_version treated as 0")
        return 0
    except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Failed to read BM25 metadata write_version ({e}), treat as 0")
        return 0
```

要点：
- `FileNotFoundError` 是 `OSError` 子类，**必须前置单独捕获**，否则被宽分支吞掉
- 返回值与控制流零变化（两个分支都 `return 0`），三个调用点（`_save()` L353 /
  reload L397 / `check_stale_and_reload()` L942）行为不变 → #396 并发写语义零影响
- docstring 中"损坏/缺失视为 0"的留痕意图：对**真损坏**（JSON 截断、字段畸形、权限）
  保留 warning，只把"缺失"重分类为预期路径

## 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 新 KB 首写（metadata 不存在）不发 WARNING、发 INFO | 自动化验证（unit） | `uv run pytest tests/unit/test_bm25_fresh_kb_logging.py -v`（caplog 断言：无 "Failed to read" WARNING；有 fresh-KB INFO） | 测试通过 |
| A2 | metadata 损坏（JSON 截断 / write_version 畸形字段）WARNING 保留 | 自动化验证（unit） | 同上文件（caplog 断言：warning 含 "Failed to read"，返回 0） | 测试通过 |
| A3 | 现有 BM25 测试不回归 | 自动化验证（unit） | `uv run pytest tests/unit/test_bm25_concurrency.py tests/unit/test_bm25_batch.py -v` | 全部通过 |
| A4 | 端到端复现路径收敛（可选烟囱） | 自动化验证（integration） | 隔离环境 `ZK_KB_ROOT/ZK_CONFIG_PATH` 下新 KB 首条 add，stderr 无 "Failed to read BM25 metadata" | 输出无该行 |

A4 说明：issue 的原始复现路径是 CLI 端到端。单测已覆盖判定逻辑；A4 作为可选烟囱在
实现完成后本地跑一次（不进 CI，避免新增依赖 embedding 的集成测试标记负担）。若嫌
冗余可降级为"用户实测"或直接裁剪。

## 可测性拆分设计

`_read_disk_write_version()` 本身即独立方法（副作用 = 读文件 + 日志），测试不需要走
完整 `_save()` 流程：

- 测试夹具：`tmp_path` 构造 `index_dir` 文件状态——(a) 空目录（fresh KB）；(b)
  metadata 写入截断 JSON；(c) metadata 写入 `{"write_version": "abc"}`（int() 抛
  ValueError）
- 被测对象：`BM25Index(index_dir=tmp_path)` 后直接调 `a._read_disk_write_version()`
  （私有方法直调在该文件既有测试中已有先例，如 test_orphan_tmp_self_heal_branch_direct
  直达自愈分支）
- 断言：`caplog.at_level(logging.INFO, logger="jfox.bm25_index")` 下按场景断言
  records 的 levelname 与消息子串；返回值 == 0
- 测试边界：纯单元（文件系统 + caplog），不依赖 embedding / ChromaDB / filelock
  竞争——与 test_bm25_concurrency.py 的双实例并发测试完全隔离

## 非目标

- `--json` 输出纯净性（#483 已覆盖）
- `_read_pkl_write_version()` 同型 warning（仅孤儿 tmp 异常分支触发，首写不经过）
- `note_index.py:96` frontmatter 超限 warning（非首写路径，不同类）
- 原选项 2「连续 N 次缺失才告警」（复杂度不值）
- daemon 侧日志聚合/告警策略（如后续有需求另立 issue）

## 风险与缓解

| 风险 | 评估 |
|------|------|
| FileNotFoundError 分支掩盖真实配置错误（如 index_dir 指错路径） | 低：`_load()` 对同一状态已发 INFO；且错路径下 metadata 缺失与 fresh KB 不可区分，warning 也无判别力 |
| 未来有人在 fresh-KB 分支 return 0 之外加逻辑 | 低：注释已写明意图；CR 把关 |
| 改动极小被误扩 | spec 明确单点改动；plan 阶段 task 数量 ≤3 |
