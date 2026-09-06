---
name: promote
description: Use when user wants to review/promote candidate notes into permanent notes, or reject/archive inaccurate ones. 过审 L5 候选宝石，支持大积压的三模式过审（客观去重扫描 / 簇级 triage / 单条 A/B/C）+ 冗余维度 + 固化机械清理。Triggers on "过审 candidate", "过审宝石", "晋升候选笔记", "审阅候选宝石", "candidate 过审", "L5 晋升", "promote candidate", "review candidate", "broken candidate", "批量过审", "簇级去重", "dedup 扫描", "candidate 冗余".
---

# 过审 candidate（破损→完整，支持大积压）

本 skill 过审 candidate——一种「破损级」候选知识笔记，把它晋升为永久笔记（permanent），或拒绝归档（reject，软删除可恢复）。新 candidate 由 `jfox prompts judge`（#399 prompt 判断）生成，处于 pending 状态；过审是知识闭环（采集→判断→过审）的最后一环。存量 gem-synth 合成的 candidate（无 `source_prompts` 溯源字段）同样走本流程。

积压量大时先用客观去重砍重复（模式1），再簇级 triage（模式2），最后精修高价值单条（模式3）；小积压直接模式2/3。

> 历史背景：对应 #249 五层 Loop 的 L5 晋升层；#319 起改为三模式以应对大积压。下面不依赖这些编号也能读懂。

## 0. 何时用哪种模式（决策树）

先看 pending 积压量决定入口模式。这里的 pending 指 candidate 的过审状态（待审），数量上有个坑：`jfox candidates list` 默认分页 50 是上限、不是真实总数，返回 50 就说明是大积压；要看真实数量直接扫 candidate 目录。

```bash
jfox candidates list --status pending --format json | jq '.candidates | length'   # 分页内（≤50；返回 50 = 大积压）
ls "$(jfox kb current --format json | jq -r .path)/notes/candidate/" | wc -l  # 文件总数（含 rejected 软删除；纯 pending 看上行 jq）
```

- **大积压（pending > 50）**：依次走模式1（客观去重扫描，砍掉精确和高度相似两档）→ 模式2（对剩余的簇做 triage）→ 模式3（精修高价值或模糊的单条）。
- **小积压（≤ 50）**：跳过去重，直接走模式2 或模式3。

> 经验：大积压的主要矛盾是**冗余**——candidate 讲的东西已被现有 permanent 覆盖——而不是准确性。所以先用模式1 砍重复、再用模式2 砍冗余，最后才用模式3 精修真正值得晋升的条目。

## 1. 模式1：客观去重扫描（大积压第一步）

对存量 pending 做一次性的 dedup（去重）扫描，按相似度从高到低分三档处理：

- **精确去重**（清理后正文逐字节一致）：把清理过的正文算 content_hash（一段正文的字节级指纹），完全相同的归为一组，每组只保留一条、其余直接 reject（拒绝即软归档），无需逐条阅读。
- **高度相似**（cosine ≥ 0.95；cosine 是余弦相似度，衡量两段正文的语义接近度，越接近 1 越像）：很可能是重复，把同组的标题、分数、内容片段报给用户，确认后 reject。
- **中度相似**（cosine 在 0.88 到 0.95 之间，不含 0.95——0.95 归高度相似档）：可能是重复，读一眼正文确认；相似度低于 0.88 的不标记。

> 下面是扫描脚本（dry-run 默认，只报簇不删；加 `--apply` 才在精确去重档批量 reject、每组保留一条——脚本取文件名最早的那条。高度/中度相似档无论是否加 `--apply` 都只报簇，需你确认后再手动 reject）：

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

# 2. 精确去重：content_hash 分组
groups = {}
for cid, title, body in cands:
    groups.setdefault(content_hash(body), []).append((cid, title, body))
