# -*- coding: utf-8 -*-
"""刀O DB 内核：落盘、再导出、幂等、与作者文件共存。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.utils.db_kernel import ensure_db_kernel


def _load_kernel(code: Path):
    spec = importlib.util.spec_from_file_location(
        "uc_db_kernel_test", code / "_shared" / "db_kernel.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["uc_db_kernel_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ensure_lands_kernel_and_reexport(tmp_path: Path):
    code = tmp_path / "code"
    written = ensure_db_kernel(code)
    assert "_shared/db_kernel.py" in written
    assert "_shared/__init__.py(补再导出)" in written
    src = (code / "_shared" / "__init__.py").read_text(encoding="utf-8")
    assert "from _shared.db_kernel import" in src


def test_from_shared_import_get_db_works(tmp_path: Path):
    """sheet_p0 死因的直接回归：`from _shared import get_db` 必须可用。"""
    code = tmp_path / "code"
    ensure_db_kernel(code)
    sys.path.insert(0, str(code))
    try:
        mod = importlib.import_module("_shared")
        assert callable(mod.get_db) and callable(mod.init_app)
        conn = mod.get_db()
        conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
        conn.close()
    finally:
        sys.path.pop(0)
        sys.modules.pop("_shared", None)
        sys.modules.pop("_shared.db_kernel", None)


def test_idempotent(tmp_path: Path):
    code = tmp_path / "code"
    w1 = ensure_db_kernel(code)
    w2 = ensure_db_kernel(code)
    assert w1 and w2 == []


def test_author_get_db_not_overridden(tmp_path: Path):
    """作者已在 __init__ 显式定义 get_db → 不补再导出（不覆盖作者语义）。"""
    code = tmp_path / "code"
    shared = code / "_shared"
    shared.mkdir(parents=True)
    (shared / "__init__.py").write_text(
        "def get_db():\n    return 'author-version'\n", encoding="utf-8")
    written = ensure_db_kernel(code)
    assert "_shared/db_kernel.py" in written          # 内核仍落盘
    assert all("再导出" not in w for w in written)     # 但不补再导出
    sys.path.insert(0, str(code))
    try:
        mod = importlib.import_module("_shared")
        assert mod.get_db() == "author-version"       # 作者语义原样
    finally:
        sys.path.pop(0)
        sys.modules.pop("_shared", None)


def test_kernel_boots_with_flask_style_app(tmp_path: Path):
    code = tmp_path / "code"
    ensure_db_kernel(code)
    mod = _load_kernel(code)
    class FakeApp:
        def teardown_appcontext(self, fn):
            self._fn = fn
    app = FakeApp()
    mod.init_app(app)
    assert hasattr(app, "_fn") and callable(mod.get_db())
