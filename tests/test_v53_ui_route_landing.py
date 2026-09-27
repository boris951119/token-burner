# -*- coding: utf-8 -*-
"""v53 刀G（UI 所有权重路由）+ 刀H（文案落地门禁）回归。"""
from __future__ import annotations

from app.agents.module_builder import ModulePlan
from app.utils.atomic_coverage import (
    enforce_atomic_coverage,
    normalize_atomic_ownership,
    reroute_ui_ownership,
)
from app.utils.manifest_landing import (
    check_manifest_landing,
    extract_manifest_anchors,
)


REQ_REGISTER = "\n".join([
    "## 模块： Identity and Access",
    "依赖：无",
    "账户注册与登录。",
    "### REQ-1-1-1 Register a New GitHub Account（验收标准）",
    'The registration page is opened by the unique link named '
    '"Create an account" from the sign-in page. The form contains '
    'exactly one textbox labeled "Username", one textbox labeled '
    '"Email", one password input labeled "Password", one password '
    'input labeled "Confirm password", one initially unchecked '
    'checkbox named "Agree to the terms", and one enabled button '
    'named "Create account".',
    "  - 场景：register",
    "    GIVEN: The visitor starts at the application home page.",
    '    WHEN: The visitor clicks "Sign in", then clicks '
    '"Create an account", fills "Username", "Email", "Password", '
    '"Confirm password", checks "Agree to the terms", and clicks '
    '"Create account".',
    '    THEN: The form shows "Username" and "Create account".',
    "### REQ-9-9-9 Internal DB Helper（验收标准）",
    "Internal persistence helper with no UI controls.",
    "  - 场景：noop",
    "    GIVEN: ready",
    "    WHEN: call helper",
    "    THEN: ok",
])


def _plans_mismatch():
    return [
        ModulePlan(
            name="shared_core",
            responsibility="数据库连接与内核 REQ-1-1-1 REQ-9-9-9",
            dependencies=[],
            priority=1,
        ),
        ModulePlan(
            name="ui_home",
            responsibility="托管 GET / 首页与注册入口",
            dependencies=["shared_core"],
            priority=2,
        ),
        ModulePlan(
            name="data_seed",
            responsibility="种子数据初始化",
            dependencies=["shared_core"],
            priority=3,
        ),
    ]


def test_knife_g_reroutes_ui_req_off_shared_core():
    """control_labels 非空的 REQ-1-1-1 不得留在 shared_core。"""
    plans = _plans_mismatch()
    report = normalize_atomic_ownership(REQ_REGISTER, plans)
    assert report.owned.get("REQ-1-1-1") == "ui_home", report.owned
    # 无控件的内部 REQ 可继续挂 core
    assert report.owned.get("REQ-9-9-9") in {
        "shared_core", "data_seed", "ui_home",
    } or "REQ-9-9-9" in report.owned


def test_knife_g_reroute_helper_direct():
    owner = {"REQ-1-1-1": "shared_core", "REQ-9-9-9": "data_seed"}
    plans = _plans_mismatch()
    out = reroute_ui_ownership(owner, plans, REQ_REGISTER)
    assert out["REQ-1-1-1"] == "ui_home"
    assert out["REQ-9-9-9"] == "data_seed"  # 无 control_labels，不动


def test_knife_g_enforce_also_reroutes():
    plans = _plans_mismatch()
    report = enforce_atomic_coverage(REQ_REGISTER, plans)
    assert report.owned.get("REQ-1-1-1") == "ui_home", report.owned
    home = next(p for p in plans if p.name == "ui_home")
    assert "REQ-1-1-1" in (home.responsibility or "")


_MANIFEST = """
托管 GET /，提供首页

【UI 页面与文案清单（硬契约，逐字实现）】
- 模块： Identity and Access: Sign in、Create an account、Username、Email、Password、Confirm password、Agree to the terms、Create account
"""


def test_knife_h_extracts_manifest_anchors():
    anchors = extract_manifest_anchors(_MANIFEST)
    assert "Create an account" in anchors
    assert "Username" in anchors
    assert len(anchors) >= 4


def test_knife_h_reds_when_landing_below_half():
    """v53-github 同形：契约有注册六件套，源码只有幻觉 chrome。"""
    bad_code = '''
from flask import Blueprint
_bp = Blueprint("ui_home", __name__)
@_bp.get("/")
def index():
    return "<span>42.2k results (173 ms)</span><a>Secret Ops</a>"
'''
    issues = check_manifest_landing(
        bad_code, responsibility=_MANIFEST, module="ui_home")
    assert issues, "应门禁红"
    assert "文案落地" in issues[0]
    assert "Create an account" in issues[0]
    assert "Username" in issues[0]


def test_knife_h_greens_when_majority_present():
    good_code = '''
from flask import Blueprint
_bp = Blueprint("ui_home", __name__)
@_bp.get("/")
def index():
    return """
    <a href="/signup">Create an account</a>
    <label>Username</label><input>
    <label>Email</label><input>
    <label>Password</label><input>
    <label>Confirm password</label><input>
    <label>Agree to the terms</label><input type="checkbox">
    <button>Create account</button>
    <a>Sign in</a>
    """
'''
    assert check_manifest_landing(
        good_code, responsibility=_MANIFEST, module="ui_home") == []


def test_knife_h_skips_when_fewer_than_four_anchors():
    thin = "just a helper module"
    code = "def helper():\n    return 1\n"
    assert check_manifest_landing(
        code, responsibility=thin, module="helper") == []
