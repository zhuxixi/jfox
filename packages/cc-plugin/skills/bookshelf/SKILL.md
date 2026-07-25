---
name: bookshelf
description: |
  Use when the user wants to manage books on the jfox bookshelf—add a book
  (PDF + scan2book-extracted bundle), list books, view a book's metadata or a
  specific page, or remove a book. Triggers on "书架", "bookshelf", "加书",
  "导入书", "看书 page", "书 页", "manage books", "add book to shelf".
---

# JFox 书架（bookshelf）管理

把读过的好书作为**资产**管进知识库：存 PDF 原件 + scan2book 抽取的 bundle + 元数据。
纯文件管理——不进语义索引、不做搜索召回。书的「思想」进 KB 走引用笔记（另起 issue）。

## 1. 前置条件

- jfox 已安装（`jfox --version`）
- 一本书的文件夹，结构：
  ```
  <folder>/
    bundle/              # scan2book 产物（含 manifest.json + pages/pNNN.md + images/）
    original.pdf         # 原件（可选）
    meta.json            # 可选；不给则 jfox 从 bundle manifest 脚手架生成
  ```
- scan2book（如需自己抽 bundle）：需 GPU，在 GPU 机器上跑 `scan2book <pdf> --out <dir>`，
  再把产出的文件夹交给 `jfox bookshelf add`。jfox 本身**不调 scan2book、不需 GPU**。

## 2. 命令

| 命令 | 作用 |
|------|------|
| `jfox bookshelf add <folder> [--force] [--move]` | 加一本书进书架（默认复制原件） |
| `jfox bookshelf list` | 列书架上的书 |
| `jfox bookshelf show <slug> [--page N]` | 看元数据 / 指定页 md |
| `jfox bookshelf remove <slug> [--yes]` | 删一本书（不可逆） |

全部支持 `--kb <name>` 切换知识库、`--json` / `--format json` 结构化输出。

## 3. 何时翻书架

- 用户问某本书里的原话/表述 → `bookshelf show <slug> --page N`。
- 用户想把一本已抽取的书管起来 → `bookshelf add <folder>`。
- 想看书架上有什么 → `bookshelf list`。

## 4. 不做什么

- 不做 OCR（用 scan2book 产物）。
- 不做语义搜索召回（书页不进索引）。
- 不调 scan2book（GPU 依赖在 jfox 之外）。