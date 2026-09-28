# -*- coding: utf-8 -*-
"""入门表单×路由静态闸 + 接线收紧。"""

from __future__ import annotations

from pathlib import Path


def test_auth_form_routes_catches_post_login_only_in_main(tmp_path):
    from app.utils.auth_form_routes import check_auth_form_routes

    mod = tmp_path / "web_core"
    mod.mkdir()
    (mod / "__init__.py").write_text("", encoding="utf-8")
    (mod / "web_core.py").write_text(
        '''
from flask import Blueprint
_bp = Blueprint("web_core", __name__)

@_bp.route("/login")
def login_page():
    return """<form method="post" action="/login">
      <button type="submit">Sign In</button></form>"""

if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    @app.route("/login", methods=["POST"])
    def demo_login():
        return "ok"
''',
        encoding="utf-8",
    )
    issues = check_auth_form_routes(tmp_path)
    assert issues, "POST 只在 __main__ 必须红"
    assert "/login" in issues[0]


def test_auth_form_routes_green_when_post_on_blueprint(tmp_path):
    from app.utils.auth_form_routes import check_auth_form_routes

    mod = tmp_path / "web_core"
    mod.mkdir()
    (mod / "web_core.py").write_text(
        '''
from flask import Blueprint
_bp = Blueprint("web_core", __name__)

@_bp.route("/login", methods=["GET", "POST"])
def login_page():
    return """<form method="post" action="/login">
      <button>Sign In</button></form>"""
''',
        encoding="utf-8",
    )
    assert check_auth_form_routes(tmp_path) == []


def test_auth_form_routes_catches_v55_github_shape():
    """对照 9355 交付：web_core GET-only login + __main__ POST。"""
    from app.utils.auth_form_routes import check_auth_form_routes

    root = Path(
        "/Users/liuboyu/Developer/token-burner/.tmp/v55-9355/"
        "template/backend"
    )
    if not root.is_dir():
        return  # 本地无尸检树则跳过
    issues = check_auth_form_routes(root)
    assert issues
    assert "/login" in issues[0]
