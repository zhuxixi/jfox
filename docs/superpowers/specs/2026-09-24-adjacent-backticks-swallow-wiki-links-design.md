# Issue #548 Spec：修复 `_strip_wiki_link_exclusions` 吞掉后续 wiki link

> 日期：2026-09-24 · 类型：bug · issue：#548 · 调研存档：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-548/research/`
> 修订：2026-09-24 v2 —— 按 spec review 发现 R1–R6 修订（见文末修订记录）

## 一句话设计

把 `_strip_wiki_link_exclusions`（`jfox/note_index.py:42`）的**三次顺序 `re.sub`** 改成**单次遍历的合并正则（alternation）**，让三类剔除区域在同一次扫描里原子匹配，已删除区域不再参与后续匹配。

## 根因（systematic-debugging Phase 1-3 已完成）

现状顺序剔除：
1. `re.sub(r"```[\s\S]*?```", "", text)` —— fenced code block
2. `re.sub(r"<!--[\s\S]*?-->", "", text)` —— HTML 注释
3. `re.sub(r"`[^`]+`", "", text)` —— inline code

第 2 步删掉被反引号包住的 HTML 注释（`` `<!-- -->` ``）后，两个反引号塌缩成**相邻空对** `` `` ``；第 3 步 `` `[^`]+` `` 在第一个反引号处匹配失败（下一字符是反引号），转而从**第二个**反引号起匹配，一路吃到文中再下一个反引号，把中间整段（含 wiki link）当行内代码删除。

已复现：输入 `页首标记 \`<!-- print p.X -->\` 说明\n\n见 [[笔记A]] 和 \`code\``，当前提取链接 `[]`，修法提取 `['笔记A']`。

## 设计

```python
# note_index.py 模块级

# 单次遍历剔除：alternation 顺序即优先级（fenced > HTML 注释 > inline code），
# 保证 `` `<!-- -->` `` 这类「反引号包注释」在首个反引号处被 inline 分支原子吃掉，
# 不产生相邻空反引号对。禁止拆回多次顺序 re.sub——顺序剔除会让已删除区域
# 造出新结构（#548：注释删除→空反引号对→inline 跨界吞链接）。
_EXCLUSION_RE = re.compile(
    r"```[\s\S]*?```"      # fenced code block
    r"|<!--[\s\S]*?-->"    # HTML 注释
    r"|`[^`]+`",           # inline code（反引号 span）
)

def _strip_wiki_link_exclusions(text: str) -> str:
    """移除不应参与 wiki-link 匹配的 Markdown 区域（fenced code block、HTML 注释、inline code）。

    单次遍历（见 _EXCLUSION_RE 注释）；轻量级处理，不保证解析所有 Markdown 边界情况。
    """
    return _EXCLUSION_RE.sub("", text)
```

**为什么有效**：单次遍历在每个位置按 alternation 顺序（fenced → HTML → inline）尝试。在 `` `<!-- -->` `` 的第一个反引号处，fenced 与 HTML 分支都因当前字符是反引号而失败，inline 分支把整段当行内代码**原子吃掉**——根本不产生空反引号对，后续文字不受影响。alternation 顺序同时保留了原代码「fenced 先于 inline」的意图（原注释「须最后处理，避免吃掉 fenced 边界」）。

**为什么不选备选方案**（issue 里也提了）：保留顺序剔除、第 2 步后折叠相邻空反引号对（`re.sub(r"``+", "", text)`）。它只堵住这一种塌缩形态，后续新增剔除规则时同类交接问题会复发；合并正则更彻底，且行为与现状在所有非 bug 用例上一致（已用对照用例验证，见「回归用例清单」）。

**注释是交付物的一部分（review R4）**：`_EXCLUSION_RE` 上方的注释解释了 alternation 顺序即优先级、以及为什么禁止拆回顺序剔除。没有这段注释，后续维护者很可能按直觉「简化」回多次 `re.sub`，复发同类 bug。

## 影响面（review R3 修订：准确版）

**fenced+HTML+inline 三合一剔除的实现只有 `note_index.py:42` 一处**，三个调用方都 import 它：

| 调用方 | 用途 |
|--------|------|
| `cli.py:373` | `resolve_wiki_links`（#511/#530 收敛的 add/edit/rebuild 三路径，含 frontmatter links 写入） |
| `note_index.py:262` | `find_notes_referencing_title`（backlinks 反查） |
| `note.py:507` | 笔记链接提取 |

**两处相邻实现，不受本 bug 影响、也不在本次改动范围**（review 时 grep 发现，修正调研阶段「全仓唯一实现」的过强表述——那只对函数成立，不对剔除逻辑成立）：

- `redirect.py:33-34,125-126`：自己的 `_FENCED_CODE_RE`/`_HTML_COMMENT_RE`，顺序 **blank（占位替换，非删除）**，且无 inline-code 步骤——不产生相邻塌缩，不受 #548 影响，无需改动。其注释「与 note_index 扫描口径保持一致」本就不完全成立（redirect 不剔 inline code），改完 note_index 后该口径差依旧存在，属独立话题。
- `graph.py:97`：第三 pass 对 **raw content** 提取链接、完全不剥离——口径与 note_index 相反，code fence 里的链接在图谱中会计成边。#548 触发的笔记在 graph 里其实**有**边，issue 里「图谱少边」的说法只对 backlinks/stored links 成立。

## 非目标

- **不捎带 #458**（含 `#` 标题被 `_normalize_wiki_link_title` 截断）、**#470**（edit 去重 + 同名歧义）——不同函数的独立 bug。
- **不处理 redirect.py / graph.py 的口径分歧**（见影响面；如需统一扫描口径，另开 issue）。
- **不引入完整 Markdown 解析器**——函数 docstring 声明的轻量口径不变，合并正则仍在该哲学内。
- **不做批量存量重存工具**——存量补救走 U1 的人工重存路径（见验收矩阵），不为此加 CLI 命令。

