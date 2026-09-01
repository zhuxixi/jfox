"""JFox prompt 记录与按需判断子包。

记录层：全量保存 Claude Code UserPromptSubmit（user_prompts 表）。
判断层：外部 agent 按 KB 分类（prompt_judgments 表）+ unresolved 索引。
"""
