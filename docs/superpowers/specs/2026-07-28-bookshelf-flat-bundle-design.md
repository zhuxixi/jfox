# Spec: bookshelf add 对齐 scan2book 扁平 bundle 契约（#349）

## 背景 & 根因（调研已确认）

`jfox bookshelf add <folder>` 写死找 `<folder>/bundle/manifest.json`（包装布局），但 scan2book v1 真实产出是**扁平** `<folder>/manifest.json`，故真实 bundle 跑不通。连带：`_find_original` 的「最大文件兜底」会把过程文件 `qa_review.html` 误当原件；整目录 `copytree` 把 `checkpoint.json / qa_*` 带进书架；CLI 无 `--original` flag 无法指 sibling PDF。

真实 bundle（已核实）：顶层 `manifest.json + pages/ + images/ + checkpoint.json + qa_report.json + qa_review.html`，无 `bundle/`、无 `original.pdf`；sibling PDF 文件名与 slug 不同。

## 目标

让 `add` 按契约消费扁平（同时向后兼容包装）布局，选择性复制、原件收紧、支持 `--original`。**目的地布局 `<kb>/bookshelf/<slug>/{meta.json, original.pdf, bundle/{manifest,pages,images}}` 不变；meta schema 不变；list/show/remove 不变。**

## 设计决策

### D1. 布局探测（包装优先，向后兼容）

新增 `_detect_bundle(src_folder) -> (bundle_src: Path, layout: str)`：

- `<folder>/bundle/manifest.json` 存在 → `(folder/bundle, "wrapped")`
- 否则 `<folder>/manifest.json` 存在 → `(folder, "flat")`
- 否则 → `InvalidBundleError`（消息点明两种期望路径）
- 包装优先：现有测试与已有 wrapped 用户零回归。

### D2. 选择性复制（白名单，跳过过程文件）

从 `bundle_src` 只复制进 `dest/bundle/`：

- `manifest.json`（始终）
- `pages/`（整个目录，存在才复制）
- `images/`（整个目录，存在才复制）
- **显式不复制**：`checkpoint.json`、`qa_report.json`、`qa_review.html`、任何 `original.*`
- 实现：删掉 `shutil.copytree(bundle_src, dest/bundle)`，改为逐项复制（manifest 用 `copy2`，pages/images 用 `copytree`，缺失跳过）。白名单语义 = 只有这几项进 bundle，其余自然丢弃。

### D3. `_find_original` 收紧（仅已知扩展名，去兜底）

- 仍扫 `src_folder.iterdir()` 顶层（包装布局原件是 bundle/ 的 sibling；扁平布局原件在顶层——两种都在 src_folder 顶层）。
- 候选 = 仅 `_KNOWN_ORIGINAL_EXTS` 内的普通文件、非软链。
- **无候选 → 返回 `(None, None)`**（删掉 `pool = known or files` 的最大文件兜底）。
- 有候选：按 `(-size, name)` 确定性选最大，算 sha256，返回 `(name, sha)`。
- 影响：`test_find_original_fallback_largest_when_no_known_ext` 旧语义（选 `a.bin`）→ 改新语义（返回 None）。

### D4. 新增 `--original <path>` flag（覆盖自动探测）

- `cli.py:add_cmd` 加 `original: Optional[str] = typer.Option(None, "--original", "-O", help="原件路径（PDF/EPUB…），覆盖自动探测；用于 scan2book 未把原件纳入 bundle 的情形")`。
- `store.py:add()` 加参数 `original: Optional[str] = None`。
- 解析逻辑（新增 `_resolve_original`）：
  - `original` 非空 → resolve；不存在 → `InvalidBundleError`；sha256 计算；返回 `(abs_path, basename, sha, external=True)`。
  - 否则 → `_find_original(src_folder)`；有则 `(src_folder/name, name, sha, external=False)`，无则 `(None, None, None, False)`。
- 复制：`original_src_path` → `stage/<basename>`（顶层，与 bundle/ 同级）。`meta.source.original_file = basename`、`original_sha256 = sha`。
- 命名保留 basename（与自动探测一致；用户想要 `original.pdf` 就给那个名）。

### D5. `--move` 在扁平布局下的删除

