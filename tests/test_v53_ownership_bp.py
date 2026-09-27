# -*- coding: utf-8 -*-
"""v53 刀C（契约跟随所有权）+ 刀D（蓝图 `_bp` 惯例）回归。"""
from __future__ import annotations

from app.agents.module_builder import ModulePlan
from app.utils.atomic_coverage import (
    enforce_atomic_coverage,
    inject_contracts_by_ownership,
)
from app.utils.blueprint_convention import check_blueprint_convention


REQ_TEXT = "\n".join([
    "## 模块：Workbooks",
    "依赖：无",
    "工作簿首页。",
    "### REQ-1-1-1 View and Open（验收标准）",
    'Users view workbooks. Each record displays '
    '"Last updated: <last updated value>" and a workbook link.',
    "  - 场景：open",
    "    GIVEN: The visitor starts at the application home page.",
    '    WHEN: The user clicks the visible workbook entry "Q3 Sales".',
    '    THEN: The editor shows "Sheet1".',
    "### REQ-1-1-2 Other（验收标准）",
    "Unrelated API helper.",
    "  - 场景：noop",
    "    GIVEN: ready",
    "    WHEN: call helper",
    "    THEN: ok",
])


def test_contracts_follow_ownership_not_single_ui_target():
    """REQ-1-1-1 被 B 认领 → B 有 Last updated；无关模块 A 没有。"""
    from app.acceptance_compile import compile_checklists_from_text

    plans = [
        ModulePlan(
            name="webui_static_assets",
            responsibility="静态资源与 CSS（无关首页契约）",
            dependencies=[],
            priority=1,
        ),
        ModulePlan(
            name="webui_home_page",
            responsibility="首页渲染 REQ-1-1-1",
            dependencies=[],
            priority=2,
        ),
        ModulePlan(
            name="api_helper",
            responsibility="辅助 API REQ-1-1-2",
            dependencies=[],
            priority=3,
        ),
    ]
    report = enforce_atomic_coverage(REQ_TEXT, plans)
    owner = dict(report.owned or {})
    for rid, mod in (report.assigned or {}).items():
        owner.setdefault(rid, mod)
    # 强制所有权：首页模块认领 1-1-1（模拟 normalize 结果）
    owner["REQ-1-1-1"] = "webui_home_page"
    owner["REQ-1-1-2"] = "api_helper"

    cks = compile_checklists_from_text(REQ_TEXT)
    assert any(c.req_id == "REQ-1-1-1" for c in cks), [c.req_id for c in cks]
    # 清掉 enforce 可能写入的清单，再按强制所有权注入
    for p in plans:
        from app.utils.atomic_coverage import _UX_CHECKLIST_BLOCK
        p.responsibility = _UX_CHECKLIST_BLOCK.sub(
            "", p.responsibility or "")

    injected = inject_contracts_by_ownership(plans, cks, owner)
    assert injected.get("webui_home_page", 0) >= 1, injected

    home = next(p for p in plans if p.name == "webui_home_page")
    static = next(p for p in plans if p.name == "webui_static_assets")
    assert "Last updated" in home.responsibility, home.responsibility
    assert "验收节点逐字清单" in home.responsibility
    assert "Last updated" not in static.responsibility
    assert "验收节点逐字清单" not in static.responsibility


def test_inject_ui_manifest_no_longer_dumps_full_checklist():
    """刀C：整表验收清单不再经 inject_ui_manifest 单目标灌入。"""
    from app.agents.module_builder import inject_ui_manifest

    plans = [
        ModulePlan(name="data_core", responsibility="数据层",
                   dependencies=[], priority=1),
        ModulePlan(name="view", responsibility="组装页面与静态资源",
                   dependencies=["data_core"], priority=2),
    ]
    assert inject_ui_manifest(plans, REQ_TEXT) == "view"
    assert "验收节点逐字清单" not in plans[1].responsibility


def test_blueprint_gate_reds_inline_app_routes():
    bad = '''
from flask import Flask

def make_routes():
    app = Flask(__name__)
    @app.route("/api/x")
    def x():
        return {}
    return app
'''
    issues = check_blueprint_convention(bad, module="workbook_api")
    assert issues, "应门禁红"
    assert "_bp" in issues[0] and "挂到" in issues[0]


def test_blueprint_gate_greens_top_level_bp():
    good = '''
from flask import Blueprint
_bp = Blueprint("workbook_api", __name__)

@_bp.route("/api/x")
def x():
    return {}
'''
    assert check_blueprint_convention(good, module="workbook_api") == []


def test_blueprint_gate_skips_create_app_factory():
    factory = '''
from flask import Flask
from peer import _bp

def create_app():
    app = Flask(__name__)
    app.register_blueprint(_bp)
    @app.route("/")
    def home():
        return "ok"
    return app
'''
    assert check_blueprint_convention(factory, module="webui_app") == []


def test_assemble_logs_bp_coverage(tmp_path, capsys):
    from app.utils.mechanical_assembly import assemble

    pkg = tmp_path / "workbook_api"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "workbook_api.py").write_text(
        "from flask import Blueprint\n"
        "_bp = Blueprint('workbook_api', __name__)\n"
        "@_bp.route('/api/x')\n"
        "def x():\n"
        "    return {}\n",
        encoding="utf-8",
    )
    summary = assemble(tmp_path)
    assert summary.get("bp_coverage") == "1/1"
    out = capsys.readouterr().out
    assert "Blueprint 覆盖 1/1" in out
