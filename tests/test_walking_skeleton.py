# -*- coding: utf-8 -*-
"""刀L 行走骨架：装配复用、起服冒烟、坏模块隔离、层冒烟留痕。"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from app.utils.walking_skeleton import (
    SKELETON_LOG, build_skeleton, layer_smoke, should_build_skeleton,
    smoke_skeleton,
)

_BROKEN_MODULE = "this is not python(((\n"


def _plan(name: str):
    return types.SimpleNamespace(name=name)


def _write_module(code: Path, name: str, path: str) -> None:
    """业务模块的真实形态是包（code/<name>/__init__.py）——扫描器只认包。"""
    fn = path.replace("/", "_").strip("_") or "index"
    pkg = code / name
    pkg.mkdir(parents=True, exist_ok=True)
    init = pkg / "__init__.py"
    if not init.is_file():
        init.write_text("", encoding="utf-8")
    (pkg / f"{name}.py").write_text(
        f'from flask import Blueprint, jsonify\n\n'
        f'bp = Blueprint({name!r}, __name__)\n\n\n'
        f'@bp.route({path!r})\n'
        f'def {fn}():\n'
        f'    return jsonify(module={name!r})\n',
        encoding="utf-8")


@pytest.fixture()
def code_dir(tmp_path: Path) -> Path:
    d = tmp_path / "code"
    d.mkdir()
    return d


def test_should_build_skeleton_only_for_multi_module():
    assert not should_build_skeleton([_plan("only")])
    assert should_build_skeleton([_plan("a"), _plan("b")])


def test_build_skeleton_writes_assembled_entry_and_shell(code_dir: Path):
    _write_module(code_dir, "store", "/api/store")
    _write_module(code_dir, "ui", "/ui")
    summary = build_skeleton(code_dir, [_plan("store"), _plan("ui")])
    assert summary["framework"] == "flask"
    main_py = code_dir / "app_main" / "app_main.py"
    assert main_py.is_file()
    src = main_py.read_text(encoding="utf-8")
    assert "__arcbench_assembled__" in src  # 交付段作者入口在场时让位
    assert (code_dir / "skeleton_shell" / "shell.py").is_file()
    assert "skeleton_shell" in src  # 诊断壳已挂进装配清单
    compile(src, "app_main", "exec")  # 语法自证


def test_smoke_skeleton_boots_and_probes(code_dir: Path):
    _write_module(code_dir, "store", "/api/store")
    build_skeleton(code_dir, [_plan("store")])
    rep = smoke_skeleton(code_dir)
    assert rep["ok"] is True, rep
    assert rep["health"] == 200
    assert rep["home"] == 200
    assert isinstance(rep["routes"], int) and rep["routes"] >= 4


def test_skeleton_survives_broken_module(code_dir: Path):
    """坏模块不连坐：装配不炸 + 好模块照常挂载 + 骨架照常起服。"""
    _write_module(code_dir, "good", "/api/good")
    bad = code_dir / "broken"
    bad.mkdir()
    (bad / "__init__.py").write_text("", encoding="utf-8")
    (bad / "impl.py").write_text(_BROKEN_MODULE, encoding="utf-8")
    summary = build_skeleton(
        code_dir, [_plan("good"), _plan("broken")])
    assert summary["framework"] == "flask"
    rep = smoke_skeleton(code_dir)
    assert rep["ok"] is True, rep
    assert rep["routes"] is not None and rep["routes"] >= 4


def test_skeleton_empty_code_still_boots(code_dir: Path):
    """开发起点（除壳外无任何模块）骨架也必须活着——这是它的存在意义。"""
    summary = build_skeleton(code_dir, [_plan("a"), _plan("b")])
    assert summary["framework"] == "flask"
    rep = smoke_skeleton(code_dir)
    assert rep["ok"] is True, rep


def test_layer_smoke_accumulates_routes_and_logs(code_dir: Path, tmp_path: Path):
    plans = [_plan("store"), _plan("ui")]
    build_skeleton(code_dir, plans)  # 起点：无业务模块
    r1 = layer_smoke(code_dir, plans, 1, sessions_dir=tmp_path)
    assert r1["ok"] is True and r1["routes_delta"] is None
    _write_module(code_dir, "store", "/api/store")
    r2 = layer_smoke(code_dir, plans, 2, sessions_dir=tmp_path,
                     last_routes=r1["routes"])
    assert r2["ok"] is True
    assert r2["routes"] > r1["routes"]  # 新层挂上后路由只增
    assert r2["routes_delta"] == r2["routes"] - r1["routes"]
    log = (tmp_path / SKELETON_LOG).read_text(encoding="utf-8")
    assert "层1" in log and "层2" in log


def test_shell_status_endpoint_reflects_routes(code_dir: Path):
    """诊断壳 status JSON 与冒烟读数同源：路由数、期望模块清单可见。"""
    _write_module(code_dir, "store", "/api/store")
    plans = [_plan("store"), _plan("ui")]
    build_skeleton(code_dir, plans)
    rep = smoke_skeleton(code_dir)
    assert rep["ok"] is True
    status = rep["status"]
    assert status and status["ok"] is True
    assert status["routes"] == rep["routes"]
    assert status["expected_modules"] == ["store", "ui"]
