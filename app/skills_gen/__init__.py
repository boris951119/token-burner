"""刀M：生成规范 skill 库（GenSkill）——服务代码生成提示词。

API 从 app.skills_gen.library 转出；设计定稿见 docs/agent-inbox.md
INBOX-016 规整结论（f7a386d）。
"""
from app.skills_gen.library import (  # noqa: F401
    GenSkill, detect_skills, render_skills_summary, repair_directive,
)
