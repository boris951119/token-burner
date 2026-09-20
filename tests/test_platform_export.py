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
