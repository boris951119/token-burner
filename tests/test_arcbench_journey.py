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
    _journey_gate,
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

    @app.route("/api/health")
    def health():
        return jsonify(status="ok")

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