## 可测性拆分设计

`_strip_wiki_link_exclusions` 本来就是**纯函数**（`text -> str`，无副作用、无外部依赖），无需拆分。测试边界：

- **unit（A1/A2，主证明）**：直接对纯函数断言输出，无 mock、无 fixture，秒级。
- **integration（A3，症状层）**：经 `ZKCLI` 走 `add` 落库 → `show --json` 读 `links`，证明用户可观察症状（落库后 links 缺失、且不进 Unresolved 警告）消失。接线本身（#511）已有测试，此处只钉症状。
- **用户实测（U1，存量补救）**：`edit` 仅在 `content is not None` 时重算 links（`cli.py:1997-1999`），已污染的 frontmatter links **不会自愈**，需对受影响笔记重存一次。

## 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 反引号包 HTML 注释后，紧随的 wiki link 被保留 | 自动化验证（unit） | `uv run pytest tests/unit/test_wiki_link_resolution.py -k strip` | 「回归用例清单」① 触发用例通过 |
| A2 | 既有剥离行为不回归 | 自动化验证（unit） | `uv run pytest tests/unit/test_wiki_link_resolution.py` | 该文件既有用例 + 清单②–⑥对照用例全部通过 |
| A3 | 端到端：`add` 含触发内容的笔记后，`show --json` 的 `links` 含目标 | 自动化验证（integration） | 新增集成测试（ZKCLI add → show，复用既有 fixtures） | `links` 包含目标笔记 id；触发内容里的链接不静默丢失 |
| U1 | 存量受污染笔记的 links 恢复 | 用户实测 | 修复合入后，对 issue 中命中的那条笔记执行 `jfox edit <id> --content-file <原文件>`（或 `--content` 原文重存），再 `jfox show <id> --json` 核对 | `links` 条数恢复（该笔记应为 3），缺失的那条 backlink 重新出现 |

A3 为必做（review R1：验收矩阵与改动清单不允许「可选」矛盾）。U1 是操作项：修复本身无法自动定位哪条笔记被污染（依赖 issue 记录），故归用户实测。

## 回归用例清单（A1/A2 落到 `TestStripWikiLinkExclusions`）

| # | 用例 | 期望（修复后） | 防什么 |
|---|------|----------------|--------|
| ① | 触发用例：`页首标记 \`<!-- p -->\` 说明\n\n见 [[笔记A]] 和 \`code\`` | `[[笔记A]]` 存活 | #548 本体（A1） |
| ② | 触发变体·后文无更多反引号 | `[[笔记A]]` 存活（修复前也存活） | 防过修/行为漂移 |
| ③ | 两个「反引号包注释」夹住一个链接 | 链接存活 | 双塌缩形态（顺序版此形态也丢链） |
| ④ | fenced block 内含 HTML 注释与链接 | 块内链接不提取，块外链接提取 | fenced 优先级不变 |
| ⑤ | inline code 内的 `[[...]]` | 不提取 | inline 剥离不变 |
| ⑥ | HTML 注释内含反引号 | 注释整体剔除、注释外链接存活 | 分支优先级不变 |

复现脚本已验证 ①–⑥ 在修复版下全部正确、在现状版下仅 ①③ 有差异（即仅 bug 形态被修）。

## 改动文件

- `jfox/note_index.py`：`_strip_wiki_link_exclusions` 改为合并正则；新增模块级 `_EXCLUSION_RE`（含解释性注释，见设计节）。
- `tests/unit/test_wiki_link_resolution.py`：`TestStripWikiLinkExclusions` 增用例①–⑥（A1/A2）。
- `tests/integration/`（A3 必做）：新增或扩展一个 add→show 集成用例。

## 修订记录

- v2（2026-09-24，spec review 后）：
  - R1：A3 从「（可选）」改为必做，矩阵与改动清单一致。
  - R2：新增 U1 存量补救（`edit` 重存触发 links 重算）。
  - R3：影响面改写——「唯一实现」收窄为「三合一剔除唯一实现」，补 redirect.py（顺序 blank，不受影响）与 graph.py（不剥离，口径相反）两处事实。
  - R4：设计节明确注释为交付物，给出注释内容。
  - R5：钉死回归用例清单①–⑥。
  - R6：非目标补三条（redirect/graph 口径分歧、不引 Markdown 解析器、不做批量重存工具）。
