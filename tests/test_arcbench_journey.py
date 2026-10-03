"""旅程级验收测试（factory26 r4 强化：冒烟之上，Playwright 同维度拦截）。

锚点：
- 路由探测定位组装模块 + url_map 倾倒；
- LLM 旅程脚本（结构约束样板内嵌）执行 → PASS/断言失败分层；
- 脚本自修复一轮（只修脚本），仍失败 → RepoFixer 修应用；
- 危险 API 扫描拦截网络/子进程类脚本；生成基础设施故障 = SKIP 不冤枉应用。
"""

from __future__ import annotations

import json

import pytest

from app.arcbench_smoke import (
    _extract_body,
    _is_script_defect,
    _journey_gate,
    _JOURNEY_BOILERPLATE,
    _probe_routes,
    run_smoke,
)


# ---- 夹具应用：等价 r3 交付形态（多模块 + create_app + 旅程路径） ----

_WEBAPP = '''\
from flask import Flask, jsonify, request

_USERS = {}
_ORDERS = []
_TRAINS = [{"number": "G101", "from": "Beijing South", "to": "Shanghai Hongqiao"}]


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "journey-fixture"  # 有 /login 路由：冒烟硬契约要求

    @app.route("/api/health")
    def health():
        return jsonify(status="ok")

    @app.route("/login")
    def login_page():
        return "login page"

    @app.route("/register")
    def register_page():
        return "register page"

    @app.route("/")
    def home():
        return "<a href='/login'>Login</a><a href='/register'>Register</a>"

    @app.route("/api/auth/register", methods=["POST"])
    def register():
        data = request.get_json(force=True)
        _USERS[data["username"]] = data["password"]
        return jsonify(message="Registration successful", ok=True), 201

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        data = request.get_json(force=True)
        if _USERS.get(data["username"]) != data["password"]:
            return jsonify(message="bad credentials"), 401
        return jsonify(message="Login successful", username=data["username"])

    @app.route("/api/search")
    def search():
        frm, to = request.args.get("from_station"), request.args.get("to_station")
        trains = [t for t in _TRAINS if t["from"] == frm and t["to"] == to]
        return jsonify(trains=trains)

    @app.route("/api/booking", methods=["POST"])
    def book():
        data = request.get_json(force=True)
        order = dict(data, id=len(_ORDERS) + 1, status="confirmed")
        _ORDERS.append(order)
        return jsonify(message="Order confirmed", order=order), 201

    @app.route("/api/booking/orders")
    def orders():
        return jsonify(orders=_ORDERS)

    return app
'''


@pytest.fixture
def app_code(tmp_path):
    code = tmp_path / "code" / "web"
    code.mkdir(parents=True)
    (code / "web.py").write_text(_WEBAPP, encoding="utf-8")
    project = tmp_path / "code"
    ok, report = run_smoke(project)
    assert ok, report  # 夹具自身先过基础冒烟
    return project


