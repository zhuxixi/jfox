# Spec: CPU 默认模型切换 bge-small-zh-v1.5 + 存量索引平滑迁移（#442）

日期：2026-08-28 · 状态：待用户审核 · Issue: zhuxixi/jfox#442

## 1. 背景与问题

jfox 用户笔记以中文为主，但 CPU 默认 embedding 模型 `all-MiniLM-L6-v2` 是英文模型，中文语义检索质量差。切换为 `BAAI/bge-small-zh-v1.5`（中文优化，24M 参数，与 MiniLM 体量相当）。

切换的连带问题（调研结论，见 issue #442 调研评论）：

1. **维度不兼容**：MiniLM 384 维 → bge-small-zh 512 维，新旧向量空间无交集，必须全量重嵌（`index rebuild`，`reset_collection()` 路径已就位，先例 #161/#162）。
2. **现状静默失败**：维度不匹配时 `search()` 返回空结果无提示（`vector_store.py:184`）、`add_note()` 仅写日志（`vector_store.py:101`）。
3. **首次下载单源**：`EmbeddingBackend.load()` 不走 `ModelDownloader.ensure_cached()` 三级降级链（#374），换模型后所有 CPU 用户触发首次下载，失败 = daemon 直接退出。
4. **硬编码 384**：`daemon/process.py:443`、`daemon/client.py:28,43` 三处 fallback 值需更新。

## 2. 目标 / 非目标

**目标**

- G1 CPU 默认模型切换为 bge-small-zh-v1.5，维度默认值同步 512。
- G2 升级用户在 `jfox daemon restart`（及 `start`）后获得维度不匹配检测：扫描全部 KB → 警告 → 交互确认 → 直接执行逐库 rebuild。
- G3 `load()` 接入 ensure_cached() 三级降级链（顺手修 #374 核心），保证"换模型 → 首次下载 → daemon 能起来 → 检测提示能展示"链路完整。
- G4 `search` / `add` 入口对维度不匹配从静默升级为用户可见警告。

**非目标（YAGNI）**

- 不做自动后台 rebuild。
- 不做 collection metadata 记录模型名/维度（peek 检测已够用）。
- 不动 BM25、GPU 路径（bge-m3 / 1024 维）、`config.embedding_model` 显式指定逻辑。
- 不实现 #374 的全部建议（`_check_model_cache` 可加载性验证为可选，仅在顺手范围内统一缓存判定）。

## 3. 决策记录（用户已拍板）

| # | 决策 | 选择 |
|---|------|------|
| D1 | restart 检测提示形态 | 警告 + 交互确认（y → 逐库 rebuild） |
| D2 | #374 降级链修复归属 | 本 issue 顺手修（不等待 #374 单独修） |
| D3 | 检测 KB 范围 | 扫描全部 KB（GlobalConfigManager 列举） |
| D4 | search/add 兜底 | 加兜底警告，双层防护 |

## 4. 组件设计

### 4.1 模型切换本体

| 位置 | 改动 |
|------|------|
| `jfox/embedding_backend.py:14` | `_CPU_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"` |
| `jfox/embedding_backend.py:167` | `get_dimensions()` fallback `384` → `512`（注释同步更新） |
| `jfox/daemon/process.py:443` | `"dimension": health.get("dimension", 384)` → 默认 `512` |
| `jfox/daemon/client.py:28` | `self._dimension: int = 384` → `512` |
| `jfox/daemon/client.py:43` | `data.get("dimension", 384)` → `512` |

### 4.2 download 降级链接入（#374 核心）

`EmbeddingBackend.load()` 现行逻辑：`_get_local_model_path()` 未命中 → 直接 `SentenceTransformer(model_name)` 联网硬加载 → 失败抛异常 → daemon 退出。

改为：

```
_get_local_model_path() 命中 → 照旧本地加载
未命中 → ModelDownloader(model_name).ensure_cached()
    → True  → 从本地目录加载（ensure_cached 下载至 ~/.zettelkasten/.models/ 或 HF Hub 缓存，加载路径需兼容两者）
    → False → 抛原异常（daemon 退出，但已尽力三级降级）
```

加载路径兼容说明：`ensure_cached()` 成功可能落在 HF Hub 缓存（`_try_hf_hub_download`）或本地 `.models/` 目录（ModelScope/curl 降级）。`load()` 在 ensure_cached 成功后优先 `SentenceTransformer(model_name)`（此时 HF 缓存命中不再联网），若本地目录存在则用本地路径——实现时以实际 `_check_cached` 命中位置为准，保持与 `model download` 命令一致。

缓存判定统一：`daemon/process.py:_check_model_cache()` 与 `EmbeddingBackend._get_local_model_path()` 复用同一判定函数（ModelDownloader 侧提供），消除"预检说已缓存、加载时找不到"假阳性。此项若改动面超预期，允许降级为仅修 load() 主链（在 PR 中说明）。

### 4.3 restart/start 检测 + 交互引导（新模块）

新增 `jfox/embedding_migration.py`，公开两个函数：

```python
def check_dimension_mismatch() -> Optional[DimensionMismatchReport]
    # 调 daemon /health 拿 model_name + dimension（拿不到 → 返回 None，不阻塞）
    # GlobalConfigManager().list_knowledge_bases() 列全部 KB
    # 逐 KB: chromadb peek(limit=1) 取已有向量维度
    #   - collection.count() == 0 或 peek embeddings 为空 → 跳过（空库无不匹配）
    #   - 维度 ≠ health.dimension → 记入受影响列表
    # 全部匹配 → 返回 None

def prompt_migration(report: DimensionMismatchReport) -> None
    # Rich 警告输出 + typer.confirm 交互
    # y → 逐 KB 执行 rebuild（复用 Indexer.index_all + reset_collection 现行路径，Rich 进度条）
    # n / 非交互（非 tty）→ 仅保留警告输出
```

