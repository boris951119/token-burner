# -*- coding: utf-8 -*-
"""冒烟建表接线检测回归（平台 v6-2 取证：users 表未建，注册崩溃，
health/首页双绿照样漏——冒烟必须覆盖 DDL 声明 vs 实际建表）。"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.arcbench_smoke import run_smoke


def _write(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


_APP_WIRED = '''\
import sqlite3
from flask import Flask, jsonify

_DB = None


def init_db():
    conn = sqlite3.connect("app.db")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def create_app():
    app = Flask(__name__)
    global _DB
    init_db()

    @app.route("/api/health")
    def health():
        return jsonify(status="ok")

    @app.route("/")
    def home():
        return "<a href='/list'>List</a> ok"

    return app
'''

_APP_UNWIRED = '''\
import sqlite3
from flask import Flask, jsonify


def init_db():
    """建表函数存在但没有任何人调用它（平台 v6-2 users 表形态）。"""
    conn = sqlite3.connect("app.db")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def create_app():
    app = Flask(__name__)

    @app.route("/api/health")
    def health():
        return jsonify(status="ok")

    @app.route("/")
    def home():
        return "<a href='/list'>List</a> ok"

    return app
'''


class TestSchemaWiringSmoke:
    def test_wired_app_passes(self, tmp_path):
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", _APP_WIRED)
        ok, report = run_smoke(code)
        assert ok, report
        assert "SMOKE_OK" in report or "health" in report

    def test_unwired_schema_fails_with_table_list(self, tmp_path):
        """DDL 声明了表但建表 init 未接线 → 冒烟 FAIL 且点名缺表。"""
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", _APP_UNWIRED)
        ok, report = run_smoke(code)
        assert not ok, "建表未接线必须被冒烟拦截"
        assert "users" in report, report
        assert "init" in report or "建表" in report

    def test_non_sqlite_app_unaffected(self, tmp_path):
        """无任何 DDL 声明的应用（非 sqlite 形态）零新增拦截。"""
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", _APP_WIRED.replace(
            'conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")\n    ', ""))
        ok, report = run_smoke(code)
        assert ok, report


# ---------------------------------------------------------------------------
# 9/21 BookStack 夜战取证三连（确定性拦截回归）
# ---------------------------------------------------------------------------

def _flask_app(home_body: str, login_route: bool = False,
               secret_key: bool = False) -> str:
    login_part = ""
    if login_route:
        login_part = '''
    @app.route("/login", methods=["GET", "POST"])
    def login():
        return "login"
'''
    key_part = "    app.secret_key = 'k'\n" if secret_key else ""
    return (
        "from flask import Flask, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        + key_part
        + "    @app.route('/api/health')\n"
        "    def h():\n        return jsonify(status='ok')\n"
        "    @app.route('/')\n"
        f"    def home():\n        return {home_body!r}\n"
        + login_part
        + "    return app\n"
    )


def _run(tmp_path, app_src: str):
    code = tmp_path / "code"
    _write(code / "app_mod" / "__init__.py",
           "from app_mod.app_mod import *  # noqa: F401,F403\n")
    _write(code / "app_mod" / "app_mod.py", app_src)
    return run_smoke(code)


class TestNightForensics:
    """首页死文本/壳页与 secret_key 缺失必须被冒烟确定性拦下。"""

    def test_missing_secret_key_with_login_route(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/l'>L</a>", login_route=True, secret_key=False))
        assert not ok
        assert "secret_key" in report

    def test_secret_key_present_passes(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/l'>L</a>", login_route=True, secret_key=True))
        assert ok, report

    def test_double_escaped_home(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "&lt;a href='/l'&gt;L&lt;/a&gt;"))
        assert not ok
        assert "双重" in report or "|safe" in report

    def test_unrendered_template_home(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "{{ body }} {% for x in y %}{% endfor %}"))
        assert not ok
        assert "模板" in report

    def test_linkless_home_is_placeholder(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app("Welcome to my site"))
        assert not ok
        assert "<a>" in report or "占位壳" in report


class TestAriaFieldAnchoring:
    """9/23 ARIA 取证：官方用例按 getByRole/getByLabel/getByPlaceholder
    定位，当期交付 placeholder 只有 2 处——定位不到的输入框等于不存在，
    功能写对了也零分。冒烟因此做一次纯机械的「可定位通道」体检。"""

    def test_bare_input_is_caught(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><form><input type='text' name='q'></form>"))
        assert not ok
        assert "可定位通道" in report
        assert "placeholder" in report and "<label" in report

    def test_placeholder_counts_as_channel(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><input type='search' placeholder='Search'>"))
        assert ok, report

    def test_label_for_pairs_even_when_written_after(self, tmp_path):
        """<label for> 常写在控件之后（模板顺序不该决定判分）。"""
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><input id='q' type='text'>"
            "<label for='q'>Query</label>"))
        assert ok, report

    def test_wrapping_label_counts_as_channel(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><label>Body <textarea rows='4'></textarea>"
            "</label>"))
        assert ok, report

    def test_non_text_input_ignored(self, tmp_path):
        """hidden/submit 这类不参与文本定位，不得误报（假红=白烧修复轮）。"""
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><form><input type='hidden' name='csrf'>"
            "<input type='submit' value='Go'></form>"))
        assert ok, report

    def test_id_alone_is_not_a_channel(self, tmp_path):
        """评分器不按属性名定位：有 id 而无 label 配对仍算落空。"""
        ok, report = _run(tmp_path, _flask_app(
            "<a href='/x'>X</a><input id='q' type='text'>"))
        assert not ok and "可定位通道" in report


def _fastapi_app(home_body: str) -> str:
    return (
        "from fastapi import FastAPI\n"
        "from fastapi.responses import HTMLResponse\n"
        "def create_app():\n"
        "    app = FastAPI()\n"
        "    @app.get('/api/health')\n"
        "    def h():\n        return {'status': 'ok'}\n"
        "    @app.get('/')\n"
        f"    def home():\n        return HTMLResponse({home_body!r})\n"
        "    @app.post('/')\n"
        "    def make():\n        return {'ok': True}\n"
        "    @app.get('/notes/{note_id}')\n"
        "    def note(note_id: int):\n        return {'id': note_id}\n"
        "    return app\n"
    )


class TestFastAPIPageCrawl:
    """9/23 取证：页面体检段直读 Flask 专有的 url_map——FastAPI 交付在这
    一行抛 AttributeError，整段冒烟猝死，后面的 DDL 缺表检查一并跑不到，
    修复环只拿到一段 traceback 而没有可执行判词。技术栈规则一直推荐
    「Flask 或 FastAPI」，双栈是这条推荐的义务。"""

    def test_fastapi_reaches_same_aria_gate(self, tmp_path):
        ok, report = _run(tmp_path, _fastapi_app(
            "<a href='/x'>X</a><input type='text' name='q'>"))
        assert not ok
        assert "可定位通道" in report

    def test_fastapi_anchored_input_passes(self, tmp_path):
        ok, report = _run(tmp_path, _fastapi_app(
            "<a href='/x'>X</a><input type='search' placeholder='Search'>"))
        assert ok, report

    def test_parameterised_and_post_routes_stays_out(self, tmp_path):
        """/notes/{id} 与 POST / 都不该被 GET 探（405/422 页体会污染体检）。"""
        ok, report = _run(tmp_path, _fastapi_app("<a href='/x'>X</a>"))
        assert ok, report


class TestHomeNavAffordance:
    """首页入口控件判据按「评测点得动」算，不按标签名（9/23 mini 彩排取证）。

    旧判据写死「首页必须有 <a>」：真需求「Enter Website 按钮 + JS 切区」的
    落地页因此判成占位壳页——评分器用 role 通道定位，按钮与链接同权。
    判据比官方紧一寸就是白烧一轮修复，还可能把合规页改坏。
    """

    def test_button_only_landing_page_passes(self, tmp_path):
        ok, report = _run(tmp_path, _flask_app(
            "<header><h1>ShortLink Desk</h1>"
            '<button id="enter-website-btn" type="button">Enter Website'
            "</button></header>"
            '<main><section id="directory" hidden><table>'
            "<thead><tr><th>Title</th></tr></thead><tbody id=\"rows\">"
            "</tbody></table></section></main>"))
        assert ok, report

    def test_role_button_without_anchor_passes(self, tmp_path):
        """无 <a> 无 <button>，只有 role 属性的 div：仍是同一条可点通道。"""
        ok, report = _run(tmp_path, _flask_app(
            '<div role="button" tabindex="0">Open board</div>'
            "<p>Sprint goals</p>"))
        assert ok, report

    def test_plain_text_home_still_placeholder(self, tmp_path):
        """反向：整页没有任何可点控件，仍旧判红（假绿防线）。"""
        ok, report = _run(tmp_path, _flask_app(
            "<h1>Welcome</h1><p>Nothing here yet.</p>"))
        assert not ok
        assert "占位壳" in report


def _app_src(extra_routes: str) -> str:
    """健康+带导航入口的合规首页，附加路由由用例给（其余判据保持全绿）。"""
    return (
        "from flask import Flask, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    @app.route('/api/health')\n"
        "    def h():\n        return jsonify(status='ok')\n"
        "    @app.route('/')\n"
        "    def home():\n        return \"<a href='/x'>X</a>\"\n"
        + extra_routes
        + "    return app\n"
    )


class TestApiGetCrashProbe:
    """9/23 mini 彩排尸检：交付的 GET /api/links 500（装配层把 db 路径字符
    串当成句柄传给 create_blueprint）——旧冒烟整段跳过 /api，页面异常还
    无条件 pass，于是本地全绿、评测列表步必死。无参 GET 的 5xx/异常从此
    硬判红；4xx 是按设计拒绝，不算病。"""

    def test_parameterless_api_500_fails_smoke(self, tmp_path):
        ok, report = _run(tmp_path, _app_src(
            "    @app.route('/api/links')\n"
            "    def links():\n"
            "        raise AttributeError(\"'str' object has no attribute"
            " 'list_links'\")\n"))
        assert not ok
        assert "无参 GET" in report, report
        assert "/api/links" in report, report

    def test_api_4xx_on_missing_args_still_passes(self, tmp_path):
        ok, report = _run(tmp_path, _app_src(
            "    @app.route('/api/links')\n"
            "    def links():\n"
            "        return jsonify(error='q required'), 400\n"))
        assert ok, report

    def test_page_exception_fails_smoke(self, tmp_path):
        """页面段同修：视图抛异常＝评测必死，不再静默吞。"""
        ok, report = _run(tmp_path, _app_src(
            "    @app.route('/board')\n"
            "    def board():\n        return 1 / 0\n"))
        assert not ok
        assert "/board" in report, report
