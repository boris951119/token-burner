# -*- coding: utf-8 -*-
"""官方 runner 布局适配器回归（6 平台提交取证：布局违约主死因）。"""
from __future__ import annotations

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from app.platform_export import export_platform_layout


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    code = proj / "code"
    (code / "view").mkdir(parents=True)
    (code / "view" / "__init__.py").write_text("", encoding="utf-8")
    (code / "view" / "view.py").write_text(
        "def create_app():\n    pass\n", encoding="utf-8")
    static = code / "view" / "static"
    static.mkdir()
    (static / "style.css").write_text("body{}", encoding="utf-8")
    return proj


def test_backend_layout_complete(tmp_path, project):
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    backend = out / "backend"
    assert (backend / "main.py").is_file()
    assert (backend / "requirements.txt").is_file()
    assert (backend / "package.json").is_file()
    assert (backend / "view" / "view.py").is_file()
    assert (backend / "view" / "static" / "style.css").is_file(), \
        "非 py 资产必须随迁"
    assert summary["backend_files"] >= 5


def test_backend_entry_has_port_and_health_contract(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    entry = (out / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT"' in entry
    assert "create_app" in entry


def test_frontend_shell_buildable_shape(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    pkg = json.loads((out / "frontend" / "package.json").read_text(
        encoding="utf-8"))
    assert "build" in pkg["scripts"], "runner 只构建声明了 build 的前端"
    assert (out / "frontend" / "index.html").is_file()
    assert (out / "frontend" / "src" / "App.tsx").is_file()


def test_export_idempotent(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    export_platform_layout(out, project)  # 重复导出不抛错
    assert (out / "backend" / "main.py").is_file()


def test_missing_code_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_platform_layout(tmp_path / "out", tmp_path / "noproj")


@pytest.fixture
def fastapi_project(tmp_path):
    proj = tmp_path / "fproj"
    code = proj / "code"
    code.mkdir(parents=True)
    (code / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/api/health')\n"
        "def health():\n    return {'status': 'ok'}\n",
        encoding="utf-8")
    return proj


def test_project_main_preserved_as_project_main(tmp_path, fastapi_project):
    out = tmp_path / "out"
    export_platform_layout(out, fastapi_project)
    backend = out / "backend"
    # FastAPI 风格唯一入口在 main.py——runner 覆盖前必须保真
    assert (backend / "project_main.py").read_text(
        encoding="utf-8").startswith("from fastapi import FastAPI")
    entry = (backend / "main.py").read_text(encoding="utf-8")
    assert "wsgi_app" in entry and "uvicorn" in entry, \
        "runner 必须双框架起服"


def test_requirements_follow_frameworks(tmp_path, fastapi_project):
    out = tmp_path / "out"
    export_platform_layout(out, fastapi_project)
    reqs = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in reqs and "uvicorn" in reqs
    assert "flask" not in reqs, "纯 FastAPI 项目不必装 flask"

    # 混合项目（flask+fastapi import 并存）双依赖都要有
    fcode = fastapi_project / "code"
    (fcode / "mixed_pkg").mkdir()
    (fcode / "mixed_pkg" / "__init__.py").write_text("", encoding="utf-8")
    (fcode / "mixed_pkg" / "x.py").write_text(
        "from flask import Flask\n", encoding="utf-8")
    export_platform_layout(out, fastapi_project)
    reqs2 = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in reqs2 and "flask" in reqs2


def test_authored_app_entry_beats_create_app_factory(tmp_path):
    """作者入口（模块级 app）必须压过机械装配 create_app 壳——
    否则修复器修好的 main.py 被旁路，修复白做。"""
    import importlib.util

    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    # 机械装配壳：只有 health
    (be / "app_main").mkdir()
    (be / "app_main" / "__init__.py").write_text("", encoding="utf-8")
    (be / "app_main" / "app_main.py").write_text(
        "from flask import Flask, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    @app.route('/api/health')\n"
        "    def h():\n"
        "        return jsonify(status='ok')\n"
        "    return app\n", encoding="utf-8")
    # 作者入口：模块级 app，带业务路由
    (be / "project_main.py").write_text(
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "AUTHORED = True\n"
        "@app.route('/api/health')\n"
        "def h():\n"
        "    return jsonify(status='ok')\n"
        "@app.route('/books')\n"
        "def books():\n"
        "    return jsonify([])\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")

    spec = importlib.util.spec_from_file_location("runner_main", be / "main.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)      # 模块级执行即完成入口探测
        assert mod.app.name == "project_main", \
            "可导入的作者入口必须赢过 create_app 工厂"
        rules = {r.rule for r in mod.app.url_map.iter_rules()}
        assert "/books" in rules
    finally:
        # walker 把 app_main/project_main 等灌进了共享 sys.modules，
        # 不清会污染后续测试的同名导入（跨文件隔离取证）
        for name in list(sys.modules):
            if name.startswith(("app_main", "project_main", "runner_main")):
                sys.modules.pop(name, None)


# ---- 出口入口保底（9/23 keep r0 真产物取证）------------------------------
# 那份交付的整棵树里没有任何 create_app，也没有模块级 app：官方 runner 的
# 入口探测两遍全空 → SystemExit → 容器 exit 1 = **不评分**。首页写得再好
# 也换不到一分，而管线当时还「尽力交付」成功了——这一层不能交给概率。

@pytest.fixture
def entryless_project(tmp_path):
    proj = tmp_path / "eproj"
    code = proj / "code"
    (code / "records").mkdir(parents=True)
    (code / "records" / "__init__.py").write_text("", encoding="utf-8")
    (code / "records" / "records.py").write_text(
        "from flask import Blueprint\n"
        "bp = Blueprint('records', __name__)\n"
        "@bp.route('/records')\n"
        "def page():\n    return 'records page'\n", encoding="utf-8")
    return proj


def test_missing_entry_is_backfilled_at_export(tmp_path, entryless_project):
    out = tmp_path / "out"
    summary = export_platform_layout(out, entryless_project)
    assert summary["entry"] == "mechanical", "出口必须报告入口是保底壳"
    assert (out / "backend" / "app_main" / "app_main.py").is_file()
    reqs = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "flask" in reqs, "保底壳 import flask，依赖表得跟着补（缺=部署即死）"


def test_backfilled_artifact_boots_with_business_routes(tmp_path,
                                                        entryless_project):
    """保底不是「只求活着」：扫到的 Blueprint 必须真挂上，否则产物只剩
    /api/health，评测仍按可见文案全灭。"""
    import importlib.util

    out = tmp_path / "out"
    export_platform_layout(out, entryless_project)
    be = out / "backend"
    spec = importlib.util.spec_from_file_location(
        "runner_main_backfill", be / "main.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)          # 模块级执行即完成入口探测
        rules = {r.rule for r in mod.app.url_map.iter_rules()}
        assert "/records" in rules and "/api/health" in rules, rules
        assert mod.app.secret_key, "保底壳缺 secret_key：session 登录必 500"
    finally:
        for name in list(sys.modules):
            if name.startswith(("app_main", "records", "runner_main")):
                sys.modules.pop(name, None)


def test_author_entry_is_never_shadowed(tmp_path, project):
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    assert summary["entry"] == "author"
    assert not (out / "backend" / "app_main").exists(), \
        "作者入口在场时装配保底必须让位，不得旁路修复成果"