class _ScriptedLLM:
    """按序返回预设脚本；记录调用。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append(user[:60])
        return self.responses.pop(0) if self.responses else "raise SystemExit(1)"


_GOOD_BODY = '''\
resp = c.get("/api/health")
assert resp.status_code == 200, f"health: {resp.status_code}"
resp = c.get("/")
assert resp.status_code == 200 and b"Register" in resp.data, "home links"
resp = c.post("/api/auth/register", json={"username": "alice", "password": "wonderland"})
assert resp.status_code == 201, f"register: {resp.status_code} {resp.data}"
resp = c.post("/api/auth/login", json={"username": "alice", "password": "wonderland"})
assert resp.status_code == 200, f"login: {resp.status_code} {resp.data}"
resp = c.get("/api/search", query_string={"from_station": "Beijing South", "to_station": "Shanghai Hongqiao"})
trains = resp.get_json()["trains"]
assert resp.status_code == 200 and trains, f"search: {resp.data}"
number = trains[0]["number"]
resp = c.post("/api/booking", json={"train_number": number, "passenger": "Alice"})
assert resp.status_code == 201, f"book: {resp.status_code} {resp.data}"
resp = c.get("/api/booking/orders")
assert resp.get_json()["orders"], "orders empty"
'''


class TestProbeRoutes:
    def test_probe_finds_app_module_and_routes(self, app_code):
        probe = _probe_routes(app_code)
        assert probe is not None
        app_module, routes = probe
        assert app_module == "web"
        joined = "\n".join(routes)
        for expect in ("/api/health [GET]", "/api/auth/register [POST]",
                       "/api/booking/orders [GET]", "/ [GET]"):
            assert expect in joined, expect


class TestJourneyGate:
    def test_good_script_passes(self, app_code):
        notes: list[str] = []
        llm = _ScriptedLLM([_GOOD_BODY])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert ok, (notes, report)
        assert any("PASS" in n for n in notes)

    def test_script_self_repair_before_app_repair(self, app_code):
        """第一版脚本引用错误路由 → 自修复重生成 → PASS（不进 RepoFixer）。"""
        notes: list[str] = []
        llm = _ScriptedLLM([
            "resp = c.get('/api/nope')\nassert resp.status_code == 200",
            _GOOD_BODY,
        ])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert ok, (notes, report)
        assert len(llm.calls) == 2
        assert not any("RepoFixer" in n for n in notes)

    def test_broken_app_goes_to_fixer_then_fails(self, app_code, monkeypatch):
        """应用真坏（搜索永远 500）：两版脚本都过不了 → 进 RepoFixer →
        修复无效 → 最终 FAIL。"""
        broken = app_code / "web" / "web.py"
        broken.write_text(
            _WEBAPP.replace(
                'return jsonify(trains=trains)',
                'raise RuntimeError("db down")',
            ),
            encoding="utf-8",
        )

        class _FakeResult:
            ok = False
            rounds = 3

        fixed = {}

        class _FakeFixer:
            def __init__(self, llm, project_dir, test_cmd=None, max_rounds=3):
                fixed["test_cmd"] = test_cmd

            def fix(self, issue):
                fixed["called"] = True
                fixed["issue_has_output"] = "RuntimeError" in issue
                return _FakeResult()

        monkeypatch.setattr(
            "app.agents.repo_fixer.RepoFixer", _FakeFixer
        )
        notes: list[str] = []
        llm = _ScriptedLLM([_GOOD_BODY])  # 脚本本身正确，坏的是应用
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert not ok
        assert fixed.get("called") is True
        assert fixed.get("issue_has_output") is True
        # 修复验证命令 = 旅程脚本本身
        assert fixed["test_cmd"][-1].endswith(str(app_code))
        assert any("RepoFixer" in n for n in notes)

    def test_dangerous_script_rejected_then_regenerated(self, app_code):
        """带网络 import 的脚本被扫描拦截 → 重生成正常脚本 → PASS。"""
        notes: list[str] = []
        llm = _ScriptedLLM([
            "import socket\nresp = c.get('/api/health')\n"
            "assert resp.status_code == 200",
            _GOOD_BODY,
        ])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert ok, (notes, report)
        assert any("扫描拦截" in n for n in notes)

    def test_generation_infra_failure_skips_not_fails(self, app_code):
        """LLM 生成通道炸掉（基础设施故障）= SKIP：不判已绿应用死刑。"""
        notes: list[str] = []

        def _boom(system, user):
            raise RuntimeError("wall clock timed out")

        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", _boom, 3, notes
        )
        assert ok is True
        assert any("SKIP" in n for n in notes)

    def test_two_scan_rejections_skip(self, app_code):
        """两版脚本都被扫描拦截：SKIP 交人工，不进 RepoFixer 冤枉应用。"""
        bad = "import socket  # persist"
        notes: list[str] = []
        llm = _ScriptedLLM([bad, bad])
        ok, report = _journey_gate(
            app_code, app_code.parent, "t", llm, 3, notes
        )
        assert ok is True
        assert any("均不可执行" in n for n in notes)


class TestExtractBody:
    def test_strips_markdown_fence(self):
        assert _extract_body("```python\nx = 1\n```") == "x = 1"

    def test_plain_passthrough(self):
        assert _extract_body("x = 1") == "x = 1"


class TestSyntaxGuard:
    def test_prose_leak_body_regenerated_not_executed(self, app_code):
        """r5 取证：LLM 把说明文字漏进代码体（全角冒号 SyntaxError）
        → compile 预检就地重生成，绝不写入执行、不冤枉应用。"""
        notes: list[str] = []
        leak = "说明要点：\n    先访问首页\n    resp = c.get('/api/health')"
        llm = _ScriptedLLM([leak, _GOOD_BODY])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert ok, (notes, report)
        assert any("语法不合格" in n for n in notes)
        assert not any("RepoFixer" in n for n in notes)

    def test_two_syntax_failures_skip(self, app_code):
        notes: list[str] = []
        llm = _ScriptedLLM(["要点：这不是代码", "说明：仍然不是"])
        ok, report = _journey_gate(
            app_code, app_code.parent, "t", llm, 3, notes
        )
        assert ok is True
        assert any("均不可执行" in n for n in notes)


# ---- r7d 取证：修复可能把应用修残（业务路由全丢）→ 路由面退化守卫 ----


class TestRepairRouteGuard:
    def test_route_degradation_triggers_rollback(self, app_code, monkeypatch):
        """修复把路由删光（8→3）：终验 FAIL + 路由退化 → 回滚修复前状态。"""
        # 先破坏应用（搜索 500）让脚本失败、进入修复通道
        web = app_code / "web" / "web.py"
        web.write_text(
            _WEBAPP.replace(
                'return jsonify(trains=trains)',
                'raise RuntimeError("broken")',
            ),
            encoding="utf-8",
        )
        before = _probe_routes(app_code)
        assert before is not None and len(before[1]) >= 5

        class _FakeResult:
            ok = False
            rounds = 3

        class _VandalFixer:
            """模拟越修越残：把 web.py 覆盖成只剩 health 的空壳。"""

            def __init__(self, llm, project_dir, test_cmd=None, max_rounds=3):
                self.project_dir = project_dir

            def fix(self, issue):
                assert "不得删除任何既有路由" in issue  # 修复指令带路由面快照
                web = self.project_dir / "code" / "web" / "web.py"
                web.write_text(
                    "from flask import Flask, jsonify\n"
                    "def create_app():\n"
                    "    app = Flask(__name__)\n"
                    "    @app.route('/api/health')\n"
                    "    def h():\n        return jsonify(status='ok')\n"
                    "    return app\n",
                    encoding="utf-8",
                )
                return _FakeResult()

        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer", _VandalFixer)
        notes: list[str] = []
        llm = _ScriptedLLM([_GOOD_BODY])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert not ok  # 修复无效
        assert any("已回滚修复" in n for n in notes)
        # 回滚后路由面与修复前一致
        after = _probe_routes(app_code)
        assert after is not None and len(after[1]) == len(before[1])

    def test_route_guard_not_triggered_on_success(self, app_code, monkeypatch):
        """修复成功（旅程 PASS）：不触发回滚判定；终验用最佳脚本版本。"""

        class _FakeResultOk:
            ok = True
            rounds = 1

        # 破坏应用让脚本失败进修复；修复器把应用修回原样
        web = app_code / "web" / "web.py"
        original = web.read_text(encoding="utf-8")
        web.write_text(
            original.replace(
                'return jsonify(trains=trains)',
                'raise RuntimeError("broken")',
            ),
            encoding="utf-8",
        )

        class _RealishFixer:
            def __init__(self, llm, project_dir, test_cmd=None, max_rounds=3):
                self.web = project_dir / "code" / "web" / "web.py"

            def fix(self, issue):
                self.web.write_text(original, encoding="utf-8")
                return _FakeResultOk()

        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer", _RealishFixer)
        notes: list[str] = []
        llm = _ScriptedLLM([_GOOD_BODY])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert ok, (notes, report)
        assert not any("已回滚" in n for n in notes)


# ---- r8 取证：自修复脚本缩水迁就残缺应用 = 空心 PASS，必须拒收 ----


class TestShrinkGuard:
    def test_shrunk_repair_script_rejected_goes_to_fixer(self, app_code, monkeypatch):
        """v1 八步旅程在残缺应用上失败；v2 缩水成只查 health → 拒收 →
        进 RepoFixer（应用修复通道），而非放行空心 PASS。"""
        # 残缺应用：只有 health（注册/登录/搜索/订票全丢）
        web = app_code / "web" / "web.py"
        web.write_text(
            "from flask import Flask, jsonify\n"
            "def create_app():\n"
            "    app = Flask(__name__)\n"
            "    @app.route('/api/health')\n"
            "    def h():\n        return jsonify(status='ok')\n"
            "    return app\n",
            encoding="utf-8",
        )

        class _FakeResult:
            ok = False
            rounds = 3

        fixed = {}

        class _SpyFixer:
            def __init__(self, llm, project_dir, test_cmd=None, max_rounds=3):
                fixed["called"] = True

            def fix(self, issue):
                fixed["issue_head"] = issue[:60]
                return _FakeResult()

        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer", _SpyFixer)
        notes: list[str] = []
        good = _GOOD_BODY  # 八步全旅程
        shrunk = (
            "resp = c.get('/api/health')\n"
            "assert resp.status_code == 200, 'health'"
        )
        llm = _ScriptedLLM([good, shrunk])
        ok, report = _journey_gate(
            app_code, app_code.parent, "train ticket app", llm, 3, notes
        )
        assert not ok  # 残缺应用 + 修复无效 → 诚实 FAIL
        assert any("缩水被拒收" in n for n in notes)
        assert fixed.get("called") is True  # 走了应用修复而非放行


class TestScriptDefectClassification:
    """r11 取证：脚本 NameError 曾被当应用缺陷送 RepoFixer（误伤方向）。"""

    def test_nameerror_in_script_frame_is_script_defect(self):
        from app.arcbench_smoke import _is_script_defect

        report = (
            "Traceback (most recent call last):\n"
            '  File "C:/Temp/arcbench_journey.py", line 17, in <module>\n'
            "    c = client\n"
            "NameError: name 'client' is not defined"
        )
        assert _is_script_defect(report)

    def test_assertion_failure_is_not_script_defect(self):
        from app.arcbench_smoke import _is_script_defect

        report = (
            '  File "C:/Temp/arcbench_journey.py", line 20, in <module>\n'
            "    assert r.status_code == 201\n"
            "AssertionError: assert 404 == 201"
        )
        assert not _is_script_defect(report)

    def test_app_exception_without_script_frame_is_not(self):
        from app.arcbench_smoke import _is_script_defect

        report = "some app traceback\nTypeError: unsupported operand"
        assert not _is_script_defect(report)


class TestTracebackForensics:
    """轨迹取证（TESTING+PROPAGATE）后的分类精度：
    异常最深处帧决定归属——脚本帧=脚本缺陷，应用帧=应用缺陷。"""

    def test_app_side_typeerror_is_not_script_defect(self):
        from app.arcbench_smoke import _is_script_defect

        report = (
            "Traceback (most recent call last):\n"
            '  File "C:/Temp/arcbench_journey.py", line 30, in <module>\n'
            "    resp = c.post('/api/register', json=payload)\n"
            '  File "C:/app/auth/auth.py", line 92, in register_view\n'
            "    body, status = register(username, password)\n"
            '  File "C:/app/auth/auth.py", line 40, in register\n'
            "    raise TypeError('users table schema unsupported')\n"
            "TypeError: users table schema unsupported"
        )
        assert not _is_script_defect(report), "应用侧异常必须送应用修复"

    def test_script_side_nameerror_still_detected(self):
        from app.arcbench_smoke import _is_script_defect

        report = (
            "Traceback (most recent call last):\n"
            '  File "C:/Temp/arcbench_journey.py", line 29, in <module>\n'
            "    c = client\n"
            "NameError: name 'client' is not defined"
        )
        assert _is_script_defect(report)


# ---- keep7w 取证：旅程脚本直连数据库 / 302 误杀 → 生成期拦截家族 ----


class TestKeep7wGuards:
    def test_script_defect_regex_catches_sqlite_error(self):
        """脚本直连连错库（no such table）= 脚本缺陷，不送应用修复。"""
        report = (
            "Traceback (most recent call last):\n"
            '  File "C:/Temp/arcbench_journey.py", line 12, in <module>\n'
            '    row = db.execute("SELECT id FROM users").fetchone()\n'
            "sqlite3.OperationalError: no such table: users"
        )
        assert _is_script_defect(report)

    def test_journey_user_prompts_carry_new_rules(self):
        from app.arcbench_smoke import _JOURNEY_USER

        assert "follow_redirects=True" in _JOURNEY_USER
        assert "禁止 import sqlite3" in _JOURNEY_USER
        assert "禁止 import 应用内部模块" in _JOURNEY_USER

    def test_scan_blocks_sqlite_and_internal_imports(self, app_code):
        from app.arcbench_smoke import _journey_script_dangers

        body_bad = (
            "import sqlite3\n"
            "from web.web import bp\n"
            "resp = c.get('/api/health')\n"
        )
        dangers = _journey_script_dangers(body_bad, "web.web", app_code)
        assert any("sqlite3" in d for d in dangers)
        assert any("web" in d for d in dangers)

    def test_scan_passes_clean_body(self, app_code):
        from app.arcbench_smoke import _journey_script_dangers

        assert _journey_script_dangers(
            _GOOD_BODY, "app_main", app_code) == []

    def test_sqlite_body_intercepted_then_regen_passes(self, app_code):
        """v1 带 import sqlite3 → 扫描拦截重生成；v2 干净 → PASS，
        全程不进应用修复通道。"""
        notes: list[str] = []
        bad = "import sqlite3\ndb = sqlite3.connect('x.db')\n" + _GOOD_BODY
        llm = _ScriptedLLM([bad, _GOOD_BODY])
        ok, report = _journey_gate(
            app_code, app_code.parent, "t", llm, 3, notes
        )
        assert ok, (notes, report)
        assert any("扫描拦截" in n for n in notes)
        assert not any("RepoFixer" in n for n in notes)


# ---- 夜间压测取证：旅程摘要必须见到逐字验收，而非技术栈规则头部盲切 ----

class TestJourneyAcceptanceBrief:
    STRUCTURED = (
        "开发一个完整可运行的 Web 应用：Demo。\n演示应用。\n\n"
        "技术栈硬性要求（优先级最高）：\n"
        + "1. 后端必须创建真实 HTTP 服务器……\n" * 200
        + "\n## 模块：notes 笔记\n依赖：无\n\n"
        "### REQ-1.1 Create Note（验收标准）\n新建笔记。\n"
        "  - 场景：create\n    WHEN: click \"Create\"\n"
        "    THEN: see \"Note saved\" 提示\n\n"
        "### REQ-1.2 No GWT Node（验收标准）\n" + "长描述" * 100 + "\n"
    )

    def test_structured_gets_verbatim_acceptance(self):
        from app.arcbench_smoke import _journey_acceptance_brief
        brief = _journey_acceptance_brief(self.STRUCTURED)
        assert "Note saved" in brief
        assert '### REQ-1.1' in brief
        assert "【逐节点验收（原文逐字）】" in brief
        assert len(brief) < 6500
        assert "演示应用" in brief  # 应用简介头保留

    def test_plain_text_falls_back_to_head(self):
        from app.arcbench_smoke import _journey_acceptance_brief
        plain = "做一个备忘录应用。" * 1000
        assert _journey_acceptance_brief(plain) == plain[:4000]

    def test_desc_only_node_survives(self):
        from app.arcbench_smoke import _journey_acceptance_brief
        brief = _journey_acceptance_brief(self.STRUCTURED)
        assert "### REQ-1.2" in brief
        # 描述截到 240 字符（=80 个三字段），不拖爆预算
        assert brief.count("长描述") <= 81
