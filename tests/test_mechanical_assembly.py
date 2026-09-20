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
    # 防跨测试 sys.modules 污染：先清同名残留再导入本例产物
    for name in list(sys.modules):
        if name.startswith(("app_main", "mod")):
            sys.modules.pop(name, None)
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


def test_scaffold_creates_stubs_for_frozen_only_and_idempotent(tmp_path):
    """契约层 v0：冻结包得存根；已有路由的包不动；幂等且不覆盖修复器写入。"""
    from app.utils.mechanical_assembly import assemble, scaffold_frozen_modules, scan_surfaces

    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "frozen_a", "# 无路由定义\n")
    _mk_pkg(code, "authed", FLASK_MOD)          # 已有 Blueprint+init
    # 第一遍：只有 frozen_a 拿存根
    created = scaffold_frozen_modules(code, scan_surfaces(code))
    assert created == ["frozen_a/frozen_a_routes.py"]
    stub = code / "frozen_a" / "frozen_a_routes.py"
    assert "Blueprint" in stub.read_text(encoding="utf-8")
    # 修复器往存根里写了 handler
    stub.write_text(
        stub.read_text(encoding="utf-8")
        + '\n@bp.route("/a")\ndef a():\n    return "A"\n',
        encoding="utf-8")
    # 第二遍：幂等，不覆盖（修复器内容保留）
    created2 = scaffold_frozen_modules(code, scan_surfaces(code))
    assert created2 == []
    assert '@bp.route("/a")' in stub.read_text(encoding="utf-8")


def test_assemble_scaffold_registers_stub_and_route_lives(tmp_path):
    """scaffold=True：存根蓝图进 app_main，修复器写入的路由真生效。"""
    from fastapi.testclient import TestClient  # noqa: F401  （flask 路径用 flask client）

    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "pages", "# 冻结\n")
    assemble(code, scaffold=True)
    # 修复器往存根写页面路由
    stub = code / "pages" / "pages_routes.py"
    stub.write_text(
        stub.read_text(encoding="utf-8")
        + '\n@bp.route("/pages")\ndef pages():\n    return "PAGES"\n',
        encoding="utf-8")
    # 下一轮脚手架重装配（app_main 再生，存根保留）
    info = assemble(code, scaffold=True)
    assert info["blueprints"] >= 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "pages_routes" in gen, "存根蓝图必须注册进 app_main"
    # 行为验证
    for name in list(sys.modules):
        if name.startswith(("app_main", "pages")):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(code))
    try:
        import app_main.app_main as m
        client = m.create_app().test_client()
        assert client.get("/pages").status_code == 200
        assert client.get("/pages").data == b"PAGES"
        assert client.get("/api/health").status_code == 200
    finally:
        sys.path.remove(str(code))
        for name in list(sys.modules):
            if name.startswith(("app_main", "pages")):
                sys.modules.pop(name, None)
