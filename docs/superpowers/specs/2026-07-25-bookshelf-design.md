# `jfox bookshelf` 子命令设计（#325）

## 问题与背景

配套 [zhuxixi/scan2book](https://github.com/zhuxixi/scan2book)（扫描书 PDF 抽取工具，v0.1 已落地）。scan2book 把扫描书变成「书 bundle」：`<slug>/{manifest.json, pages/pNNN.md, images/pNNN.jpg, checkpoint.json}`。jfox 这边需要消费它：把读过、觉得好的书作为**资产**管进知识库，原件可追溯、可翻阅。

调研结论（详见 #325 评论）：

- scan2book v0.1 核心 bundle 契约**已冻结**：目录结构、`pages/pNNN.md`（3 位零填充）、`manifest.json = {slug, meta:{title}, page_count, pages:[{page, md, image, chars, has_image}]}`、CLI `scan2book <pdf> --out <dir>`。页 md 是纯 markdown、无 frontmatter、无图片引用。
- 未冻结（scan2book Phase 2 才有）：`meta` 字段（目前仅 `title`，author/publisher/year/isbn 待 P2）、TOC 目录、per-page QA 标记、页 md 结构化。
- scan2book 需 NVIDIA GPU；jfox 定位「纯 CPU 无 GPU」→ **jfox 只吃已产出的 bundle，绝不 import / 不子进程调 scan2book**。
- `#22`（OCR/PDF 提取）曾 wontfix，理由「不在 jfox 核心定位」→ 本方案 bookshelf 是**纯资产管理**，不做 OCR、不做裸页向量召回，与 `#22` 自洽。
- jfox 现有 chroma/bm25 索引对「外部对象」不友好（`search_engine` 用 `note.load_note_by_id` 水合命中、metadata 无 `source_type` 判别）。**本方案不进索引，整个难点跳过。**

## 目标（v1）

提供一个**纯文件/资产管理**的 `jfox bookshelf` 子命令，把好书原件管起来：

- `add` 吃一个自包含的书文件夹（PDF 原件 + scan2book bundle + 元数据），落进当前 KB 的书架。
- `list` / `show` / `remove` 对书架做只读浏览与删除。
- per-KB 隔离，沿用全仓 `--kb` / `--format json` 惯例。
- 极简 cc-plugin `bookshelf` skill，让 agent 知道何时翻书架。

## 非目标（v1 明确不做）

- ❌ 书页进 chroma / bm25 索引；`jfox search` 召回书页。
- ❌ `bookshelf search`（维护者明确 de-scope）。
- ❌ OCR（只吃 scan2book 产物）。
- ❌ TOC / 章节导航（scan2book Phase 2 才有）。
- ❌ 调 scan2book 子进程 / `--scan`（jfox 永不碰 GPU）。
- ❌ 书更新（slug 撞 → 拒；`--force` 覆盖重加）。
- ❌ distill / 引用笔记 —— 见「Follow-up」。

## 存储布局

per-KB，和 `notes/` 平级。所有整库扫描器（`Indexer.index_all`、`graph.py`、`note.load_note_by_id`、`kb_manager._get_kb_stats`）都从 `notes_dir` 起，bookshelf 天然不被扫到，零冲突。

```
~/.zettelkasten/<kb>/bookshelf/<slug>/
  meta.json            # jfox 自有元数据（wrap scan2book manifest）
  original.pdf         # 原件，保留原文件名亦可
  bundle/              # scan2book 产物，原样吃进来
    manifest.json
    pages/p001.md      # 3 位零填充
    images/p001.jpg
    checkpoint.json    # jfox 忽略（scan2book 断点续跑用）
```

- `<slug>` 来源优先级：`meta.json` 的 `slug` → 文件夹名 → `meta.title` 经 slugify。scan2book 的 slugify 规则（保留 CJK、ASCII 小写、非字母数字压缩为 `-`）与 jfox 现有 slugify 可能不同；**v1 以输入文件夹携带的 slug 为准，jfox 不重算**，避免与 scan2book 产物目录名不一致。
- KB 根路径取 `config.base_dir`（在 `with use_kb(kb):` 块内），bookshelf 根 = `config.base_dir / "bookshelf"`。

## meta.json schema（jfox 自有）

jfox 拥有此文件，**wrap** scan2book 的 `bundle/manifest.json` 而非改写它。好处：scan2book Phase 2 改 manifest 字段不波及 jfox；原件与产物的可追溯性集中在 jfox 侧。

```json
{
  "schema_version": 1,
  "slug": "人类简史-从动物到上帝",
  "title": "人类简史：从动物到上帝",
  "added_at": "2026-07-25T20:42:00+08:00",
  "source": {
    "original_file": "original.pdf",
    "original_sha256": "<原件 sha256>",
    "extractor": "scan2book",
    "extractor_version": "0.1",
    "bundle_dir": "bundle",
    "bundle_manifest": "bundle/manifest.json"
  },
  "book": {
    "page_count": 448,
    "pages_dir": "bundle/pages",
    "images_dir": "bundle/images",
    "meta": { "title": "人类简史：从动物到上帝" }
  },
  "tags": [],
  "distill": { "status": "none", "reference_notes": [] }
}
```

字段说明：

- `schema_version`：jfox meta 自身的 schema 版本，便于以后迁移。v1 = 1。
- `source`：原件与产物来源。`original_sha256` 给原件一个稳定指纹（同名不同书可区分、未来去重依据）。`extractor`/`extractor_version` 记录是 scan2book 还是别的工具产的（为将来别的提取工具留口）。
- `book.meta`：**透传** scan2book `manifest.json` 的 `meta` 字段。今天只有 `title`；Phase 2 scan2book 加 `author`/`isbn` 等会自动流过，jfox schema 不用改。
- `book.page_count` / `pages_dir` / `images_dir`：从 scan2book manifest 抽出来便于 `list`/`show` 直接用，不必每次去读 bundle manifest。
- `distill`：**预留**给 follow-up（distill→引用笔记）。v1 写入时恒为 `{"status": "none", "reference_notes": []}`，`list`/`show` 原样展示。

## 命令契约

全部走 `fragment/cli.py` 的 sub-app 模式，`--kb` / `--format json`（含 `--json` 快捷）沿用全仓惯例；`--format json` 下错误返回 `{"success": false, "error": "..."}`（参照 `gem_synth/cli.py:38-46`）。

### `jfox bookshelf add <folder> [--force] [--move] [--kb X] [--format json]`

输入文件夹需包含（二选一）：

- `bundle/`（scan2book 产物，含 `manifest.json`）+ 原件文件（pdf/epub 等；多个非 bundle 文件时取最大的一个，文件名记入 `source.original_file`）；或
- 上述 + 用户手写的 `meta.json`。

流程：

1. 读 `bundle/manifest.json` 抽 `title` / `page_count` / `meta`；确定 slug（见上「存储布局」）。
2. 校验目标 `bookshelf/<slug>/`：存在且无 `--force` → 报错拒（书不更新）；`--force` → 先整体删除旧目录再写入。
3. 默认**复制**文件夹内容到 `bookshelf/<slug>/`（保原件，安全）；`--move` 则移动（省盘，但原件离开原位）。
4. 计算原件 `sha256`，写/归一化 `meta.json`（输入有则校验 + 补缺字段 + 强制 `schema_version=1`、`added_at=now`、`distill.status="none"`；无则脚手架生成）。
5. 输出：`{slug, title, page_count, path}`。

边界 / 错误：

- 输入文件夹无 `bundle/manifest.json` → 报错（v1 要求 scan2book 产物，不自行 OCR）。
- 原件缺失 → 允许（只警告），但 `source.original_file`/`sha256` 留空。
- slug 含非法路径字符 → 报错。

### `jfox bookshelf list [--kb X] [--format json]`

扫 `bookshelf/*/meta.json`，输出每本书：`slug` / `title` / `page_count` / `added_at` / `distill.status`。table 默认，`--format json` 出数组。

### `jfox bookshelf show <slug> [--page N] [--kb X] [--format json]`

- 无 `--page`：输出该书 `meta.json`（结构化）+ 页清单（`bundle/manifest.json` 的 `pages[]` 摘要：页号 + chars + has_image）。
- `--page N`：输出 `bundle/pages/pNNN.md` 原文（N 按 3 位零填充定位文件）。页不存在 → 报错。
- 找不到书 → 报错 `exit(1)`。

### `jfox bookshelf remove <slug> [--yes] [--kb X] [--format json]`

- 无 `--yes` → 交互确认（书名 + 页数 + 提醒不可逆）。
- `--yes` 跳过确认。
- 删整个 `bookshelf/<slug>/` 目录。没进索引，无需撤索引。
- `--format json` 输出 `{slug, removed: true}`。

## 模块结构

镜像 `jfox/fragment/`（sub-app + 独立存储层）：

```
jfox/bookshelf/
  __init__.py        # 导出 bookshelf_app、BookShelf
  cli.py             # bookshelf_app = typer.Typer(name="bookshelf", no_args_is_help=True)
                     #   command: add / list / show / remove，各包 with use_kb(kb)
  store.py           # BookShelf: 文件夹 + meta.json 的 CRUD（list_books / get / add / remove）
  meta.py            # BookMeta dataclass + load / validate / normalize / from_bundle_manifest / to_json
```

接线（`jfox/cli.py` 现有 sub-app 区，约 L104-119）：

```python
from .bookshelf.cli import bookshelf_app  # noqa: E402
app.add_typer(bookshelf_app, name="bookshelf", help="管理好书书架：PDF + 抽取 bundle + 元数据")
```

**不需要** note 生命周期 hook：bookshelf 有自己的 add/remove 路径，与 note 变更解耦。

## 关键设计决策

1. **不进索引**：维护者明确不要向量/三路召回。书的思想进 KB 走「引用笔记」（follow-up），而非裸页召回。→ 规避 jfox 索引对外部对象的所有难点（source_type 判别、多态水合、backfill、id 防撞）。
2. **meta.json 由 jfox 拥有、wrap scan2book manifest**：两个工具的发版周期解耦；scan2book Phase 2 改 manifest 字段通过 `book.meta` 透传，jfox schema 不动。
3. **add 默认复制、`--move` 可选**：本地优先、KB 自包含更干净；大 PDF 复制费盘但有保原件的好处。`--link`（软链）留待以后按需加。
4. **slug 以输入为准、jfox 不重算**：与 scan2book 产物目录名保持一致，避免对不上。
5. **slug 撞默认拒**：书不更新（与 scan2book 「书不更新」立场一致）；`--force` 覆盖重加。
6. **v1 不调 scan2book**：彻底解耦 GPU。用户在 GPU 机器上跑 scan2book 产出 bundle，再把整个文件夹交给 `jfox bookshelf add`。

## 降级与边界

- scan2book Phase 2 字段（author/isbn/TOC/per-page QA）：`book.meta` 透传，有则 `show` 展示、无则不报错。v1 不依赖任何 Phase 2 字段。
- `meta.json` 缺失：`add` 从 `bundle/manifest.json` + 原件 hash 脚手架生成。
- 原件缺失：允许 add（警告），`source.original_*` 留空。
- `checkpoint.json`：jfox 永远忽略（复制时可保留不影响，但绝不读）。

## 多 KB

per-KB 独立书架 `~/.zettelkasten/<kb>/bookshelf/`。`--kb` 经 `use_kb(kb)` 切换，与现有命令一致。`bookshelf` 不进 `kb_manager` 的 KB 名保留集（`{"notes", ".zk", ".zk_config.json"}`），无冲突。

## cc-plugin skill

新增 `packages/cc-plugin/skills/bookshelf/SKILL.md`（极简）：

- 描述何时翻书架（用户问某本书、某概念想看原书表述、核对权威出处）。
- 指引 `jfox bookshelf list/show` 用法。
- v1 价值有限（无 distill/引用笔记时，agent 也就 list/show 读页）；真正发力待 follow-up 落地。先占位。

## 测试策略（快速单元测试为主，可自主跑）

- `meta.py`：`from_bundle_manifest` 抽取、`validate`/`normalize` 补缺字段、round-trip 序列化。纯逻辑，无 IO。
- `store.py`：用 `tmp_path` fixture 造假 KB + 假 bundle 目录，测 `add`（复制/移动/force 覆盖/slug 撞拒/无 manifest 报错）、`list`、`get`、`remove`。
- `cli.py`：用现有 `cli`/`cli_fast` fixture（mock embedding 无关，bookshelf 不碰索引）跑 `bookshelf add/list/show/remove` 的 happy path + `--format json` + 错误路径。
- 不需要 embedding / ChromaDB / GPU → 全部快速测试，CI fast job 可覆盖。

## Follow-up（独立 issue）

**distill → 引用笔记**：跑 LLM 任务把书里权威的关键思想/段落提炼成 JFox 的 reference 笔记（正经笔记，可搜可链可被 agent 引用）。是个 LLM 子系统，待定：粒度（整本/章节/页/用户框选）、prompt 策略、模型选型（`claude -p` / 本地）、手动一次性命令 vs 守护循环（参照 `gem_synth`/`auto_summary`）、引用笔记的表示（新 `NoteType` vs 复用 `literature`/`permanent` + citation frontmatter）。落地后回填 `meta.json` 的 `distill` 字段，cc-plugin skill 才真正发力。
