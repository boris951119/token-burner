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

【验收节点逐字清单（机械抽取自需求 GWT 结构，逐条满足）】
- REQ-1-1-1 Register｜控件须可见: "Sign in"、"Create an account"、"Username"、"Email"、"Password"、"Confirm password"、"Agree to the terms"、"Create account"｜首页卡片须含: "Create an account"
"""

_HARD_DUMP = """
【UI 页面与文案清单（硬契约，逐字实现）】
- 模块： Identity: Sign in、Create an account、Username、Email、Password、Confirm password、Agree to the terms、Create account、the requested workflow、false、Worksheet grid、工作簿1
"""


def test_knife_h_extracts_manifest_anchors():
    anchors = extract_manifest_anchors(_MANIFEST)
    assert "Create an account" in anchors
    assert "Username" in anchors
    assert len(anchors) >= 4


def test_v56_knife_h_ignores_hard_manifest_dump():
    """v56-4：整表硬契约 89 条不得灌入锚点（含 placeholder/boolish/中文 OCR）。"""
    anchors = extract_manifest_anchors(_HARD_DUMP)
    assert "the requested workflow" not in anchors
    assert "false" not in anchors
    assert "工作簿1" not in anchors
    # 无刀C 清单时硬契约整表跳过 → 锚点应极少/为空
    assert len(anchors) < 4


def test_v56_knife_h_blacklists_placeholder_in_checklist():
    dirty = _MANIFEST + '\n- REQ-x｜动作后须出现: "the requested workflow"、"true"\n'
    anchors = extract_manifest_anchors(dirty)
    assert not any("requested workflow" in a.lower() for a in anchors)
    assert "true" not in anchors


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
    assert "Create an account" in issues[0] or "Username" in issues[0]


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


def test_v56_home_route_html_gate_reds_missing_card_field():
    from app.utils.manifest_landing import check_home_route_html
    html = "<html><body><a>Q3 Sales</a><p>Region East</p></body></html>"
    issues = check_home_route_html(
        html, responsibility=_MANIFEST, module="webui")
    # _MANIFEST 首页卡片须含 Create an account
    assert issues and "卡片模板补字段" in issues[0]
    assert "Create an account" in issues[0]


def test_v56_home_route_html_gate_greens_when_present():
    from app.utils.manifest_landing import check_home_route_html
    html = '<html><body><article><a>Create an account</a></article></body></html>'
    assert check_home_route_html(
        html, responsibility=_MANIFEST, require_article=True,
        module="webui") == []


def test_v56_home_route_html_require_article_scope():
    from app.utils.manifest_landing import check_home_route_html
    # 串在 footer 不在 article → 红
    html = ('<html><body><article><a>Q3 Sales</a></article>'
            '<footer>Create an account</footer></body></html>')
    issues = check_home_route_html(
        html, responsibility=_MANIFEST, require_article=True,
        module="webui")
    assert issues
    assert ("article" in issues[0].lower() or "卡片" in issues[0])


# ---- 刀J'：login surface + 隐藏元素 ----

_LOGIN_MANIFEST = """
托管 /login 登录页

【验收节点逐字清单（机械抽取自需求 GWT 结构，逐条满足）】
- REQ-1-1-1 Register｜控件须可见: "Username"、"Password"｜登录页须含: "Create an account"、"Sign in to GitHub"
"""


def test_knife_j_login_route_html_reds_when_missing():
    """#85 同形：/login 渲染体无 Create an account → 红。"""
    from app.utils.manifest_landing import check_login_route_html
    html = "<html><body><h1>Login</h1><label>Username</label>" \
           "<label>Password</label><button>Sign In</button></body></html>"
    issues = check_login_route_html(
        html, responsibility=_LOGIN_MANIFEST, module="web_core",
        route="/login")
    assert issues
    assert "Create an account" in issues[0]
    assert "login" in issues[0].lower() or "登录" in issues[0]


def test_knife_j_login_route_html_greens_when_visible():
    from app.utils.manifest_landing import check_login_route_html
    html = (
        '<html><body><a href="/signup">Create an account</a>'
        "<h1>Sign in to GitHub</h1></body></html>"
    )
    assert check_login_route_html(
        html, responsibility=_LOGIN_MANIFEST, module="web_core") == []


def test_knife_j_hidden_element_does_not_count():
    """隐藏元素里的串不算落地（display:none / hidden / aria-hidden）。"""
    from app.utils.manifest_landing import check_login_route_html
    html = (
        '<html><body><div hidden>Create an account</div>'
        '<span style="display:none">Sign in to GitHub</span>'
        "<p>Login</p></body></html>"
    )
    issues = check_login_route_html(
        html, responsibility=_LOGIN_MANIFEST, module="web_core")
    assert issues
    assert "Create an account" in issues[0]


def test_knife_j_surface_sidecar_writes_home_and_login(tmp_path):
    from app.utils.manifest_landing import (
        write_surface_anchors_sidecar,
        load_surface_anchors_sidecar,
        SURFACE_ANCHORS_SIDECAR,
        HOME_ANCHORS_SIDECAR,
    )
    text = _MANIFEST + "\n" + _LOGIN_MANIFEST
    by_s = write_surface_anchors_sidecar(tmp_path, [text])
    assert "Create an account" in (by_s.get("login") or by_s.get("home") or [])
    assert (tmp_path / SURFACE_ANCHORS_SIDECAR).is_file()
    assert (tmp_path / HOME_ANCHORS_SIDECAR).is_file()
    loaded = load_surface_anchors_sidecar(tmp_path)
    assert "login" in loaded or "home" in loaded


def test_acceptance_login_surface_from_sign_in_page(tmp_path):
    """编译器：sign-in page 同句引号 → surface=login → 登录页须含。"""
    from app.acceptance_compile import (
        compile_checklists,
        render_ux_checklist,
    )
    yaml_text = '''
id: ROOT
type: FOLDER
children:
  - id: REQ-1-1-1
    name: Register
    type: ATOMIC
    description: >
      The registration page is opened by the unique link named
      "Create an account" from the sign-in page.
    scenarios:
      - name: register
        steps:
          - keyword: GIVEN
            content: The visitor starts at the application home page.
          - keyword: WHEN
            content: >
              The visitor clicks "Sign in", then clicks
              "Create an account".
          - keyword: THEN
            content: The form shows "Username".
'''
    p = tmp_path / "requirements.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    cls = compile_checklists(p)
    ck = next(c for c in cls if c.req_id == "REQ-1-1-1")
    surfs = ck.surfaces_of("Create an account")
    assert "login" in surfs, surfs
    ux = render_ux_checklist(cls)
    assert "登录页须含" in ux
    assert "Create an account" in ux
