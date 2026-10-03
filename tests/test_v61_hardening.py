# -*- coding: utf-8 -*-
"""v61.2 可选加固回归（5d05 尸检同族预防，outbox 第 6 节清单）。

①入口 CTA 去重扩展：Sign in 之外 Create an account 也必须恰好 1
  （smoke 闸 + 导出 after_request 两个站点）；
②_force_webui_index 劫持清除：before_request 拦 '/' 强转 index() 的
  窄形态在导出时移除（形态对不齐不动刀）；
③入口可达闸：GET / 页内 <a href> 逐个探测，非 2xx/3xx 记失败
  （/signup 404 教训：官方真实点击首页链接）。
"""
from __future__ import annotations

from pathlib import Path

from app.platform_export import _strip_force_index_hijack
from app.utils.surface_anchor_sanitize import (
    collapse_exact_named_links,
    count_exact_named_links,
)

HIJACK = '''from flask import Flask, request

app = Flask(__name__)


@app.route("/")
def index():
    return "<html><body>home</body></html>"


@app.before_request
def _force_webui_index():
    if request.path == "/":
        try:
            return index()
        except Exception:
            return None
    return None


@app.route("/other")
def other():
    return "ok"
'''


class TestDedupCreateAccount:
    def test_count_and_collapse_both_ctas(self):
        html = ('<a href="/login">Sign in</a> x '
                '<a href="/login">Sign in</a> y '
                '<a href="/register">Create an account</a> '
                '<a href="/register">Create an account</a>')
        assert count_exact_named_links(html, "Sign in") == 2
        assert count_exact_named_links(html, "Create an account") == 2
        out = collapse_exact_named_links(html, "Sign in")
        out = collapse_exact_named_links(out, "Create an account")
        assert count_exact_named_links(out, "Sign in") == 1
        assert count_exact_named_links(out, "Create an account") == 1

    def test_smoke_gate_pins_both_ctas(self):
        src = Path(
            __import__("app.arcbench_smoke", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        assert '"Sign in", "Create an account"' in src, \
            "smoke 闸必须同时检查两个入口 CTA（v61.1 只查了 Sign in）"

    def test_export_wrap_pins_both_ctas(self):
        src = Path(
            __import__("app.platform_export", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        assert '"Sign in", "Create an account"' in src, \
            "导出 after_request 去重必须覆盖两个入口 CTA"


class TestStripForceIndexHijack:
    def test_removes_hijack_keeps_routes(self, tmp_path):
        py = tmp_path / "webui.py"
        py.write_text(HIJACK, encoding="utf-8")
        changed = _strip_force_index_hijack(tmp_path)
        assert changed == ["webui.py"]
        out = py.read_text(encoding="utf-8")
        assert "_force_webui_index" not in out
        assert "before_request" not in out
        assert '@app.route("/")' in out, "正常路由不得误伤"
        assert '@app.route("/other")' in out
        compile(out, "webui.py", "exec"), "清除后必须仍是合法 Python"

    def test_leaves_unrelated_code_alone(self, tmp_path):
        clean = 'from flask import Flask\n\napp = Flask(__name__)\n'
        (tmp_path / "main.py").write_text(clean, encoding="utf-8")
        assert _strip_force_index_hijack(tmp_path) == []
        assert (tmp_path / "main.py").read_text() == clean

    def test_other_before_request_survives(self, tmp_path):
        """同名之外的 before_request（如 g.session）不得误删。"""
        src = HIJACK.replace("_force_webui_index", "_load_session")
        py = tmp_path / "webui.py"
        py.write_text(src, encoding="utf-8")
        assert _strip_force_index_hijack(tmp_path) == []
        assert (tmp_path / "webui.py").read_text() == src


class TestPromptPins:
    def test_write_code_bans_before_request_hijack(self):
        root = Path(__file__).resolve().parents[1]
        src = (root / "app" / "prompts" / "write_code_system.md").read_text(
            encoding="utf-8")
        assert "before_request" in src and "_force_webui_index" in src
        assert "必须真实注册在" in src


# ---- ③入口可达闸（/signup 404 教训）：run_smoke 全链路 ----

def _run_smoke(tmp_path, home_body: str):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.test_smoke_schema import _run
    return _run(tmp_path, (
        "from flask import Flask, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    @app.route('/api/health')\n"
        "    def h():\n        return jsonify(status='ok')\n"
        "    @app.route('/login')\n"
        "    def login():\n        return 'login'\n"
        "    @app.route('/')\n"
        f"    def home():\n        return {home_body!r}\n"
        "    return app\n"))


class TestEntryReachability:
    def test_dead_link_is_flagged(self, tmp_path):
        ok, report = _run_smoke(
            tmp_path, '<a href="/login">Sign in</a>'
                      '<a href="/ghost">Modules</a>')
        assert not ok
        assert "入口可达闸" in report
        assert "/ghost" in report

    def test_live_links_pass(self, tmp_path):
        ok, report = _run_smoke(
            tmp_path, '<a href="/login">Sign in</a>'
                      '<a href="/login?next=1">Sign in again</a>')
        assert "入口可达闸" not in report, report

    def test_anchors_and_external_skipped(self, tmp_path):
        ok, report = _run_smoke(
            tmp_path, '<a href="#top">Top</a>'
                      '<a href="https://x.example">Ext</a>'
                      '<a href="mailto:a@b.c">Mail</a>')
        assert "入口可达闸" not in report, report
