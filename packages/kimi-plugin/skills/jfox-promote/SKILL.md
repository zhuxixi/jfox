---
name: jfox-promote
description: Use when user wants to review/promote gem-synth candidate notes into permanent notes, or reject/archive inaccurate ones. 过审 L5 候选宝石，支持大积压的三模式过审（客观去重扫描 / 簇级 triage / 单条 A/B/C）+ 冗余维度 + 固化机械清理；也用于过审前监控 L3 合成进度与上游 fragments。Triggers on "过审 candidate", "过审宝石", "晋升候选笔记", "审阅候选宝石", "candidate 过审", "L5 晋升", "promote candidate", "review candidate", "broken candidate", "candidate 审核", "破损 candidate", "批量过审", "簇级去重", "dedup 扫描", "candidate 冗余", "合成进度", "碎片", "gem-synth status", "fragments".
---

# 过审 candidate（破损→完整，支持大积压）

把 L3 合成产出的 candidate（pending/flawed）过审，晋升为 permanent 或拒绝归档。
对应 #249 五层 Loop Engineering 的 L5 晋升层。#319 重写：逐条 A/B/C → **三模式过审**，应对 700+ 积压。

> 本技能复用 `/skill:jfox-manage` §4.1 的共享约定（`--kb` / `--content-file` / `--format json`）。

## 前置条件

确认当前知识库存在且 jfox CLI 可用：

```bash
jfox --version
jfox kb current --format json
```

若尚未初始化，先调用 `/skill:jfox-manage` 创建知识库。

## 监控 L3 合成

在 candidate 进入过审流程前，可先查看 L3 合成状态与上游碎片，确认是否有新的 candidate 产出或失败锚点。

### 查看合成状态

```bash
jfox gem-synth status --format json
```

关注字段（实际 JSON 输出）：

- `pending`：待 L3 合成的 anchor 数（≠ candidate 过审队列；合成完归零，过审积压看 candidates list）
- `success` / `failed` / `duplicate`：合成成功 / 失败 / 去重跳过数
- `total`：总数
- 失败锚点列表：`jfox gem-synth status --failed`（需要人工介入的 fragment 锚点）

### 查看碎片

Hook 采集的 session 碎片会进入 `fragments.db`，过审前可通过 fragments 命令了解候选宝石的上游上下文。

```bash
jfox fragments list --format json
jfox fragments show <fragment_id>
```

`fragments list` 可用于定位 candidate 可能来源的 session 主题；`fragments show` 可查看碎片原文、所属 session、采集时间等元信息。

### 何时使用

- 批量合成后先执行 `gem-synth status`，看 `pending`（待合成 anchor）/ `failed` 判断合成进度；过审积压量看 `jfox candidates list --status pending --format json`。
- 某条 candidate 内容存疑时，用 `fragments show` 追溯其来源 fragment，辅助判档。
- 发现 `failed_anchors` 时，可转由 `/skill:jfox-session-summary` 检查对应 session 是否已产生高质量 summary，再决定是否重新触发合成。

## 0. 何时用哪种模式（决策树）

先看 pending 积压量（注意 `jfox candidates list` 默认分页 50 是上限非真实数；真实数量直接扫目录）：

```bash
jfox candidates list --status pending --format json | jq '.candidates | length'   # 分页内（≤50）
ls "$(jfox kb current --format json | jq -r .path)/notes/candidate/" | wc -l  # 文件总数（含 rejected 软删除；纯 pending 看上行 jq）
```

- **大积压（pending > 50）** → **模式1**（客观去重扫描，砍精确/高重复）→ **模式2**（剩余簇级 triage）→ **模式3**（高价值/模糊单条）
- **小积压（≤ 50）** → 直接 **模式2 / 模式3**

> 经验：大积压的主要矛盾是**冗余**（被现有 permanent 覆盖），不是准确性。先用模式1 砍重复，再用模式2 砍冗余，最后模式3 精修真正值得晋升的。

## 1. 模式1：客观去重扫描（大积压第一步）

对存量 pending 做一次性 dedup 扫描，三档：

- **L1 content_hash 精确**（cleaning 后正文逐字节一致）：直接清，每组留 1，不用读
- **L2 cosine ≥ 0.95**：报簇（标题 + 分数 + 内容片段）给用户确认后清
- **L3 cosine 0.88–0.95**：很可能，读一眼确认；< 0.88 不标记

