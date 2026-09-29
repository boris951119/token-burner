# -*- coding: utf-8 -*-
"""v53 刀A 调用签名 + 刀B 作者工厂试装（v54 P1-3 子进程）。"""
from __future__ import annotations

from pathlib import Path

from app.utils.call_arity import check_imported_call_arity
from app.utils.factory_pool import (
    probe_author_factories,
    probe_author_factories_safe,
)


def _pkg(root: Path, name: str, src: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / f"{name}.py").write_text(src, encoding="utf-8")


def test_call_arity_catches_seed_db_missing_conn(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _pkg(code, "db_seed", "def seed_db(conn):\n    pass\n")
    caller = (
        "from db_seed import seed_db\n"
        "def create_app():\n"
        "    seed_db()\n"
        "    return 1\n"
    )
    issues = check_imported_call_arity(
        caller, code_root=code, module="webui_app")
    assert issues
    assert issues[0].required == 1 and issues[0].given == 0


def test_call_arity_ok_when_arg_passed(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _pkg(code, "db_seed", "def seed_db(conn):\n    pass\n")
    caller = (
        "from db_seed import seed_db\n"
        "def create_app(conn):\n"
        "    seed_db(conn)\n"
    )
    assert check_imported_call_arity(
        caller, code_root=code, module="webui_app") == []


def test_call_arity_catches_excess_via_import_as(tmp_path):
    """81bc：import peer as alias + alias.fn(4 args) vs def fn(a, b)。"""
    code = tmp_path / "code"
    code.mkdir()
    _pkg(
        code,
        "worksheet_list_create_switch",
        "def create_worksheet_record(workbook_id, name):\n"
        "    return {'id': 1}\n",
    )
    caller = (
        "import worksheet_list_create_switch as _ws_sheets\n"
        "def create_workbook(db, name):\n"
        "    _ws_sheets.create_worksheet_record(db, 1, 'Sheet1', 0)\n"
    )
    issues = check_imported_call_arity(
        caller, code_root=code, module="workbook_list_create_open")
    assert issues, "超额实参应硬红"
    assert issues[0].given == 4 and issues[0].maximum == 2


def test_call_arity_ok_import_as_matching(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _pkg(
        code,
        "worksheet_list_create_switch",
        "def create_worksheet_record(workbook_id, name):\n"
        "    return {'id': 1}\n",
    )
    caller = (
        "import worksheet_list_create_switch as _ws_sheets\n"
        "def create_workbook(wb_id):\n"
        "    _ws_sheets.create_worksheet_record(wb_id, 'Sheet1')\n"
    )
    assert check_imported_call_arity(
        caller, code_root=code, module="workbook_list_create_open") == []


def test_probe_author_factory_reports_typeerror(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _pkg(code, "db_seed", "def seed_db(conn):\n    return conn\n")
    _pkg(
        code, "webui_app",
        "from db_seed import seed_db\n"
        "def create_app():\n"
        "    seed_db()\n"
        "    return object()\n",
    )
    _pkg(
        code, "app_main",
        "__arcbench_assembled__ = True\n"
        "def create_app():\n"
        "    return object()\n",
    )
    result = probe_author_factories(code)
    assert result["infra_error"] is False
    fails = result["failures"]
    assert fails
    assert any("webui_app" in f and "TypeError" in f for f in fails)
    assert not any("app_main" in f for f in fails)
    assert result["tried"] >= 1


def test_probe_author_factory_safe_ok(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _pkg(code, "webui_app",
         "def create_app():\n    return object()\n")
    issues, infra = probe_author_factories_safe(code)
    assert infra is False
    assert issues == []


def test_probe_subprocess_timeout_is_infra_fail(tmp_path, monkeypatch):
    """子进程超时 → fail-closed（带 probe基础设施失败 前缀）。"""
    import subprocess

    code = tmp_path / "code"
    code.mkdir()

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="py", timeout=240)

    monkeypatch.setattr(subprocess, "run", _boom)
    result = probe_author_factories(code)
    assert result["infra_error"] is True
    assert any("probe基础设施失败" in f for f in result["failures"])

    issues, infra = probe_author_factories_safe(code)
    assert infra is True
    assert any("probe基础设施失败" in f for f in issues)


def test_probe_subprocess_bad_json_is_infra_fail(tmp_path, monkeypatch):
    """子进程输出非 JSON → fail-closed。"""
    import subprocess
    from types import SimpleNamespace

    code = tmp_path / "code"
    code.mkdir()

    monkeypatch.setattr(
        subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(
            stdout="not-json-at-all\n", stderr="", returncode=0),
    )
    issues, infra = probe_author_factories_safe(code)
    assert infra is True
    assert any("probe基础设施失败" in f for f in issues)


def test_probe_green_exits_when_author_factory_red(tmp_path, monkeypatch):
    from app import arcbench_smoke as sm

    called = {"repair": 0}

    monkeypatch.setattr(
        "app.utils.factory_pool.probe_author_factories_safe",
        lambda *_a, **_k: (["webui_app.create_app: TypeError: boom"], False),
    )
    monkeypatch.setattr(sm, "run_form_probe", lambda *_a, **_k: [])
    monkeypatch.setattr(
        sm, "auto_repair",
        lambda *_a, **_k: called.__setitem__("repair", called["repair"] + 1)
        or (True, ""),
    )
    monkeypatch.setattr(sm, "run_smoke", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(sm, "run_journey_script",
                        lambda *_a, **_k: (True, "skip"))
    monkeypatch.setattr(sm, "run_all_fixers", lambda *_a, **_k: {})
    monkeypatch.setattr(sm, "collect_ddl", lambda *_a, **_k: {})
    monkeypatch.setattr(sm, "_repair_blocked", lambda: "")

    (tmp_path / "code").mkdir()
    _ok, report = sm.verify_delivery(
        tmp_path, "req", settings=type("S", (), {"models": []})(),
        probe_green=True, max_app_rounds=0, max_verify_rounds=0,
        repair_budget_s=30,
    )
    assert called["repair"] == 0
    assert "probe-fast→full" in report or "create_app" in report


def test_probe_parent_does_not_import_generated_code(tmp_path):
    """父进程不得把生成包塞进 sys.modules（P1-3 根因回归）。"""
    import sys

    code = tmp_path / "code"
    code.mkdir()
    # 故意起名叫 app——旧实现会 del sys.modules['app'] 毒死 agent
    _pkg(code, "app",
         "def create_app():\n    raise RuntimeError('gen boom')\n")
    before = {k for k in sys.modules if k == "app" or k.startswith("app.")}
    result = probe_author_factories(code)
    after = {k for k in sys.modules if k == "app" or k.startswith("app.")}
    assert after == before, "父进程 sys.modules 被生成包污染"
    assert result["infra_error"] is False
    assert any("RuntimeError" in f for f in result["failures"])
