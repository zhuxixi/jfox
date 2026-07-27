# /release-all 统一发版编排 skill 设计

- Issue: #334
- 关联：#333（CHANGELOG 漂移 verify）—— 折进本 PR 一起实现
- 日期：2026-07-27
- 状态：spec draft（待用户 review）

## 1. 背景与目标

jfox 有三条**独立**发版轨道，skill 覆盖参差：

| 组件 | 现有 skill | helper | 版本源 | tag/Release |
|------|-----------|--------|--------|-------------|
| jfox CLI | `/release` | `release_helper.py` | `pyproject.toml` | ✅ tag `v*` + GitHub Release + PyPI |
| cc-plugin | `/release-cc-plugin` | `release_cc_plugin_helper.py` | `plugin.json`（三处原子 bump） | ❌ 合 main 即发布 |
| kimi-plugin | ❌ 无 | ❌ 无 | `kimi.plugin.json`（单一 version） | ❌ 合 main 即发布 |

「三组件一起发」的场景（如 2026-07-25 的 1.5.0 / 0.6.0 / 0.14.0 三连发）需要分别走三次流程；且并非每次三组件都有改动。

**目标**：新增 `/release-all` 编排 skill，一条命令检测三个组件各自是否有未发布改动，**自动跳过无改动者**，为有改动者批量建 PR，最后发 jfox GitHub Release。顺带补 kimi-plugin helper（+ 单 skill），让三轨道对称；并把 #333 的 verify 校验折进 `release_helper.py`，`/release` 与 `/release-all` 共用。

**非目标**：
- 不自动合并 PR（main 保护分支，用户手动合并）。
- 不统一三组件版本号（三条独立轨道，语义各自独立）。
- 不替换 `/release`、`/release-cc-plugin`（它们仍是单组件入口；`/release-all` 编排复用它们）。
- 不处理编排窗口内外部 PR 抢先合入（由 verify 在发 Release 前兜底，见 §6）。

## 2. 已确认的关键决策（澄清结论）

1. **#333 verify 折进本 PR**：给 `release_helper.py` 加 `verify` 子命令，`/release` Step 9 与 `/release-all` 的 jfox Release 段都调用它。一次同时关掉 #333 + #334。
2. **批量建 PR + 最后发 jfox Release**：detect 全部 → 展示合并计划 → 为每个有改动组件 bump + 建 PR → 用户依次合并全部 PR → 拉最新 main → verify → 建 jfox GitHub Release。交互最少。

## 3. 组件设计

### 3.1 `release_all_helper.py`（新增，`.claude/skills/release-all/`）

纯检测层，只做「detect」，不碰文件、不发版。发版动作复用各组件 helper。

**子命令 `detect`**（默认）：扫三组件，输出 JSON：

```json
{
  "components": [
    {
      "name": "jfox",
      "changed": true,
      "current_version": "1.5.0",
      "baseline": "v1.5.0",
      "commits": ["feat(backup): #338 ... (#339)", "feat(gem-synth): ... (#335)"],
      "suggested_bump": "minor",
      "suggested_version": "1.6.0"
    },
    {
      "name": "cc-plugin",
      "changed": true,
      "current_version": "0.6.0",
      "baseline": "9f8924d",
      "commits": ["docs(promote): ... (#342)"],
      "suggested_bump": "patch",
      "suggested_version": "0.6.1"
    },
    {
      "name": "kimi-plugin",
      "changed": false,
      "current_version": "0.14.0",
      "commits": [],
      "skip_reason": "自 0.14.0 以来无改动"
    }
  ],
  "any_changed": true
}
```

**逐组件检测逻辑**（baseline + commits 两步）：

| 组件 | baseline（上次发版基线） | commits（基线..HEAD） | changed 判定 |
|------|--------------------------|----------------------|--------------|
| jfox | `git describe --tags --abbrev=0 --match "v*"`（仓内仅 jfox 有 tag；`--match "v*"` 防御性过滤） | `git log <tag>..HEAD --format=%s`，滤掉含 "bump version" 的行 | 滤后非空 → changed |
| cc-plugin | `git log -S '"version": "<cur>"' --format=%H -- .claude-plugin/marketplace.json`（fallback：最后改 marketplace.json 的 commit），**镜像** `release_cc_plugin_helper.find_last_bump_commit` 同款逻辑（本脚本内实现，不跨目录 import） | `git log <baseline>..HEAD --oneline -- packages/cc-plugin/ .claude-plugin/marketplace.json` | 非空 → changed |
| kimi-plugin | `git log -S '"version": "<cur>"' --format=%H -- packages/kimi-plugin/kimi.plugin.json`（fallback 同上） | `git log <baseline>..HEAD --oneline -- packages/kimi-plugin/` | 非空 → changed |

**suggested_bump**：
- jfox：基线..HEAD 含 `^feat` → minor，否则 patch。
- cc / kimi：默认 patch（与 `/release-cc-plugin` 默认一致：「无新 skill/command → patch」）。是否升 minor 由用户在确认环节覆盖。

