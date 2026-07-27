---
name: release-all
description: Release all three components (jfox CLI + cc-plugin + kimi-plugin) in one command. Detects per-component changes since last release, skips unchanged ones, batches bump PRs, then creates the jfox GitHub Release last (with CHANGELOG verify). Triggers on "全发", "release all", "三件套发版", "一起发版".
---

# Release-All Skill

一条命令编排三条独立发版轨道：jfox CLI → cc-plugin → kimi-plugin。自动检测各组件自上次发版以来的改动，**跳过无改动者**；为有改动者批量建 bump PR；用户合并后，最后发 jfox GitHub Release（带 #333 verify 校验）。

⚠️ 三组件版本轨道独立、语义各自不同。本 skill 不统一版本号，只统一编排。
要单独发某一组件，用 `/release`、`/release-cc-plugin`、`/release-kimi-plugin`。

## 用法

```
/release-all              # 逐组件确认 suggested_bump
/release-all minor        # 统一指定 bump 类型（套用到所有 changed 组件）
/release-all patch
```

## 编排模型

**批量建 PR + 最后发 jfox Release**：detect 全部 → 展示计划 → 为每个 changed 组件 bump+建 PR → 用户依次合并全部 PR → 拉最新 main → verify → 建 jfox GitHub Release。

## 执行流程

### Step 1: 前置校验（任一不符即停）

```bash
git branch --show-current                       # 期望 main
git status --porcelain                          # 期望 空
git branch --list 'chore/bump-*'                # 期望 空（三组件任一 bump 分支都不能存在）
gh pr list --state open --head "chore/bump-*"   # 期望 空
```

### Step 2: 检测

```bash
uv run python .claude/skills/release-all/release_all_helper.py detect
```

### Step 3: 展示合并计划 + 确认 bump 类型

展示 detect 结果：

```
📦 Release-All 计划:
  jfox        1.5.0 → 1.6.0 (minor)  ✓ 有改动  [feat(backup)#339, feat(gem-synth)#335]
  cc-plugin   0.6.0 → 0.6.1 (patch)  ✓ 有改动  [docs(promote)#342]
  kimi-plugin 0.14.0                ✗ 无改动，跳过
```

- 命令带参数（`/release-all minor`）→ 统一套用到所有 changed 组件。
- 否则逐组件确认 suggested_bump（用户可改 patch/minor/major 或指定 x.y.z）。
- 全部 changed=false → 打印「三组件均无未发布改动，无需发版」并结束。

### Step 4: 逐组件 bump + 建 PR（顺序 jfox → cc → kimi，仅 changed 者）

detect 已算出 suggested_version 并经确认，跳过各单组件 skill 的 dry-run 预览步。

⚠️ **每个组件开始前必须先 `git checkout main`**：上一组件的 bump 提交落在它自己的分支上，若不回 main，下一组件的 `git checkout -b` 会从上一组件分支拉出，导致 PR diff 串进别的组件文件（如 cc PR 里混入 jfox 的 pyproject.toml）。

对每个 changed 组件，循环执行（helper 在 main 工作树改文件 → 从 main 拉 bump 分支 → commit → push → 开 PR）：

1. `git checkout main`（确保下一组件从干净的 main 拉分支）
2. 正式 bump + 建分支 + commit + push + `gh pr create`：
   - **jfox** → `release_helper.py <v>` → `git checkout -b chore/bump-version-<v>` → `git add pyproject.toml jfox/__init__.py uv.lock CHANGELOG.md` → commit → push → PR（body 用 changelog_preview）
   - **cc-plugin** → `release_cc_plugin_helper.py <v>` → `git checkout -b chore/bump-cc-plugin-<v>` → `git add packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json` → commit → push → PR
   - **kimi-plugin** → `release_kimi_plugin_helper.py <v>` → `git checkout -b chore/bump-kimi-plugin-<v>` → `git add packages/kimi-plugin/kimi.plugin.json` → commit → push → PR

三组件文件不冲突，PR 可并存。收集所有 PR URL。

### Step 5: 告知用户合并

```
已创建 N 个 bump PR：
  - jfox:       <URL>
  - cc-plugin:  <URL>
  - kimi-plugin: <URL>
请依次合并后告知我，我将继续创建 jfox GitHub Release（cc/kimi 合 main 即生效，无需 Release）。
```

等待用户确认全部合并。**只有 jfox 在计划内时才需要合并后回流；若 jfox 被跳过，cc/kimi 合完即结束。**

### Step 6: 发 jfox Release（仅当 jfox 在计划内）

```bash
git checkout main && git pull origin main
uv run python .claude/skills/release/release_helper.py verify    # #333 兜底
# verify 退出码 0 才继续：
gh release create v<jfox_ver> --title "v<jfox_ver>" --notes "<changelog_preview>"
```

verify 非 0 → 打印 missing 条目，**停**，提示用户补 CHANGELOG（开 `docs(changelog)` PR 合并）后重跑 verify + release。**不自动建 Release。**

## 跳过提示

detect 阶段 changed=false 的组件，全程打印一次「<组件> 自 <ver> 以来无改动，跳过」后不再出现。

## 错误处理

- detect 某组件异常 → 该组件 changed=false + skip_reason，继续其他组件，不中断。
- 某组件 bump 中途失败 → 已建的早期组件 PR 保留（独立），报告失败组件、停。
- 用户只合并部分 PR → Step 6 不执行，提示「还有 X 个 PR 未合并」。
- verify 非 0 → 不建 Release，打印 missing，停。

## 与单组件 skill 的关系

- `/release`、`/release-cc-plugin`、`/release-kimi-plugin` 不变其单组件职责。
- 本 skill 是编排层，**委托**三组件 helper，自身只做 detect + 调度 + skip + verify 串接，无特判分支。
