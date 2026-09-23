# Spec: #541 — `--content-file` 输入标准化（剥 H1 与通道统一）

- **Issue**: zhuxixi/jfox#541
- **日期**: 2026-09-23
- **状态**: draft（等待用户确认）
- **调研**: `research/root-cause-and-scope.md`

## 1. 根因（已实证）

jfox 的读写契约是「H1 由 jfox 生成，`Note.content` 不含 H1」：`to_markdown()` 拼盘时无条件写 `# {title}`，`from_markdown()` 读盘时无条件剥首个 H1。但写入侧的输入清洗 `_strip_frontmatter()`（cli.py:1874）把 H1 剥离嵌在 frontmatter 分支内，且 stdin 路径（`--content-file -`）完全不经过清洗。读写不对称导致回灌在两种输入 × 两种通道的组合下有三格静默损坏（调研矩阵：文件+.content_body 双 H1；stdin+.content 双 frontmatter；stdin+.content_body 双 H1）。

## 2. 目标行为（决策表）

标准化函数对 `--content-file`（文件与 stdin 同一语义）的输入按行处理：

| # | 输入形态 | 现行为 | 新行为 |
|---|---------|--------|--------|
| 1 | 纯正文（无 fm 无 H1） | 原样返回 | 原样返回（不变，精确 passthrough） |
| 2 | frontmatter + H1 + 正文 | 剥 fm + 剥 H1 | 不变 |
| 3 | frontmatter + 正文（无 H1） | 剥 fm | 不变 |
| 4 | H1 + 正文（无 fm） | **H1 保留 → 双 H1** | **剥 H1**（#541 主诉）。判断前**先吃掉开头空行**（与 from_markdown 的贪婪 `^# .+\n+` 口径对齐——否则漏剥的 H1 会在下一次读写循环中跨代传播） |
| 5 | BOM + 上述任一 | BOM 剥 | 不变 |
| 6 | 剥完一次后**开头仍是 H1**（连续双 H1，如损坏文件） | 静默保留 | **报错退出**：`输入内容开头存在多个 H1 标题行，疑似结构损坏的笔记（双 H1/嵌套笔记）。请手动删除多余的 H1 行，或用 --content 直传修复后的内容` |
| 7 | stdin 传上述任一形态 | **完全不清洗** | **与文件路径同一语义**（决策 D1） |
| 8 | 剥除后正文为空、原始输入非空（如误传单行 `# 标题`） | 静默清空正文（edit 无空值校验，review R1 实证 cli.py:1949 直接赋值） | **报错退出**：`剥除标题行后正文为空，请确认输入内容是否正确`。纯空输入仍原样放行（add 侧既有 `if not content` 校验兜底） |

**降级/逃生通道**：`--content`（直接传内容参数）不经过 `_read_content_file`、不做任何剥离——想让正文以井号空格开头的用户走这条路（spec 明确此为 escape hatch，文档化即可）。

## 3. 组件契约（可测性拆分）

```
_read_content_file(path_or_dash)   # IO 装配层：文件读/BOM/存在性校验；stdin 读入后同样走 normalize
  └─ _strip_frontmatter(raw) -> str        # 纯函数：①BOM 剥 ②fm 剥（如有）③吃开头空行+剥一个开头 H1（如有）④双 H1 校验 ⑤剥后为空校验
       └─ _strip_leading_h1(body) -> str   # 纯函数：吃掉开头空行后，至多剥掉一行 H1（^#[ \t]+\S），供 ③ 复用
```

- 两个纯函数均无 IO、无全局状态；单元测试直接喂字符串断言。
- 双 H1 校验在第 ④ 步：若 `re.match(r"^#[ \t]+\S", result)` 仍命中则 `raise ValueError`（文案含修复指引）；剥后为空校验在第 ⑤ 步：结果为空串且原始输入非空白则 `raise ValueError`。两者由 add/edit 的既有异常通道转为 CLI 错误（exit 1 + 中文报错；已核实 edit 命令 `except Exception → typer.Exit(1)`）。
- `_read_content_file` 变更仅一处：stdin 分支从 `return sys.stdin.read()` 改为 `return _strip_frontmatter(sys.stdin.read())`。
- 空串/纯空白输入：原样放行（纯空 passthrough；仅「剥后为空且原输入非空」才报错，见形态 8）。

## 4. 数据流（修复后）

```
jfox show --json ──jq──▶ /tmp/body.md ──▶ edit --content-file ──▶ _read_content_file
                                                                    ├─ 文件: read_text
                                                                    └─ stdin: sys.stdin.read
                                                                          ↓
                                                          _strip_frontmatter（统一清洗）
                                                                          ↓
                                                    n.content = 干净正文 → to_markdown() 拼盘
                                                    （1 fm 块 + 1 H1，结构恒定）
```

## 5. 设计决策（需用户拍板）

