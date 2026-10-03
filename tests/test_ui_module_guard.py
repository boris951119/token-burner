# -*- coding: utf-8 -*-
"""v63.1 拆分守卫 + monolith 实验开关回归。

v61 尸检（50d1f62e8860 同族）：spec 拆分全 API 化、无 UI 承载模块 →
inject_ui_manifest 无目标可注 → 整树零 HTML → 交付=保底壳。
守卫=需求含 UI 形态而无模块得分时，确定性补挂 webui_pages 模块。
monolith=全部模块合并单块的实验臂（接缝消除假设），默认关零行为。
"""
from __future__ import annotations

from app.agents.module_builder import (
    ModulePlan,
    ensure_ui_module,
    merge_plans_monolith,
)


def _plans(*names_resps):
    return [ModulePlan(name=n, responsibility=r, dependencies=[],
                       priority=i)
            for i, (n, r) in enumerate(names_resps)]


UI_REQ = (
    "The visitor opens the home page and clicks the visible link "
    "'Sign in', enters username `alice-dev` and password, then the "
    "workspace page shows repository list.")


class TestEnsureUiModule:
    def test_appends_when_all_api(self):
        plans = _plans(("auth_api", "login/register REST endpoints"),
                       ("repo_api", "repository CRUD API"))
        out = ensure_ui_module(plans, UI_REQ)
        assert out == "webui_pages"
        assert plans[-1].name == "webui_pages"
        assert set(plans[-1].dependencies) == {"auth_api", "repo_api"}
        assert plans[-1].priority > max(p.priority for p in plans[:-1]), \
            "UI 层最后开发（priority 最大）"
        assert "register_all" in plans[-1].responsibility, \
            "补挂模块必须引用 seed kernel"

    def test_noop_when_ui_module_exists(self):
        plans = _plans(("auth_api", "login API"),
                       ("webui", "renders pages and navigation"))
        assert ensure_ui_module(plans, UI_REQ) is None
        assert len(plans) == 2

    def test_noop_for_cli_task(self):
        plans = _plans(("parser", "parse csv files"))
        assert ensure_ui_module(plans, "convert csv to json files") is None

    def test_noop_empty(self):
        assert ensure_ui_module([], UI_REQ) is None


class TestMergeMonolith:
    def test_merges_all_into_one(self):
        plans = _plans(("a", "does A"), ("b", "does B"), ("c", "does C"))
        merged = merge_plans_monolith(plans)
        assert len(merged) == 1
        assert merged[0].name == "app"
        assert "does A" in merged[0].responsibility
        assert "does B" in merged[0].responsibility
        assert merged[0].dependencies == []

    def test_single_plan_unchanged(self):
        plans = _plans(("solo", "everything"))
        assert merge_plans_monolith(plans) is plans


class TestConfigField:
    def test_default_modular(self):
        from app.config import Settings
        assert Settings.module_mode == "modular"