**临时脚本**（dry-run 默认，`--apply` 批量 reject keep-best）：

```python
# promote-skill 模式1：存量 candidate dedup 扫描（临时脚本，直读文件版）
# 待 jfox candidates dedup-scan 命令（follow-up）落地后替换
# 用法: python dedup_scan.py [--threshold 0.88] [--apply]（用 jfox 所在 python 或 uv run python）
# 实测：直读 notes/candidate/ 绕过 candidates list 的分页 50 + list 无 content 字段两个坑
import hashlib, re, sys, json, glob, os, subprocess
import numpy as np

META_RE = re.compile(r"\n## (来源|参考的永久笔记|置信度.*|可信度.*)\n")
LEADING_H1_RE = re.compile(r"\A\s*# .+\n*")

def parse_md(path):
    """读 candidate md → (id, title, status, body)。"""
    txt = open(path, encoding="utf-8", errors="replace").read()
    if not txt.startswith("---"):
        return None, None, None, txt
    end = txt.find("\n---", 3)
    if end < 0:
        return None, None, None, txt
    fm, body = txt[3:end], txt[end + 4:]
    cid = title = status = None
    for line in fm.splitlines():
        if line.startswith("id:"):
            cid = line.split(":", 1)[1].strip().strip("'\"")
        elif line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("'\"")
        elif line.startswith("status:"):
            status = line.split(":", 1)[1].strip().strip("'\"")
    return cid, title, status, body

def clean(content: str) -> str:
    """剥 candidate 元段落（覆盖 ## 置信度说明 / ## 可信度说明 变体）+ 首个 leading H1。"""
    m = META_RE.search("\n" + content)
    if m:
        content = content[: max(0, m.start() - 1)]
    content = LEADING_H1_RE.sub("", content, count=1)
    return content.strip()

def content_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

APPLY = "--apply" in sys.argv
try:
    THRESHOLD = float(sys.argv[sys.argv.index("--threshold") + 1]) if "--threshold" in sys.argv else 0.88
except (ValueError, IndexError):
    THRESHOLD = 0.88

# 1. 直读 pending candidate（用 kb current 的 path 字段，支持自定义 --path KB；绕过 candidates list 分页 + 无 content）
try:
    kb_info = json.loads(subprocess.check_output(
        ["jfox", "kb", "current", "--format", "json"], text=True))
    kb, cdir = kb_info["name"], os.path.join(kb_info["path"], "notes", "candidate")
except Exception as e:
    print(f"jfox kb current 失败({e})，无法定位 candidate 目录"); sys.exit(1)
cands = []
for path in sorted(glob.glob(os.path.join(cdir, "*.md"))):
    try:
        cid, title, status, body = parse_md(path)
    except (OSError, UnicodeDecodeError) as e:
        print(f"  跳过 {os.path.basename(path)}: {e}"); continue
    if status != "pending":
        continue
    cands.append((cid, title, clean(body)))
print(f"[{kb}] pending candidate: {len(cands)} 条")

# 2. L1 content_hash 精确分组
groups = {}
for cid, title, body in cands:
    groups.setdefault(content_hash(body), []).append((cid, title, body))
l1 = {h: v for h, v in groups.items() if len(v) > 1}
print(f"L1 精确重复: {sum(len(v) for v in l1.values())} 条 / {len(l1)} 簇")
for h, v in l1.items():
    keep, *rest = v
    print(f"  keep {keep[1]} ({keep[0]}); reject {[r[0] for r in rest]}")
    if APPLY:
        for r in rest:
            subprocess.run(["jfox", "candidates", "reject", r[0],
                            "--reason", f"L1 精确重复 of {keep[0]}"])

# 3. L2/L3 cosine（需 embedding daemon；不可用则降级只做 L1）
try:
    from jfox.embedding_backend import get_backend
    backend = get_backend()
    reps = [v[0] for v in groups.values()]  # 每组代表 (id, title, body)
    if len(reps) < 2:
        print("去重后代表 < 2 条，无 cosine 可算")
    else:
        embs = np.array([backend.encode_single(r[2]) for r in reps], dtype="float32")
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
        sims = (embs / norms) @ (embs / norms).T
        l2 = l3 = 0
        for i in range(len(reps)):
            for j in range(i + 1, len(reps)):
                s = float(sims[i, j])
                if s >= THRESHOLD:
                    if s >= 0.95:
                        l2 += 1
                        print(f"  [L2 {s:.3f}] {reps[i][1]} ↔ {reps[j][1]}\n      {reps[i][2][:60]} …")
                    else:
                        l3 += 1
                        if l3 <= 30:
                            print(f"  [L3 {s:.3f}] {reps[i][1]} ↔ {reps[j][1]}")
        print(f"L2 (cosine≥0.95): {l2} 对；L3 (0.88–0.95): {l3} 对")
except Exception as e:
    print(f"embedding daemon 不可用({e})，已降级只做 L1 content_hash")
```

