# -*- coding: utf-8 -*-
"""拼接机械化回归：Flask Blueprint / FastAPI APIRouter / 混合甄别。

9/20 泛化取证：装配器原为 Flask-only——生成项目出现 FastAPI 风格时
装配全盲（0 路由空壳）。
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.utils.mechanical_assembly import assemble


def _mk_pkg(code: pathlib.Path, name: str, body: str) -> None:
    pkg = code / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"{name}.py").write_text(body, encoding="utf-8")


FLASK_MOD = """
from flask import Blueprint
bp = Blueprint('x', __name__)
def init_db(app):
    pass
"""

FASTAPI_MOD = """
from fastapi import APIRouter
router = APIRouter()
@router.get('/items')
def items():
    return []
"""


def test_flask_project_assembles_blueprint(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FLASK_MOD)
    info = assemble(code)
    assert info["framework"] == "flask"
    assert info["blueprints"] == 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "register_blueprint" in gen
    assert "from flask import Flask" in gen


def test_fastapi_project_assembles_router(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD)
    info = assemble(code)
    assert info["framework"] == "fastapi", "纯 APIRouter 项目必须走 FastAPI 模板"
    assert info["routers"] == 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "include_router" in gen
    assert "from fastapi import FastAPI" in gen
    assert '"/api/health"' in gen


def test_fastapi_prefixed_router_import_detected(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD.replace(
        "from fastapi import APIRouter\nrouter = APIRouter()",
        "import fastapi\nrouter = fastapi.APIRouter()"))
    info = assemble(code)
    assert info["routers"] == 1, "fastapi.APIRouter(...) 属性式调用必须扫到"


def test_mixed_project_prefers_flask(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "fa", FLASK_MOD)
    _mk_pkg(code, "fb", FASTAPI_MOD)
    info = assemble(code)
    assert info["framework"] == "flask", "并存时 Blueprint 优先（见 assemble 注释）"


def test_generated_fastapi_app_imports_and_serves(tmp_path):
    """端到端：生成物可导入、路由真挂上（TestClient 实行为——
    本仓 FastAPI 版 include_router 摊平为 _IncludedRouter，不能靠
    扫 app.routes 断言）。"""
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD)
    assemble(code)
    sys.path.insert(0, str(code))
    try:
        from fastapi.testclient import TestClient
        import app_main.app_main as m
        client = TestClient(m.create_app())
        assert client.get("/api/health").status_code == 200
        assert client.get("/items").status_code == 200, \
            "include_router 必须把模块路由真接上"
    finally:
        sys.path.remove(str(code))
        sys.modules.pop("app_main.app_main", None)
        sys.modules.pop("app_main", None)
        sys.modules.pop("mod.mod", None)
        sys.modules.pop("mod", None)
