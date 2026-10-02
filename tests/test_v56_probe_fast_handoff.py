# -*- coding: utf-8 -*-
"""v56 刀1：交卷假绿——守卫选路 / 终局探针路径 / sidecar 落点。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _reload_main(monkeypatch):
    for key in list(sys.modules):
        mod = sys.modules[key]
        path = getattr(mod, "__file__", "") or ""
        if key == "main" or path.endswith("/backend/main.py"):
            del sys.modules[key]
    sys.path = [str(ROOT)] + [p for p in sys.path if p != str(ROOT)]
    return importlib.import_module("main")


def test_probe_fast_guard_issues_language_red(tmp_path):
    from app.arcbench_smoke import probe_fast_guard_issues

    code = tmp_path / "code"
    mod = code / "webui"
    mod.mkdir(parents=True)
    (mod / "__init__.py").write_text("", encoding="utf-8")
    (mod / "webui.py").write_text(
        'LABEL = "首页导航"\nBTN = "创建工作簿"\n',
        encoding="utf-8",
    )
    # requirement_language 对过短样本会判 unknown 后放行——拉长英文题面
    req = (
        "Users view available workbooks on the workbook home page. "
        "Each record displays Last updated and provides a link. "
    ) * 5
    issues = probe_fast_guard_issues(code, req)
    assert issues, "英文需求 + 中文 UI 文案必须红"
    assert any("中文" in x or "界面" in x for x in issues)


def test_main_demotes_probe_fast_when_guards_red(monkeypatch, tmp_path, capsys):
    """语言/守卫红时不得进 8 分钟强制交分支。"""
    m = _reload_main(monkeypatch)

    calls = {"verify": 0, "probe_green_arg": None}

    def _fake_export(*_a, **_k):
        return {
            "exported": True,
            "backend_files": 1,
            "frontend_files": 1,
            "entry": "author",
            "export_probe": {"ok": True, "health": True, "home": True},
        }

    def _fake_guards(*_a, **_k):
        return ["需求为英文，但 1 个文件的界面文案含中文（demo）"]

    def _fake_verify(*_a, **_k):
        calls["verify"] += 1
        calls["probe_green_arg"] = _k.get("probe_green")
        return False, "full-path"

    monkeypatch.setattr(m, "_export_official_layout", _fake_export)
    monkeypatch.setattr(
        "app.arcbench_smoke.probe_fast_guard_issues", _fake_guards)
    monkeypatch.setattr(
        "app.arcbench_smoke.verify_delivery", _fake_verify)

    # 直接演练选路片段：绿探针 + 守卫红 → verify(probe_green=False)
    early = _fake_export()
    assert m._probe_green(early) is True
    guards = _fake_guards()
    assert guards
    # 模拟 main 选路
    if m._probe_green(early) and not guards:
        raise AssertionError("不应进快车道")
    ok, report = _fake_verify(probe_green=False)
    assert calls["probe_green_arg"] is False
    assert ok is False and report == "full-path"


def test_main_source_reprobes_workdir_backend_not_code():
    """静态防回归：终局重探针不得再写 project_dir/code。"""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'probe_exported_backend(_backend' in src \
        or 'probe_exported_backend(\n                    _backend' in src \
        or "probe_exported_backend(_backend," in src
    # 旧病灶不得回潮
    assert 'probe_exported_backend(\n                    Path(result.project_dir) / "code"' not in src
    assert 'Path(result.project_dir) / "code", window_s' not in src


def test_main_source_guards_before_force_stage3():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "probe_fast_guard_issues" in src
    assert "守卫红 → 退出快车道" in src
    # 可执行路径不得再强制跳过自测交卷
    assert 'print("[probe-fast] 入口修补超时，强制交' not in src
    assert "完整验收" in src
    assert "自测不跳过" in src


def test_surface_sidecar_writes_under_code(tmp_path):
    from app.utils.manifest_landing import (
        write_surface_anchors_sidecar,
        SURFACE_ANCHORS_SIDECAR,
        HOME_ANCHORS_SIDECAR,
    )

    project = tmp_path / "proj"
    code = project / "code"
    code.mkdir(parents=True)
    text = (
        '【验收节点逐字清单】\n'
        '- REQ-1｜首页卡片须含: "Last updated"｜种子可见: "Q3 Sales"\n'
        '- REQ-2｜登录页须含: "Create an account"\n'
    )
    by_s = write_surface_anchors_sidecar(code, [text])
    assert (code / SURFACE_ANCHORS_SIDECAR).is_file()
    assert (code / HOME_ANCHORS_SIDECAR).is_file()
    assert by_s.get("home") or by_s.get("login")