> 批量 reject（> 40 条）建议后台跑（每条触发一次 chroma embedding，累积耗时）；`while read` 注意文件尾换行，否则漏最后一条。

## 2. 模式2：簇级 triage（非精确重复的簇）

对模式1 剩下的、或小积压的候选簇：

1. **每簇先查「是否已被现有 permanent 覆盖」**（冗余维度）：
   ```bash
   jfox search "<簇主题关键词>" --type permanent
   jfox suggest-links "<簇代表正文>" --format json   # 阈值可放宽 0.4–0.5
   ```
2. **已被覆盖** → keep-best（簇中 grounding 最实 / 信息最完整者）+ reject 其余
3. **未被覆盖** → promote-merge：簇内 candidate 改写合并成单条 permanent

## 3. 模式3：单条深度 triage（A/B/C，降为次要）

仅用于高价值单条或模式1 L3 模糊条：

- **档 A 准确（无实质错误）**：读 candidate + `grounded_by` permanent → 微调（清元段落 + 补链 + title）→ 展示改写后正文 + wiki-link 报告 → 用户确认 → 写回正文 → `jfox candidates promote <id>`
- **档 B 大部分对、局部有问题**：一次性列出待澄清问题 → 用户批量回答 → 据答改写（含 A 的微调 + 补链）→ 确认 → promote
- **档 C 整体不可信**：给依据（与哪条 permanent 冲突 / grounding 崩）→ 用户确认 → `jfox candidates reject <id> --reason "<原因>"`

## 4. 「冗余」verdict（跨模式维度，与 A/B/C 并列）

模式2 / 模式3 过审时，凡判定**「已被现有 permanent 覆盖」** → `verdict = 冗余`，处置 fold（折进现有 permanent）/ merge / reject。

**纪律**：promote 前强制查「是否已被现有 permanent 覆盖」，避免晋升冗余笔记污染知识库。

## 5. 机械清理标准流程（固化，别每批重写）

晋升前对 candidate 正文做标准 clean（frontmatter 字段 promote 自动清；正文用下面片段）：

```python
# promote-skill 晋升前机械清理（复用 _strip_leading_h1 / _clean_candidate_content 思路）
import re
META_RE = re.compile(r"\n## (来源|参考的永久笔记|置信度.*|可信度.*)\n")
LEADING_H1_RE = re.compile(r"\A\s*# .+\n*")

def clean_for_promote(content: str) -> str:
    # 1. 删元段落（截断到首个 marker，覆盖变体 ## 置信度说明 / ## 可信度说明）
    m = META_RE.search("\n" + content)
    if m:
        content = content[: max(0, m.start() - 1)]
    # 2. 剥首个 leading H1（title 重复，#320 残留）
    content = LEADING_H1_RE.sub("", content, count=1)
    # 3. 2+H1（剥首个后仍有行首 H1，LLM 用 H1 当分节）→ 降级 H2（人审确认）
    if re.search(r"(?m)^# ", content):
        content = re.sub(r"(?m)^# ", "## ", content)
    return content.strip()
# 写回：jfox edit <candidate_id> --content-file cleaned.md
```

清理四步：
1. **剥 frontmatter 字段**：promote 自动清 `status` / `gem_level` / `confidence` / `knowledge_type` / `reject_reason`（**保留** `source_fragments` / `grounded_by` 溯源）
2. **删元段落**：上面的 META_RE（覆盖 `## 置信度说明` / `## 可信度说明` 变体，补 dedup cleaning 现存缺陷）
3. **去双/多 H1**：剥首个 leading H1；若仍剩正文 H1（2+H1，LLM 用 H1 当分节）降级 H2 或人审
4. **修 exact-link**：wiki link 精确标题匹配（关联 #275）；`suggest-links` 补漏链

## 6. 已知坑（条条实踩）