**依赖**：检测逻辑是「基线..HEAD 是否有功能性 commit」，约 10 行/组件，**本脚本内轻量实现**，不跨 skill 目录 import 各 helper（解耦；真正的 changelog 生成仍由各组件 helper 在 bump 时负责，避免「何谓功能 commit」两处定义漂移）。

**用法**：
```bash
uv run python .claude/skills/release-all/release_all_helper.py detect
```
退出码 0 正常；某组件检测异常时该组件 `changed=false` + `skip_reason` 带 error，不中断其他组件。

### 3.2 `release_kimi_plugin_helper.py` + `/release-kimi-plugin` skill（新增）

镜像 `release_cc_plugin_helper.py`，差异只在**单一 version 字段**（`packages/kimi-plugin/kimi.plugin.json` 的 `"version"`），最简单。

- `read_current_version`：读 `kimi.plugin.json` 的 `version`。
- `compute_new_version`：patch/minor/major 或 x.y.z，须 > current。
- `bump_version_files`：原子替换（`count == 1` 预校验 + 落盘失败回滚 + 写后断言 `assert_versions`），单文件单字段。
- `get_changelog`：`find_last_bump_commit`（`git log -S '"version": "<cur>"' -- packages/kimi-plugin/kimi.plugin.json`）..HEAD 触 `packages/kimi-plugin/` 的 oneline。
- 输出 JSON 同 cc helper 结构。
- `/release-kimi-plugin` SKILL.md：薄，镜像 `/release-cc-plugin`（前置校验 → dry-run → 确认 → bump → 分支 `chore/bump-kimi-plugin-<v>` → PR → 告知合并；不打 tag、不发 Release）。

**为什么顺带建单 skill**：让三轨道对称（都有 helper + 单 skill），`/release-all` 编排层无特判分支；用户也能单独发 kimi。属 issue「让三轨道都有 helper，编排层逻辑统一」的落地。

### 3.3 `verify` 子命令折进 `release_helper.py`（关 #333）

新增模式 `python release_helper.py verify`：

1. `last_tag = git describe --tags --abbrev=0`
2. 列 `last_tag..HEAD` 的 commit subject，过滤功能类（feat/fix/refactor/docs/perf，**排除** chore/bump/test），正则抽 `(#NNN)` 得「应有 PR 号集合 A」。
3. 解析 `CHANGELOG.md` **最新版本段**（第一个 `## [x.y.z]` 到下一个 `## [` 之间）所有 `(#NNN)`，得「已收录 PR 号集合 B」。
4. `missing = A - B`，`extra = B - A`。`missing` 非空 → 打印缺失条目，**退出码 1**；皆空 → 退出码 0。

接线：
- `/release` Step 9（`gh release create` 前）先跑 `verify`，非 0 即停。
- `/release-all` jfox Release 段同上。

> 说明：verify 只对 **jfox**（有 tag + Release + CHANGELOG）成立；cc/kimi 无 tag/Release/CHANGELOG，不校验。

### 3.4 `/release-all` SKILL.md（新增，`.claude/skills/release-all/`）

编排层，纯散文调度，发版动作委托各组件 helper。流程：

**Step 1 · 前置校验**（任一不符即停）：
```bash
git branch --show-current                            # 期望 main
git status --porcelain                               # 期望 空
git branch --list 'chore/bump-*'                     # 期望 空（三组件任一 bump 分支都不能存在）
gh pr list --state open --head "chore/bump-*"        # 期望 空
```

**Step 2 · 检测**：
```bash
uv run python .claude/skills/release-all/release_all_helper.py detect
```

**Step 3 · 展示合并计划 + 确认 bump 类型**：
向用户展示 detect 结果：
```
📦 Release-All 计划:
  jfox       1.5.0 → 1.6.0  (minor)   ✓ 有改动  [feat(backup)#339, feat(gem-synth)#335]
  cc-plugin  0.6.0 → 0.6.1  (patch)   ✓ 有改动  [docs(promote)#342]
  kimi-plugin 0.14.0                ✗ 无改动，跳过
```
- 若命令带参数（`/release-all minor`）→ 统一套用到所有 changed 组件。
- 否则逐组件确认 suggested_bump（用户可改 patch/minor/major 或指定 x.y.z）。
- 全部 changed=false → 打印「三组件均无未发布改动，无需发版」并结束。

**Step 4 · 逐组件 bump + 建 PR**（顺序 jfox → cc → kimi，仅 changed 者）：
对每个 changed 组件，执行其单组件 skill 的 bump+PR 段。detect 已算出 `suggested_version` 并经用户确认，故**跳过各单组件 skill 的 dry-run 预览步**，直接正式 bump → 分支 → commit → push → `gh pr create`：
- jfox → `release_helper.py <v>` → 分支 `chore/bump-version-<v>` → PR
- cc → `release_cc_plugin_helper.py <v>` → 分支 `chore/bump-cc-plugin-<v>` → PR
- kimi → `release_kimi_plugin_helper.py <v>` → 分支 `chore/bump-kimi-plugin-<v>` → PR

