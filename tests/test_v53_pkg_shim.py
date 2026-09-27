# -*- coding: utf-8 -*-
"""v53 刀E：包 shim 不覆盖同名 callable + 同名子模块调用门禁。"""
from __future__ import annotations

import types

from app.tools.file_manager import FileManager
from app.utils.pkg_name_collision import check_pkg_name_call_collision


def test_shim_preserves_same_named_function(tmp_path):
    """d462 最小复现：def seed_accounts 不得被 _impl.seed_accounts=_impl 盖掉。"""
    fm = FileManager(projects_root=tmp_path / "projects")
    pid = fm.create_project("shim").project_id
    fm.write_code_file(
        pid, "seed_accounts", "seed_accounts.py",
        "def seed_accounts():\n    return 'fn'\n",
    )
    handle = fm.get_project(pid)
    code_root = handle.root / "code"
    init = (code_root / "seed_accounts" / "__init__.py").read_text(
        encoding="utf-8")
    assert "callable" in init
    assert '_sys.modules[__name__ + ".seed_accounts"]' in init

    import importlib
    import sys
    sys.path.insert(0, str(code_root))
    for k in list(sys.modules):
        if k.startswith("seed_accounts"):
            del sys.modules[k]
    from seed_accounts import seed_accounts as fn
    assert callable(fn) and not isinstance(fn, types.ModuleType)
    assert fn() == "fn"
    # 双键：import pkg.pkg 仍可达实现模块
    mod = importlib.import_module("seed_accounts.seed_accounts")
    assert mod.seed_accounts() == "fn"


def test_shim_still_self_aliases_when_no_same_named_callable(tmp_path):
    """无同名函数时仍自引用，保证 import pkg.pkg 与属性补丁同源。"""
    fm = FileManager(projects_root=tmp_path / "projects")
    pid = fm.create_project("shim2").project_id
    fm.write_code_file(
        pid, "cfg", "cfg.py",
        "CONST = 'orig'\n\ndef read():\n    return CONST\n",
    )
    handle = fm.get_project(pid)
    code_root = handle.root / "code"
    import sys
    sys.path.insert(0, str(code_root))
    for k in list(sys.modules):
        if k == "cfg" or k.startswith("cfg."):
            del sys.modules[k]
    import cfg
    import cfg.cfg as deep
    assert deep is cfg
    assert cfg.read() == "orig"


def test_collision_gate_reds_old_shim_call_site(tmp_path):
    code_root = tmp_path / "code"
    pkg = code_root / "seed_accounts"
    pkg.mkdir(parents=True)
    (pkg / "seed_accounts.py").write_text(
        "def seed_accounts():\n    return 1\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(
        '"""old"""\nimport sys as _sys\n'
        "from . import seed_accounts as _impl\n"
        "_impl.__path__ = __path__\n"
        "_impl.seed_accounts = _impl\n"
        "_sys.modules[__name__] = _impl\n",
        encoding="utf-8",
    )
    caller = (
        "from seed_accounts import seed_accounts as _seed\n"
        "def init_db():\n"
        "    _seed()\n"
    )
    issues = check_pkg_name_call_collision(
        caller, code_root=code_root, module="seed_bootstrap")
    assert issues and "同名冲突" in issues[0]


def test_collision_gate_greens_new_shim(tmp_path):
    fm = FileManager(projects_root=tmp_path / "projects")
    pid = fm.create_project("ok").project_id
    fm.write_code_file(
        pid, "seed_accounts", "seed_accounts.py",
        "def seed_accounts():\n    return 1\n",
    )
    code_root = fm.get_project(pid).root / "code"
    caller = (
        "from seed_accounts import seed_accounts as _seed\n"
        "def init_db():\n"
        "    _seed()\n"
    )
    assert check_pkg_name_call_collision(
        caller, code_root=code_root, module="seed_bootstrap") == []
