# Changelog

All notable changes to jfox-cli will be documented in this file.

## [0.4.2] - 2026-04-22

### Features
- add Kimi CLI skill collection (#166)
- **skills**: add release skill with full workflow instructions
- **skills**: add release helper script with version bump and CHANGELOG generation

### Fixes
- **lint**: remove unused pytest import
- **skills**: improve git Chinese encoding and fix pluralization in release helper
- **skills**: address code review issues in release helper
- **cli**: list 命令 table 输出显示完整 18 位笔记 ID

### Changes
- style(lint): format test_release_helper.py with black
- Merge pull request #167 from zhuxixi/feat/kimi-cli-skills
- Merge pull request #165 from zhuxixi/fix-list-id-truncation

[0.4.2]: https://github.com/zhuxixi/jfox/compare/v0.4.1...v0.4.2

## [0.2.0] - 2026-04-13

### Features
- **edit**: add `--content-file` parameter for reading note content from a file (#106)

### Fixes
- **skill**: add `--kb` parameter support to jfox-health skill
- **cli**: add `use` as alias for `kb switch` subcommand (#105)

### Changes
- **skills**: redesign from 5 skills to 4
- **test**: fix flaky `test_update_content_preserves_id_and_created` (timing race on fast machines)

### Performance
- **startup**: lazy import optimization to eliminate startup overhead for lightweight commands (#122)
- **ci**: optimize CI coverage job to avoid rerunning tests (#119)

## [0.1.5] - 2026-04-12

### Fixes
- **index**: add `--kb` parameter to `jfox index` command (#104) (#113)
- **index**: fix `index verify` false positives (filename vs index ID format mismatch) (#111)
- **index**: fix `index rebuild` clearing ChromaDB before re-indexing (#110)
- **test**: prevent test KB residue in global config (#101)
- **ci**: resolve Windows path comparison bug and add quality gate

### Changes
- **style**: auto-fix all ruff/black lint errors (1869 fixed)

[0.2.0]: https://github.com/zhuxixi/jfox/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/zhuxixi/jfox/compare/v0.1.4...v0.1.5