- **wiki link 要精确标题**：`[[Boktionary]]`、`[[没爆就别修]]` 等短链会悬空；promote 时未解析链 warning + 跳过（不报上层）
- **`suggest-links` 常关键词误命中 / 漏语义邻居**（如版权 ↔ Boktionary 返回 < 0.6）→ 需手动按概念补链，不能只信它
- **confidence 是合成器自评、≠ 质量/冗余**：别按它排序或决定能否直接升（0.85 的簇里既有冗余又有 grounding 标错的）
- **reject = archive**：文件保留在 candidate/，`jfox unarchive` 可恢复——放心清
- **批量 reject（> ~40 条）须后台跑**：每条触发一次 chroma embedding（增量、非全量重建，但累积耗时）；`while read` 注意尾换行

## 7. 标准输出格式

每条过审结论按此格式给用户：

```
verdict: A(准确) | B(澄清) | C(不可信) | 冗余
证据: <与哪条 permanent 对照 / grounding 报告>
wiki-link 报告: <已有链验证 + suggest-links 推荐>
处置: promote <id> | reject <id> | merge <ids> | fold → <permanent id>
确认: <等用户 yes/no>
```

## 关键约束

- **promote 不改正文**：晋升前先 `jfox edit <candidate_id> --content-file cleaned.md` 写回清理 + 改写后正文，再 `jfox candidates promote <id>`（promote 只改 type / 移文件 / 回填 backlinks）
- **补链阈值 ≥ 0.6**（与 organize skill 一致）；模式1 / 改写场景 candidate 正文短，可放宽 0.4–0.5
- **用户始终有最终决定权**：agent 判档 + 给依据，用户可 override
- **溯源不丢**：promote 保留 `source_fragments` / `grounded_by`（剥的是正文 `## 来源` 段落，溯源信息已在 frontmatter）

## 命令参考

```bash
jfox candidates list --status pending --format json   # 列出待审 candidate（分页 50）
jfox candidates show <id> --format json               # 查看 candidate 详情
jfox candidates promote <id>                          # 晋升为 permanent
jfox candidates reject <id> --reason "<原因>"          # 拒绝并归档（软删除，可 unarchive）
jfox unarchive <id>                                   # 恢复被 reject/archive 的笔记
jfox show <id_or_title>                               # 查看 permanent 笔记全文（--format json 输出结构化字段）
jfox suggest-links "<正文>" --format json             # 推荐 [[wiki links]] 候选
jfox edit <candidate_id> --content-file updated.md    # 将改写后的正文写回 candidate
jfox search "<关键词>" --type permanent                # 查现有 permanent（模式2 冗余判定）
```

> 通用命令（`add` / `edit` / `delete` / `list` / `show`）以及 `--kb` / `--content-file` 用法详见 `/skill:jfox-manage` §4。

### 合成与碎片监控命令

```bash
jfox gem-synth status --format json          # 查看 L3 合成进度与失败锚点
jfox fragments list --format json            # 列出 Hook 采集的 session 碎片
jfox fragments show <fragment_id>             # 查看碎片详情（默认 JSON，无 flag）
```

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| 无 pending candidate | 告知用户当前没有需要过审的候选宝石 |
| 大积压（pending > 50） | 先走模式1 客观去重扫描，再模式2/3 |
| 模式1 embedding daemon 不可用 | 降级只做 L1 content_hash 精确去重 |
| `jfox suggest-links` 返回低匹配度（score < 0.6） | 跳过自动补链，改手动按概念补；改写场景可放宽阈值到 0.4–0.5 |
| candidate 对应的 grounded_by 笔记不存在 | 报告缺失，并基于 candidate 自身内容继续判断 |
| promote 时 wiki link 目标不存在 | warning + 跳过该链（不阻塞，关联 #275）；改写时手动修精确标题 |
| 用户拒绝 agent 的判档 | 按用户意图重新分流或终止 |

## 使用建议

- **定期过审**：建议每批 L3 合成完成后立即过审，避免 pending candidate 堆积。
- **大积压先模式1**：pending > 50 时先用模式1 客观去重砍掉精确/高重复，再簇级 triage——别逐条过。
- **大胆 reject**：整体不可信或已被现有 permanent 覆盖（冗余）的 candidate 不应强行晋升，拒绝并归档是对知识库质量的保护。
- **别按 confidence 排序**：confidence 是合成器自评、≠ 质量/冗余，按它挑条目是误导信号。
