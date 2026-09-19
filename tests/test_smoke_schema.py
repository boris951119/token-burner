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
        return "ok"

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
        return "ok"

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
