# Issue #407 Spec: index verify 改用 frontmatter 真实 ID 对账

> 状态：draft，待用户确认
> 路由：bug → systematic-debugging（根因已确认，Phase 1 完成）
> 关联：#103（上一代同类）、#387（repair 消费者）、#390（同方向）

## 1. 根因（已确认）

`Indexer.verify_index()` 用 `_extract_note_id_from_filename(f.stem)` 从文件名猜测 ID。
该函数（#237 修 #103 时引入）只支持 `18位-slug` 与 fleeting `8位-10位` 两种格式。
legacy `14位时间戳-6位微秒-slug` 格式（gem_synth synthesizer.py:188 生成 ID 的格式，连字符是 ID 一部分）解析失败 → 文件不计入 file_ids → 对应向量被误报 orphaned。

实测本机 default KB：candidate 1152 个文件全部 legacy 格式、permanent 49 个 legacy，即 1270 误报主体。

## 2. 修复设计

### 2.1 数据源替换（核心）

`verify_index()` 不再从文件名猜 ID，改为逐文件解析 frontmatter 取真实 `id`：

- 复用 `jfox/note_index.py::_parse_frontmatter_only(filepath)`（只读 frontmatter，不读正文，有 50k 行防御上限）。
- 遍历保持现状 `notes_dir.rglob("*.md")` 语义（覆盖四类目录全部 md）。
- 文件 → ID 映射按 frontmatter `id` 归一化 `str()` 后收集。

### 2.2 新返回结构（组件契约）

```python
{
    "total_files": int,            # 扫描到的 md 文件总数（含 unreadable）
    "valid_files": int,            # 有有效 frontmatter id 的文件数（含重复）
    "unique_ids": int,             # 去重后的文件 ID 数
    "total_indexed": int,          # 向量库 ID 数
    "unreadable_files": [str],     # frontmatter 读不了/无 id 的文件路径
    "duplicate_ids": [{ "id": str, "files": [str] }],  # 同 id 多文件
    "missing_from_index": [str],   # 文件有、向量库无（真缺失）
    "orphaned_in_index": [str],    # 向量库有、文件无（真孤儿）
    "healthy": bool,
    "checked": "vector_store",     # 明确标注验证对象
}
```

### 2.3 决策表

| 决策点 | 结论 | 理由 |
|---|---|---|
| ID 来源 | frontmatter `id` 字段 | 与 vector_store 写入路径（Note.id）同源，文件名格式无关 |
| 解析复用 | `_parse_frontmatter_only` | 已有实现含防御上限；NoteIndex.rebuild 同款解析，两套对账口径一致 |
| 不直接用 NoteIndex 单例 | 自己遍历 | 避免模块级缓存/NoteType 目录遍历语义耦合；verify 是独立读路径 |
| unreadable 归类 | 单独 `unreadable_files`，不混入 missing/orphan | issue 建议方向 2；repair 不应对其做修复动作 |
| duplicate 归类 | 单独 `duplicate_ids`，不混入 missing/orphan | 同 id 多文件时对账本身无差集，但文件层不一致需报告 |
| healthy 判定 | `missing==0 and orphaned==0` | 保持「向量对账健康」语义；unreadable/duplicate 属文件层问题，repair 修不了，混入会误导 repair 后的再验证 |
| 验证对象标注 | `checked: "vector_store"` + CLI 标题 "Vector Store Verification" | issue 建议方向 3；BM25 有独立 bm25-status 命令，不在本命令范围 |
| `_extract_note_id_from_filename` 去留 | 删除（无其他调用者）+ 删除/改写其专属单测 | 死代码不留；#390 spec 已明确不复用该函数 |

### 2.4 CLI 输出（cli.py verify 分支）

- 非 JSON：标题改为「Vector Store Verification」；增加 unreadable/duplicate 两行（有值才显示）；missing/orphaned 保持现有格式（取前 5）。
- JSON：直出 dict（结构见 2.2）。
- 说明行：提示 verify 不覆盖 BM25，BM25 状态见 `jfox index bm25-status`。

### 2.5 降级行为

- frontmatter 解析失败的单个文件：计入 unreadable_files，不中断整体 verify。
- notes_dir 不存在：保持现状返回 `{"error": ...}`。

## 3. 非目标

- 不修 duplicate 文件本身（文件层数据修复，另开 issue）。
- 不校验 BM25（有 bm25-status）。
- 不实现 repair（#387）。
- 不改 NoteIndex 及其单例缓存语义。
- 不迁移候选笔记文件名（存量 legacy 文件名保持，verify 已与文件名解耦）。

## 4. 测试计划

- 改写 `tests/unit/test_indexer_verify.py`：
  - legacy `14位-6位-slug` candidate 不误报（验收：candidate 不再 1152/1152 误报的单元形态）
  - unreadable frontmatter → unreadable_files（+ 真值仍对账正确）
  - duplicate id 两组场景 → duplicate_ids（同 slug 异文件 / 跨类型）
  - fleeting / session / 18位-slug 回归
  - missing / orphaned 真值判定
- 更新 `tests/test_advanced_features.py` 中 verify 相关断言（total_files 语义、healthy）。
- 保留不碰 embedding 模型：verify 测试用 mock_embedding_backend_for_vs fixture。

## 5. 验收标准映射（issue 原文）

| issue 验收 | 本 spec 对应 |
|---|---|
| 四种文件均以真实 note ID 对账 | 2.1 frontmatter id 数据源 |
| candidate 不再 1152/1152 误报 | 2.1 + 测试计划 legacy 用例 |
| missing/orphan 与 frontmatter 独立对账一致 | 2.1/2.2 结构（调研 R3 实测已证明一致性） |
| 输出清楚区分 vector/BM25 | 2.3 `checked` 字段 + 2.4 CLI 标注 |
| 回归测试（legacy/无法读取/重复 ID） | 4 测试计划 |

## 6. 风险

- 返回结构加键对既有消费者：rg 确认仅 cli.py + tests，无隐藏消费者。
- 性能：2934 文件实测秒级，保持「不碰模型」。
- `_parse_frontmatter_only` 的 yaml 异常面：函数自身 try/except 已覆盖（YAMLError/UnicodeDecodeError/OSError/AttributeError）。
- duplicate id 文件对向量库的映射：向量库该 id 只有一条（add_or_update_note 先删后加），对账差集正确，duplicate 仅作文件层报告。
