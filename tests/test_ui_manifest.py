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
