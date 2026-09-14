# -*- coding: utf-8 -*-
"""规模工程：FOLDER 摘要渲染 + 拆分阶段需求全文注入
（keep1 取证：32 需求全量文本令 glm-5.3 讨论超墙钟）。"""

from __future__ import annotations

from app.arcbench_ingest import render_folder_summary
from app.agents.module_builder import ModuleBuilder


def _keep_like_tree() -> dict:
    return {
        "id": "ROOT", "name": "Keep", "type": "FOLDER",
        "description": "Note management system.",
        "children": [
            {
                "id": "REQ-1", "name": "Home Page", "type": "FOLDER",
                "description": "Main workspace. Reference: ![i](./reference/home.png)",
                "dependencies": [],
                "children": [
                    {"id": "REQ-1.1", "name": "Enter Website", "type": "ATOMIC",
                     "description": "Open the application and display the home page.",
                     "dependencies": [],
                     "scenarios": [
                         {"name": "Enter", "steps": [
                             {"keyword": "GIVEN", "content": "browser"},
                             {"keyword": "WHEN", "content": "open URL"},
                             {"keyword": "THEN", "content": "home displayed"},
                         ]},
                     ]},
                ],
            },
            {
                "id": "REQ-2", "name": "Notes", "type": "FOLDER",
                "description": "Note CRUD.",
                "dependencies": ["REQ-1"],
                "children": [
                    {"id": "REQ-2.1", "name": "Create Note", "type": "ATOMIC",
                     "description": "Create a note.", "dependencies": [],
                     "scenarios": []},
                ],
            },
        ],
    }


class TestRenderFolderSummary:
    def test_compression_and_structure(self):
        tree = _keep_like_tree()
        brief = render_folder_summary(tree)
        assert "## 模块：REQ-1 Home Page（1 条原子需求）" in brief
        assert "- REQ-1.1 Enter Website" in brief
        assert "GIVEN" not in brief, "场景步骤不得进入摘要"
        assert "（验收标准）" not in brief, "原子正文不得进入摘要"
        assert "技术栈硬性要求" in brief, "规则 1-16 必须保留"

    def test_module_count_consistent_with_full(self):
        from app.arcbench_ingest import render_requirement_text

        tree = _keep_like_tree()
        full = render_requirement_text(tree)
        brief = render_folder_summary(tree)
        assert brief.count("## 模块：") == full.count("## 模块：")
        assert len(brief) <= len(full), "摘要不得大于全文（真实 keep 树实测 26%）"


class TestSplitSpecRequirementInjection:
    def test_requirement_appended_to_prompt(self):
        captured = {}

        class _LLM:
            def chat(self, model, messages, **kwargs):
                captured["user"] = messages[-1]["content"]
                return type("R", (), {"content": '{"modules": []}'})()

        from app.config import Settings

        builder = ModuleBuilder(_LLM(), "openai/glm-5.3", Settings(), None)
        try:
            builder.split_spec("SPEC", requirement="原始需求全文XYZ")
        except Exception:
            pass  # 解析失败无所谓——只验证提示词
        assert "原始需求全文XYZ" in captured["user"]
        assert "原始需求全文" in captured["user"]

    def test_no_requirement_no_section(self):
        captured = {}

        class _LLM:
            def chat(self, model, messages, **kwargs):
                captured["user"] = messages[-1]["content"]
                return type("R", (), {"content": '{"modules": []}'})()

        from app.config import Settings

        builder = ModuleBuilder(_LLM(), "openai/glm-5.3", Settings(), None)
        try:
            builder.split_spec("SPEC")
        except Exception:
            pass
        assert "原始需求全文" not in captured["user"]
