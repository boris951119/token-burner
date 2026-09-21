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