l1 = {h: v for h, v in groups.items() if len(v) > 1}
print(f"精确重复: {sum(len(v) for v in l1.values())} 条 / {len(l1)} 簇")
for h, v in l1.items():
    keep, *rest = v
    print(f"  keep {keep[1]} ({keep[0]}); reject {[r[0] for r in rest]}")
    if APPLY:
        for r in rest:
            subprocess.run(["jfox", "candidates", "reject", r[0],
                            "--reason", f"精确重复 of {keep[0]}"])

# 3. 高度/中度相似：cosine（需 embedding daemon；不可用则降级只做精确去重）
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
                        print(f"  [高度相似 {s:.3f}] {reps[i][1]} ↔ {reps[j][1]}\n      {reps[i][2][:60]} …")
                    else:
                        l3 += 1
                        if l3 <= 30:
                            print(f"  [中度相似 {s:.3f}] {reps[i][1]} ↔ {reps[j][1]}")
        print(f"高度相似 (cosine≥0.95): {l2} 对；中度相似 (0.88–0.95): {l3} 对")
except Exception as e:
    print(f"embedding daemon 不可用({e})，已降级只做精确去重 content_hash")
```

> 批量 reject（超过 40 条）建议放后台跑：每条 reject 都会触发一次 chroma embedding（虽然是增量、不是全量重建，但累积起来耗时）。另外用 `while read` 循环时注意文件尾要有换行，否则会漏掉最后一条。

## 2. 模式2：簇级 triage（处理非精确重复的簇）

模式1 砍掉精确和高度相似两档后，剩下的 candidate 会聚成若干主题簇（或小积压直接从这里开始）。对每个簇，先判断它讲的内容是否已被现有 permanent 覆盖（这就是「冗余」维度），再决定怎么处置：

1. **查是否已被现有 permanent 覆盖**：

   ```bash
   jfox search "<簇主题关键词>" --type permanent
   jfox suggest-links "<簇代表正文>" --format json   # 阈值可放宽到 0.4–0.5
   ```

2. **已被覆盖**：在簇里保留 grounding 最扎实、信息最完整的一条（keep-best），其余 reject。`grounding` 指 candidate 合成时依据的永久笔记，grounding 扎实意味着它的来源更可靠。
3. **未被覆盖**：把簇内多条 candidate 改写、合并成一条新的 permanent（promote-merge）。

## 3. 模式3：单条深度 triage（A/B/C 三档，降为次要）

模式3 只用于高价值的单条 candidate，或模式1 里「中度相似」那档拿不准的条目。对每条按准确性分 A/B/C 三档处理，三档结构一致：先判断准确性、再走对应改写或拒绝流程。

- **档 A（准确，无实质错误）**：先读 candidate 和它依据的永久笔记（frontmatter 里的 `grounded_by` 字段）；然后微调正文——清掉元段落、补上 `[[wiki link]]`、修正标题；把改写后的正文和 wiki-link 报告展示给用户，确认后写回正文，最后执行 `jfox candidates promote <id>` 晋升。
- **档 B（大部分对、局部有问题）**：先把所有需要澄清的问题一次性列出来，让用户批量回答；再据回答改写正文（包含档 A 的微调和补链），确认后 promote。
- **档 C（整体不可信）**：给出不可信的依据——和哪条 permanent 冲突、或 grounding（合成依据）崩了；用户确认后执行 `jfox candidates reject <id> --reason "<原因>"`。

## 4. 「冗余」verdict（与 A/B/C 并列的跨模式维度）

除了 A/B/C 三档准确性判断，还有一个跨模式的维度：无论在模式2 还是模式3，只要判定 candidate 讲的内容**已被现有 permanent 覆盖**，就标 `verdict = 冗余`。冗余条目的处置有三种：fold（折进现有 permanent，把增量信息补进去）、merge（多条合并）、reject（直接拒绝）。

**纪律**：promote 前强制查「是否已被现有 permanent 覆盖」，避免晋升冗余笔记污染知识库。

## 5. 机械清理标准流程（固化，不用每批重写）

晋升前要对 candidate 正文做一次标准清理：frontmatter 里的状态字段由 promote 命令自动清除，正文部分用下面的代码片段处理。

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
    # 3. 多 H1：剥掉首个 H1 后若正文仍有行首 H1（合成器把 H1 当分节用了），降级为 H2 或交人审
    if re.search(r"(?m)^# ", content):
        content = re.sub(r"(?m)^# ", "## ", content)
    return content.strip()
# 写回：jfox edit <candidate_id> --content-file cleaned.md
```

