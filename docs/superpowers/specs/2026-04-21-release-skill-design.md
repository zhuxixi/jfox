# Release Skill 设计

## 目标

创建一个 `/release` skill，将 jfox 的发版流程从手动多步操作简化为一条命令。覆盖从版本号 bump 到 GitHub Release 创建的全流程。

## 背景

### 现状痛点

- 发版需要手动修改 3 个文件：`pyproject.toml`、`jfox/__init__.py`、`uv.lock`
- 曾因遗漏 `__init__.py` 导致 #88 事故
- CHANGELOG.md 停在 0.2.0，后续 4 个版本未更新
- 每次发版需手动创建分支、commit、PR、Release，步骤重复

### 发版流程

GitHub Release (tag) → `publish.yml` workflow → PyPI (OIDC)

## 方案

### 架构：Skill + Python 辅助脚本

- **Skill 文件** (`SKILL.md`): 流程指令，Claude 读取后逐步执行
- **辅助脚本** (`release_helper.py`): 处理确定性工作（版本计算、文件更新、CHANGELOG 生成），输出 JSON

### 文件结构

```
.claude/skills/release/
├── SKILL.md            # Skill 指令文件
└── release_helper.py   # Python 辅助脚本
```

## 调用方式

```
/release 0.5.0          # 指定具体版本号
/release patch          # bump patch: 0.4.1 → 0.4.2
/release minor          # bump minor: 0.4.1 → 0.5.0
/release major          # bump major: 0.4.1 → 1.0.0
```

## 辅助脚本设计

### 输入

命令行参数：版本号（semver 字符串或 bump 类型关键词）

### 职责

1. **版本号计算**
   - 从 `pyproject.toml` 读取当前版本
   - 解析 bump 类型或使用指定版本
   - 校验 semver 格式
   - 确保新版本 > 当前版本

2. **三处文件更新**
   - `pyproject.toml`: 替换 `version = "X.Y.Z"` 行
   - `jfox/__init__.py`: 替换 `__version__ = "X.Y.Z"` 行
   - `uv.lock`: 运行 `uv lock` 更新

3. **CHANGELOG 生成**
   - 获取上一个 git tag（`git describe --tags --abbrev=0`）
   - 提取 `<last_tag>..HEAD` 之间的 commit log
   - 按 conventional commit 类型分类：feat → Features, fix → Fixes, 其他 → Changes
   - 从 commit message 中提取 scope 和 PR 号
   - 生成 Markdown 条目并插入 CHANGELOG.md 头部
   - 添加底部比较链接

### 输出

JSON 格式，包含：

```json
{
  "current_version": "0.4.1",
  "new_version": "0.5.0",
  "changelog_entries": [
    {"type": "feat", "scope": "search", "message": "add hybrid search mode", "pr": 155},
    {"type": "fix", "scope": "cli", "message": "fix list command table output", "pr": 165}
  ],
  "changelog_summary": "2 features, 3 fixes, 1 change",
  "files_modified": ["pyproject.toml", "jfox/__init__.py", "uv.lock", "CHANGELOG.md"]
}
```

脚本出错时输出 `{"error": "描述"}` 并以非零退出码退出。

## Claude 负责的流程

### 1. 前置校验

- 当前分支是否为 main
- 工作区是否干净（`git status --porcelain`）
- 是否存在未合并的 bump 分支（`git branch --list 'chore/bump-*'`）
- 是否有未合并的 PR（`gh pr list --state open`）

### 2. 调用辅助脚本

```bash
uv run python .claude/skills/release/release_helper.py <version>
```

### 3. 展示变更摘要并等待确认

向用户展示：
- 新版本号
- CHANGELOG 条目预览
- 即将修改的文件列表

**必须等待用户确认后才继续。**

### 4. Git 操作

```bash
git checkout -b chore/bump-version-X.Y.Z
git add pyproject.toml jfox/__init__.py uv.lock CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"
git push -u origin chore/bump-version-X.Y.Z
```

### 5. 创建 PR

```bash
gh pr create \
  --title "chore: bump version to X.Y.Z" \
  --body "<CHANGELOG content>"
```

### 6. 等待合并提示

告知用户 PR 已创建，提示合并。

### 7. 创建 GitHub Release

合并后由用户确认，然后执行：

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "<CHANGELOG content>"
```

这会触发 `publish.yml` 自动发布到 PyPI。

## CHANGELOG 格式

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Features
- **scope**: description (#PR)

### Fixes
- **scope**: description (#PR)

### Changes
- **scope**: description (#PR)

[X.Y.Z]: https://github.com/zhuxixi/jfox/compare/vPREV...vX.Y.Z
```

## 安全设计

- **用户确认点**: 变更摘要后、commit 前、创建 Release 前
- **不跳过 hook**: 使用正常 git commit 流程，不使用 `--no-verify`
- **分支保护**: 始终在新分支操作，不直接改 main
- **幂等性**: 脚本可在已修改的文件上安全重新运行
- **预检阻断**: 校验失败时立即停止，不执行任何文件修改

## 不做的事

- 不修改 `publish.yml` workflow
- 不处理 prerelease/beta 版本号
- 不支持同时 bump 多个版本
- 不自动监控 PyPI 发布状态