- **D0 文件格式不变（保留 to_markdown 生成的 H1）**：笔记文件的双重身份（数据库记录 + 给人看的独立 Markdown 文档）要求开头有标题行；元数据块的 title 是真身、H1 是渲染品，与 Hugo/Jekyll 同约定。去掉 H1 需全库存量迁移 + 永久双格式兼容，且只能消灭本 bug 的一半（stdin 双 frontmatter 与 H1 无关，输入清洗无论如何必须存在）。若要论证去 H1 化，另开格式演进 issue。输入标准化的定性：补齐「文件格式 ↔ 内部模型」转换器缺失的写盘输入侧（读盘侧 from_markdown 早已有），不是补救。
- **D1 stdin 统一**（推荐：做）。#200（05-06）当时明说 stdin 豁免并有测试锁死；但实机已证明该豁免正是 #451 双 frontmatter 的通道，且「传输方式不同语义不同」本身就是坑。统一后纯文本 stdin passthrough 行为不变（形态 1），仅对「长得像笔记文件」的 stdin 输入生效。需同步改写 `test_stdin_passthrough` 为新契约。
- **D2 双 H1 报错**（推荐：做）。即 issue 期望 2。只拦「开头连续双 H1」这一强损坏信号，不动正文中段的 H1。
- **D4 剥后为空报错**（review R1 新增，推荐：做）。edit 对 content 无空值校验（cli.py:1949），剥后空串会静默清空正文，与双 H1 同级静默数据丢失。仅拦「原输入非空、剥后为空」，纯空输入行为不变。
- **D3 `add` 标题派生行为变更**（跟随修复自动发生）：无 `--title` 时 `derive_note_title` 取正文前 50 字符，H1 被剥后标题从 `# 标题行` 变为首段文字——视为契约一致的改善，进验收但不额外补偿逻辑。

## 6. 非目标

- #470（edit 覆盖 links 不去重）— 同命令另一处问题，独立修
- #451 / #528（jfox-session-to-permanent skill 文档）— 修复后 skill 的 `sed '1{/^# /d;}'` 规避法可简化，但 skill 文档改动归 #451
- `--content` 直传路径不新增剥离（escape hatch）
- 正文中段的 H1 不动（只管开头）
- 存量双 H1 笔记的批量检测/修复不在本次范围（修复后此类笔记回灌会撞 D2 报错，报错文案已含修复指引；如需批量清理另开 issue）

## 7. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 形态 4：无 fm 的 H1 开头正文被剥（#541 主诉） | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py -k h1_only` | 新测试通过；剥后正文首行不再以井号空格开头 |
| A2 | 形态 1：纯正文精确 passthrough 不回归 | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py::TestReadContentFile::test_plain_content_unchanged` | 既有测试保持通过 |
| A3 | 形态 2/3/5：fm 路径与 BOM 行为不回归 | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py -k "frontmatter or bom"` | 既有测试保持通过 |
| A4 | 形态 6：开头连续双 H1 报错（fm/no-fm 两变体） | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py -k double_h1` | `pytest.raises(ValueError)`，报错文案含「多个 H1」与修复指引（删多余 H1 / 用 `--content`） |
| A9 | 形态 8：剥后为空报错；纯空输入放行 | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py -k empty` | 单行 `# 标题` 输入 `pytest.raises(ValueError)`；空串输入返回空串不报错 |
| A5 | D1：stdin 与文件同语义（fm/H1/纯文本三变体） | 自动化验证（unit） | `uv run pytest tests/unit/test_content_file.py -k stdin` | 改写后的 stdin 测试通过（fm 剥、H1 剥、纯文本不变） |
| A6 | 端到端回灌：issue 实验 B 场景结构完好 | 自动化验证（integration） | `uv run pytest tests/integration/test_edit_roundtrip.py`（新文件，temp_kb + cli fixture） | 回灌后文件恰好 1 个 fm 块（2 个 `---` 行）、1 个 H1 标题行，追加内容在正文中 |
| A7 | `add --content-file` H1 开头输入（D3 标题派生变更） | 自动化验证（integration） | 同 A6 文件内 `test_add_content_file_h1_title_derivation` | 落盘 1 fm + 1 H1；无 `--title` 时 title 来自剥后正文首段 |
| A8 | 静态检查与全量快速测试 | 自动化验证（static/build） | `uv run ruff check jfox/ tests/`、`uv run black --check jfox/cli.py tests/unit/test_content_file.py`、`uv run pytest -m "not embedding and not slow"` | 全部通过 |
| U1 | 真实知识库冒烟：session-to-permanent「补充已有笔记」流程 | 用户实测 | 修复合入后在真实 KB 取某笔记 `.content_body` 追加回灌一次，`grep -c '^---$'`=2、`grep -c '^# '`=1 | 结构完好；命中双 H1 报错时文案可理解 |

## 8. 测试边界小结

- 纯函数 `_strip_frontmatter` / `_strip_leading_h1`：字符串进出，7 形态全覆盖（unit 层，最低成本）
- IO 装配 `_read_content_file`：文件读 + stdin 分支（unit 层，monkeypatch sys.stdin 沿用既有测试模式）
- CLI 端到端：edit 回灌 / add 派生（integration 层，走真实临时 KB）
- 实现不得把剥 H1 逻辑重新内联进 `_read_content_file` 或调用方（保持纯函数边界）