清理分四步（第一步清 frontmatter 由 promote 命令自动完成、不在脚本里；第二步删元段落、第三步处理多 H1 对应上面脚本的 `clean_for_promote`；第四步修 wiki link 单独做）：

1. **清 frontmatter 字段**：promote 命令会自动清掉 `status` / `gem_level` / `confidence` / `knowledge_type` / `reject_reason`；但 `source_fragments`（来源碎片）和 `grounded_by`（合成依据）这两个溯源字段会保留，以便晋升后仍能追溯 candidate 的来历。
2. **删元段落**：用脚本里的 META_RE 正则，截断掉 `## 来源` / `## 参考的永久笔记` / `## 置信度说明` / `## 可信度说明` 这类合成器附加的元信息段落。
3. **处理多 H1**：剥掉正文首个一级标题（leading H1，它和笔记标题重复）；如果剥掉后正文里仍有一级标题（说明合成器把 H1 当分节用了），把这些 H1 降级为 H2，或交人工确认。
4. **修 wiki link**：要求 wiki link 精确匹配目标笔记标题（短链如 `[[Boktionary]]` 会悬空，见 §6）；再用 `suggest-links` 补漏掉的链接。

## 6. 已知坑（条条实踩）

- **wiki link 必须精确标题**：`[[Boktionary]]`、`[[没爆就别修]]` 这种短链会悬空（找不到目标笔记）。promote 时遇到解析不了的链只会 warning 然后跳过，不会报上层错误，容易漏发现。
- **`suggest-links` 常误命中或漏邻居**：它容易按关键词误匹配，又漏掉语义相近的笔记（比如「版权」和「Boktionary」相似度返回不到 0.6）。所以不能只信它的结果，要手动按概念补链。
- **confidence 不等于质量或冗余**：confidence 是合成器给自己的自评置信度，和 candidate 准不准、是否冗余无关。别按 confidence 排序，也别因为它高就跳过审核直接晋升——0.85 的簇里照样既有冗余条目，也有 grounding 标错的。
- **reject 等于 archive（软删除）**：reject 后文件仍保留在 candidate/ 目录，用 `jfox unarchive` 可以恢复，所以可以放心清。
- **批量 reject 要放后台跑**：一次 reject 超过约 40 条时，每条都会触发一次 chroma embedding（虽然是增量、不是全量重建，但累积耗时），建议后台跑。用 `while read` 循环时注意文件尾要有换行，否则漏最后一条。

## 7. 标准输出格式

每条 candidate 过审后，按下面的固定格式把结论报给用户——一眼能看到判定结果、依据和处置动作，方便用户快速确认或 override：

```
verdict: A(准确) | B(澄清) | C(不可信) | 冗余
证据: <与哪条 permanent 对照 / grounding 报告>
wiki-link 报告: <已有链验证 + suggest-links 推荐>
处置: promote <id> | reject <id> | merge <ids> | fold → <permanent id>
确认: <等用户 yes/no>
```

## 关键约束

- **promote 命令本身不改正文**：晋升前要先用 `jfox edit <candidate_id> --content-file cleaned.md` 把清理、改写后的正文写回 candidate，再执行 `jfox candidates promote <id>`。promote 只负责改笔记类型、移动文件、回填 backlinks。
- **补链阈值默认 ≥ 0.6**（与 organize skill 一致）；在模式1 或改写场景，candidate 正文较短，可放宽到 0.4–0.5。
- **用户有最终决定权**：agent 负责判档和给依据，用户随时可以 override。
- **溯源信息不能丢**：promote 会保留 `source_fragments` 和 `grounded_by`；清理时剥掉的只是正文里的 `## 来源` 段落，完整的溯源信息已经在 frontmatter 里。