- 现状：`move` 删 `src_folder/bundle`（整目录）+ 原件。扁平无 `bundle/`。
- 新增 `_consumed_bundle_paths(bundle_src, layout)`：返回本次消费的源路径列表（manifest.json + pages/ + images/）。`move` 时逐个删（文件 unlink、目录 rmtree），而非整目录 rmtree——保守，不动 sibling 过程文件。
- 原件删除：删 `original_src_path`（无论 external 还是 src_folder 内）；若 `original_src_path` 在书架内则跳过（沿用 cc-1 思路，删原件=删新书）。

## 数据流

```
add(folder, slug?, move, force, original?)
 ├─ _detect_bundle(folder) → (bundle_src, layout)         [D1]
 ├─ load manifest (bundle_src/manifest.json) + 校验 dict
 ├─ slug = --slug or manifest.slug or folder.name
 ├─ _resolve_original(folder, original) → (src_path, name, sha, ext)  [D3/D4]
 ├─ build/normalize meta
 ├─ conflict check (--force)
 ├─ stage:
 │    ├─ manifest.json  → stage/bundle/manifest.json      [D2 白名单]
 │    ├─ pages/ (opt)   → stage/bundle/pages
 │    ├─ images/ (opt)  → stage/bundle/images
 │    ├─ original (opt) → stage/<name>                    [D4]
 │    └─ meta.save → stage/meta.json
 ├─ atomic stage→dest（沿用现有 stage/dest_bak 逻辑，不改）
 └─ move? → 删 _consumed_bundle_paths + original_src_path  [D5]
```

## 契约 / 不变量

- 目的地结构恒为 `<slug>/{meta.json, bundle/{manifest.json, pages/, images/}, <original?>}`。
- bundle/ 内**绝不**出现 `checkpoint.json / qa_*`。
- meta.source.original_* 反映**实际复制**的文件（覆盖用户 meta 值，沿用现有语义）。
- `original_file` 为空字符串 ⇔ 没复制任何原件（CLI 已有 ⚠️ 提示，沿用）。
- 软链原件一律不复制（cc-7，沿用）。

## 非目标

- 不改目的地布局 / meta schema / show / list / remove。
- 不校验 scan2book 过程文件内容（只是不复制）。
- 不批量迁移已有书架数据（本次只修 add 入口）。
- 不改 `read_bundle_manifest`（仍读 dest 的 `bundle/manifest.json`，目的地不变）。

## 测试计划

- 扁平布局 add（含过程文件）跑通；断言 dest `bundle/` 无 checkpoint/qa_*，pages/images 齐全。
- 扁平布局 + `--original` 指外部 PDF：原件入库、sha 非空、basename 正确。
- 扁平布局无原件且无 `--original`：`original_file=""`，CLI ⚠️ 提示，bundle 仍入库。
- `_find_original` 收紧：无已知扩展名 → None（改 `test_find_original_fallback_largest_when_no_known_ext`）；已知扩展名优先仍过。
- 包装布局回归：现有 wrapped 测试全过（向后兼容）。
- `--original` 指不存在路径 → `InvalidBundleError`。
- conftest `make_book_folder` 加 `layout="wrapped"|"flat"` 参数（默认 wrapped 不破坏旧测试），flat 模式造扁平结构 + 过程文件。

## 验收（= issue）

```
jfox bookshelf add /home/elling/ebooks/人类简史-从动物到上帝        # 跑通（自动探测无原件→--original 兜底）
jfox bookshelf add <folder> --original /home/elling/ebooks/人类简史\ 450.pdf
jfox bookshelf list                                                 # 列出
jfox bookshelf show 人类简史-从动物到上帝 --page 1
jfox bookshelf show 人类简史-从动物到上帝 --page 100
```

dest `~/.zettelkasten/<kb>/bookshelf/<slug>/{meta.json, original, bundle/{manifest,pages,images}}`，无 checkpoint/qa。

## 风险

- **改 `_find_original` 契约会破坏既有调用方语义**：grep 确认仅 bookshelf 内部用，无外部依赖（调研已查）。
- **扁平 move 删除范围**：保守只删消费项，文档注明不删 sibling 过程文件。
- **真实 bundle 验收依赖本机 ebooks 路径**：CI 用造的 flat fixture，本机手动跑真实 bundle 兜底。
