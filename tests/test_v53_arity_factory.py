# -*- coding: utf-8 -*-
"""v53 刀A 调用签名 + 刀B 作者工厂试装。"""
from __future__ import annotations

from pathlib import Path

from app.utils.call_arity import check_imported_call_arity
from app.utils.factory_pool import probe_author_factories


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
    fails = probe_author_factories(code)
    assert fails
    assert any("webui_app" in f and "TypeError" in f for f in fails)
    assert not any("app_main" in f for f in fails)


def test_probe_green_exits_when_author_factory_red(tmp_path, monkeypatch):
    from app import arcbench_smoke as sm

    called = {"repair": 0}

    monkeypatch.setattr(
        "app.utils.factory_pool.probe_author_factories",
        lambda *_a, **_k: ["webui_app.create_app: TypeError: boom"],
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
