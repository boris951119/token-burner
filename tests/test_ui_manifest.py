# -*- coding: utf-8 -*-
"""UI 页面清单注入回归（平台 v6-3 取证：占位壳 0/32）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


class TestInjectUiManifest:
    def test_manifest_injected_into_ui_module(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [
            ModulePlan(name="data_core", responsibility="数据层", dependencies=[], priority=1),
            ModulePlan(name="view", responsibility="组装页面与静态资源", dependencies=["data_core"], priority=2),
        ]
        req = '需求：首页含 "Take a note" 表单。Seed data: note "Sprint goals"。'
        target = inject_ui_manifest(plans, req)
        assert target == "view"
        assert "Take a note" in plans[1].responsibility
        assert "Sprint goals" in plans[1].responsibility
        assert "硬契约" in plans[1].responsibility

    def test_non_ui_task_skipped(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="cli", responsibility="命令行工具", dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, '需求：做 "加法"') is None

    def test_empty_requirement_skipped(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="页面", dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, "") is None


class TestUxChecklistInjection:
    """9/22 keep#2 取证：锚点摊平丢 GWT 归属——逐节点清单须随契约注入。"""

    def test_structured_checklist_injected(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        req = "\n".join([
            "## 模块：M1 Notes",
            "依赖：无",
            "笔记模块。",
            "### REQ-1.1 Create（验收标准）",
            'Seed data: note "Sprint goals".',
            "  - 场景：create",
            "    GIVEN: the home page is open",
            '    WHEN: press the "Take a note" button',
            '    THEN: a snackbar shows "Note created"',
        ])
        plans = [
            ModulePlan(name="data_core", responsibility="数据层",
                       dependencies=[], priority=1),
            ModulePlan(name="view", responsibility="组装页面与静态资源",
                       dependencies=["data_core"], priority=2),
        ]
        assert inject_ui_manifest(plans, req) == "view"
        r = plans[1].responsibility
        assert "验收节点逐字清单" in r
        assert "REQ-1.1" in r and '"Take a note"' in r and '"Note created"' in r

    def test_plain_text_requirement_unaffected(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="页面",
                            dependencies=[], priority=1)]
        assert inject_ui_manifest(
            plans, '需求：首页含 "Search" 框。') == "view"
        assert "验收节点逐字清单" not in plans[0].responsibility