`DimensionMismatchReport`：`model_dimension: int`、`affected_kbs: List[str]`、`kb_dimensions: Dict[str, int]`。

**挂载点**（`cli.py` daemon 命令）：`action == "start"` 与 `action == "restart"` 的成功路径（`_print_daemon_status()` 之后）：

```python
report = check_dimension_mismatch()
if report:
    prompt_migration(report)
```

**检测实现的边界**：

- 只读 peek，不写不删，检测失败（单库 chroma 打不开等）跳过该库并在 debug log 记录，不中断整体。
- daemon health 无 dimension 字段或请求失败 → 返回 None（restart 本身已成功，不为检测阻塞用户）。
- rebuild 逐库执行时的 `--kb` 上下文：用 `use_kb(kb_name)` 包裹现有 rebuild 实现。

### 4.4 search / add 兜底警告

`jfox/vector_store.py`：

- **search()**：except 分支用与 `add_note` 相同的维度错误识别（`"dimension" in msg and "expecting" in msg` + 正则 `dimension of (\d+).*got (\d+)`）。识别为维度不匹配时，除 log 外将警告文本写入实例属性 `self.last_dimension_warning: Optional[str]`；`search_engine.py` / CLI `search` 命令在拿到空结果后检查该属性，非空则输出：
  `⚠ 索引维度(N)与当前 embedding 模型维度(M)不匹配，语义搜索不可用。请执行 jfox daemon restart 获取迁移引导，或 jfox index rebuild 重建索引。`
- **add_note()**：保留现有捕获与 return False，同样填充 `last_dimension_warning`；CLI `add` 命令在写入笔记成功后检查该属性并显示同款警告（笔记正常落盘，仅向量索引未更新——在警告中说明）。

实现取舍：不抛异常（add/search 调用链含 indexer/watcher/daemon 循环等多处，抛异常破坏面大）；用实例属性上浮警告是最小侵入方案。`search_engine.py` 混合搜索路径透传该警告（RRF 融合含向量路时）。

### 4.5 提示文案（restart 检测）

```
⚠ 检测到 embedding 模型已更换（索引维度 384 ≠ 当前模型 512）
  受影响知识库: default, work
  影响语义搜索（返回空结果）与新笔记向量索引。
是否现在重建索引？将逐库重新嵌入全部笔记 [y/N]:
```

## 5. 升级用户旅程（验收主线）

1. `uv tool upgrade jfox` → CPU 环境默认模型变为 bge-small-zh-v1.5。
2. `jfox daemon restart` → 首次加载触发 24MB 下载（HF 失败自动降级 ModelScope/curl）→ daemon 启动成功。
3. 检测扫全部 KB → 发现 default/work 索引 384 维 ≠ 模型 512 维 → 警告 + 确认。
4. 选 y → 逐库 rebuild（进度条），完成后语义搜索正常。
5. 选 n → 后续 search 空结果时 / add 笔记时收到兜底警告，随时可 `jfox index rebuild`。

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| daemon health 拿不到 dimension | 检测跳过（返回 None），restart 正常完成 |
| 单 KB chroma 目录损坏/peek 异常 | 跳过该库，debug log，其余库继续 |
| ensure_cached 三级全失败 | load() 抛异常，daemon 启动失败提示查看日志（与现状一致，但已穷尽降级） |
| rebuild 中途单笔记失败 | 沿用 index_all 现行行为（单条失败继续，计 failed） |
| 空库（count=0） | 不列入受影响 KB |
| 非交互环境（无 tty） | 跳过 confirm，仅输出警告文案 |

## 7. 测试计划

- **单元**（fast，无模型加载）：
  - `check_dimension_mismatch`：mock health（512）+ mock peek（384 / 512 / 空 / 异常库）四分支
  - `prompt_migration`：mock confirm y/n，验证 rebuild 触发/跳过；非 tty 分支
  - `load()` 降级链：mock 本地未命中 → 断言 ensure_cached 被调用、成功后从本地加载
  - `search/add_note` 兜底：mock 维度异常 → 断言 `last_dimension_warning` 非空
- **集成**（现有 CI fast 范围）：改 `_CPU_DEFAULT_MODEL` 后 `daemon restart` 输出含警告文案（mock embedding 512 维）
- **回归**：现有 `pytest -m "not embedding and not slow"` 全绿
- **手动验收**：真实环境完整跑一遍第 5 节旅程（含中文查询召回对比，issue 验证步骤 4-5）

## 8. 风险

| 风险 | 缓解 |
|------|------|
| bge-small-zh-v1.5 文件清单与 `_REQUIRED_FILES` 不匹配 | bge 系列含 tokenizer.json/config.json，预计兼容；实现首步先 `jfox model download BAAI/bge-small-zh-v1.5` 实测 |
| peek 对 3098 条实库的开销 | peek(limit=1) 只取一条，毫秒级，已实测（本机 1024 维读出正常） |
| `last_dimension_warning` 实例属性方案对并发/多调用者 | jfox CLI 单进程模型，无并发写冲突；daemon 循环不读该属性 |
| ensure_cached 落点（HF 缓存 vs .models/）与 load 加载路径不一致 | 4.2 节已说明加载顺序；实现时以 `_check_cached` 实际命中为准并在测试覆盖 |

## 9. 相关

- Issue #442（本 issue）、#374（降级链，本 spec 修其核心）、#161/#162（维度不匹配先例）、#387（增量 repair，非依赖但相关：rebuild 仅保留给切模型场景）
- 调研存档：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-442/research/dimension-migration.md`