收集所有 PR URL。三组件文件不冲突，PR 可并存。

**Step 5 · 告知用户合并**：
```
已创建 N 个 bump PR：
  - jfox:       <URL>
  - cc-plugin:  <URL>
请依次合并后告知我，我将继续创建 jfox GitHub Release（cc/kimi 合 main 即生效，无需 Release）。
```
等待用户确认全部合并。

**Step 6 · 发 jfox Release**（仅当 jfox 在计划内）：
```bash
git checkout main && git pull origin main
uv run python .claude/skills/release/release_helper.py verify     # #333 兜底
# verify 退出码 0 才继续：
gh release create v<jfox_ver> --title "v<jfox_ver>" --notes "<changelog_preview>"
```
verify 非 0 → 打印 missing 条目，**停**，提示用户补 CHANGELOG 后重跑（不自动建 Release）。

cc/kimi 在计划内但无 Release 步骤。

**跳过提示**：detect 阶段 changed=false 的组件，全程打印一次「<组件> 自 <ver> 以来无改动，跳过」后不再出现。

## 4. 数据流

```
/release-all [bump]
  └─ release_all_helper.py detect ──→ {components: changed/skip + suggested_bump}
       └─ 用户确认计划
            └─ 逐组件（jfox→cc→kimi，仅 changed）：
                  各组件 helper <v> → 分支 → PR
            └─ [用户合并全部 PR]
            └─ git pull main → release_helper.py verify → gh release create v<jfox>
```

## 5. 错误处理与降级

| 场景 | 处理 |
|------|------|
| detect 某组件异常（无 tag / git log 失败） | 该组件 `changed=false` + `skip_reason`，继续其他组件，不中断 |
| 某组件 bump 中途失败 | 已建的早期组件 PR 保留（独立），报告失败组件、停；用户决定 |
| 用户只合并了部分 PR | Step 6 不执行；提示「还有 X 个 PR 未合并」，等齐再发 Release |
| verify 非 0（CHANGELOG 漂移） | **不建 Release**，打印 missing；用户补 CHANGELOG（开 docs(changelog) PR 合并）后重跑 verify + release |
| jfox 未改动、cc/kimi 改动 | 跳过 jfox 全段（无 Release），只 bump cc/kimi + 建 PR |
| 三组件均无改动 | detect 后直接结束，不发版 |

## 6. 测试

纯逻辑单元测试（无 embedding/ChromaDB），可自主跑（CLAUDE.md「快速单元测试」）：

- `release_all_helper.detect`：fixture git 仓（打 tag + 各目录造 commit）→ 断言 changed/skipped、suggested_bump、commits 列表。覆盖：全改/全不改/jfox 不改只发 plugin/检测异常降级。
- `release_kimi_plugin_helper`：bump 原子性（count≠1 报错不写）、compute_new_version 边界（降级/同号拒）、changelog 取基线..HEAD。
- `release_helper.verify`：CHANGELOG 顶段 PR 号 ⊇/≠ functional commits 的 `(#NNN)` → 退出码 0/1 + missing 输出正确。

放 `tests/unit/release/`（与现有 unit 测试组织一致）。

## 7. 改动清单

新增：
- `.claude/skills/release-all/SKILL.md`
- `.claude/skills/release-all/release_all_helper.py`
- `.claude/skills/release-kimi-plugin/SKILL.md`
- `.claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py`
- `tests/unit/release/test_release_all_helper.py`
- `tests/unit/release/test_release_kimi_plugin_helper.py`
- `tests/unit/release/test_release_helper_verify.py`

修改：
- `.claude/skills/release/release_helper.py`（加 `verify` 子命令；main 路由 `verify` 分支）
- `.claude/skills/release/SKILL.md`（Step 9 前插 verify 步骤）

文档（可选，CR 一致性）：
- `CLAUDE.md` 发版相关段落补 `/release-all`、`/release-kimi-plugin`、verify 说明（若 Zima CR 会查文档 drift 则同步）。

## 8. 与现有 skill 的关系

- `/release`、`/release-cc-plugin`：**不变其单组件职责**，只在 release SKILL 插 verify 步骤。
- `/release-kimi-plugin`：新增，与 cc 对称。
- `/release-all`：编排层，**委托**三组件 helper/skill，自身只做 detect + 调度 + skip + verify 串接。无特判分支（三组件统一 detect → bump → PR）。

## 9. 开放小决策（review 时可推翻）

- kimi 是否**也建单 skill** `/release-kimi-plugin`（当前方案：建，求对称），还是只建 helper 给 release-all 用？倾向建。
- jfox suggested_bump 默认「feat→minor 否则 patch」是否合理？还是统一默认 patch、一律要用户指定？倾向前者。
