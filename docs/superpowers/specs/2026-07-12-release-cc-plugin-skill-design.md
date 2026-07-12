# release-cc-plugin skill 设计

**日期**：2026-07-12
**目标 PR 分支**：`feat/release-cc-plugin-skill`（main 受保护，必须新分支 + PR）
**关联**：补 `/release`（CLI/PyPI 专用，不管 plugin）的缺口；流程源自 cc-plugin 0.5.0 → 0.5.1 发版（PR #313）

## 1. 问题

仓库已有 `.claude/skills/release` skill，但它**只管 CLI/PyPI 发版**（动 `pyproject.toml` / `jfox/__init__.py` / `uv.lock` / `CHANGELOG.md` + GitHub Release 触发 PyPI），**不管 cc-plugin**。

cc-plugin 走另一条轨道：marketplace 分发，`.claude-plugin/marketplace.json` 的 `source` 指向仓库内 `./packages/cc-plugin`，发版 = **三处版本号同步 bump + PR 合 main**，不打 tag、不发 PyPI。用户侧 `/plugin update` 读 `marketplace.json` 新版本号自动拉新。

目前这套没有 skill 承接，每次靠手改 + grep 验证（如本次 0.5.1）。CLAUDE.md 明确点名三处版本号「漏改任一处都会导致 marketplace 与 plugin 版本不一致」——已知坑。

## 2. 目标 / 非目标

**目标**

- 新建项目级 dev skill `.claude/skills/release-cc-plugin/`，把 cc-plugin 发版流程固化。
- 带 `release_cc_plugin_helper.py`，**原子 bump 3 字段**，堵漏改坑；`--dry-run` 预览。
- 流程镜像 `/release` 的确认点（前置校验 → 预览 → 用户确认 → 执行 → PR）。

**非目标**

- 不管 kimi-plugin（另一条轨道，`packages/kimi-plugin/kimi.plugin.json` 单字段 0.13.0；以后单独 `release-kimi-plugin`）。
- 不管 CLI/PyPI 发版（那是 `/release`）。
- 不自动合并 PR；不打 tag / GitHub Release（先例 #272 / #313 均 PR-only）。

## 3. 架构

两个文件，职责分离：

| 文件 | 职责 |
|---|---|
| `.claude/skills/release-cc-plugin/SKILL.md` | 流程编排（前置校验 → dry-run → 用户确认 → bump → 分支 / commit / PR） |
| `.claude/skills/release-cc-plugin/release_cc_plugin_helper.py` | 确定性计算（读版本 / 算版本 / bump 3 字段 / git log changelog / dry-run JSON） |

### helper 脚本契约

```
python release_cc_plugin_helper.py patch|minor|major|<explicit> [--dry-run]
```

- **读现版本**：`json.load` 读 `packages/cc-plugin/.claude-plugin/plugin.json` 的 `version` 字段（只读单一真相源；marketplace.json 必须与之同步）。
- **算新版本**：`patch` / `minor` / `major` 按语义递增；`<explicit>`（如 `0.6.0`）直传并校验格式 `^\d+\.\d+\.\d+$`，非法报错退出。
- **原子 bump 3 字段**（定向字符串替换，非 JSON round-trip——见风险）：
  - 把每个目标文件文本里的 `"version": "<old>"` 替换为 `"version": "<new>"`
  - `packages/cc-plugin/.claude-plugin/plugin.json`：期望命中 1 次
  - `.claude-plugin/marketplace.json`：期望命中 2 次（`metadata.version` + `plugins[0].version`）
  - 命中次数不符 → 报错，**不写任何文件**（原子性）
  - 写完后重新 `json.load` 两个文件，断言三处版本号都 == `<new>`，否则报错
- **changelog**：`git log <上次 bump commit>..HEAD --oneline -- packages/cc-plugin/` 取摘要。上次 bump commit 用 `git log -S '"<current_version>"' --format=%H -- .claude-plugin/marketplace.json | head -1` 定位，定位失败则降级为 `git log` 最近一次改 `marketplace.json` 的提交。
- **dry-run**：输出 JSON `{current_version, new_version, files_to_change[], changelog_summary[]}`，**不写任何文件**。
- **正式模式**：写两个文件，输出确认 JSON。

### SKILL.md 流程

1. **前置校验**（任一失败即停并告知原因）：
   - 当前分支 = main
   - 工作区干净（`git status --porcelain` 为空）
   - 无未合并的 `chore/bump-cc-plugin-*` 分支 / PR
2. `uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py <ver> --dry-run` → 解析 JSON。
3. 展示预览（现版本 → 新版本、改动文件、changelog）→ **必须等用户明确确认**才继续；拒绝或要改则停。
4. `uv run python .../release_cc_plugin_helper.py <ver>`（正式）→ 确认退出码 0，非 0 读错误并停。
5. `git checkout -b chore/bump-cc-plugin-<new_version>` → `git add` 两个文件 → `git commit -m "chore(cc-plugin): bump version <old> → <new>"` → `git push -u origin chore/bump-cc-plugin-<new_version>`。
6. `gh pr create`，PR body = changelog（release notes）。
7. 告知用户合并，**不打 tag / 不发 Release**。

## 4. 默认决策

- **版本参数**：`patch|minor|major|<explicit>`，默认建议 patch（无新 skill / command → semver patch，与 0.5.1 一致）。
- **tag**：默认不打（#272 / #313 先例）；如需追溯用户可手动 `gh release create cc-plugin-v<x>`。
- **changelog**：只写进 PR body，**不新增 CHANGELOG 文件**（YAGNI；CLI 根 `CHANGELOG.md` 是 1.3.x 那条，不混入）。

## 5. 验证

- **helper 单测**（快速、无外部依赖，可自主跑；放 `tests/unit/test_release_cc_plugin_helper.py`）：
  - 版本递增：`patch` / `minor` / `major` 计算正确（如 `0.5.1` → patch `0.5.2` / minor `0.6.0` / major `1.0.0`）
  - explicit 格式校验（`0.6` / `abc` 报错退出码非 0）
  - dry-run 不写文件
  - 正式模式：三处版本号都 == 新版本（断言），命中次数不符时报错不写
  - changelog 抓取（mock `git log` 输出）
- **SKILL.md 人工通读**：流程自洽、确认点齐全、与 `/release` 风格一致。
- **端到端冒烟**：在临时 git 仓库副本上跑一次 dry-run + 正式，对照真实 marketplace/plugin.json 结构，不实际推远程。

## 6. 风险

- **JSON 格式被改写**：定向字符串替换只动 `"version": "<old>"` 那几个 token，保留 `marketplace.json` 里 `"author": { "name": "zhuxixi" }` 等单行紧凑写法——diff 最小。**不用** `json.dump` round-trip（会把紧凑对象展开成多行，产生不必要 diff）。
- **上次 bump commit 定位不准**：`git log -S` 可能匹配到无关提交；降级方案——取 `git log --oneline -- .claude-plugin/marketplace.json` 最近一次改动，并在 dry-run 输出里显示 commit hash 供人工核对。
- **过度工程**：helper 不引入版本号解析库，正则 + `str.split('.')` 即可；只依赖标准库（json / re / subprocess / pathlib / sys）。
- **命中率假设漂移**：若将来 plugin.json / marketplace.json 结构变化（如多插件），命中次数假设（1 / 2）会失效——靠「写后断言三处相等」兜底，结构变了会报错而非静默漏改。
