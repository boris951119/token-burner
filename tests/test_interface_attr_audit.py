# -*- coding: utf-8 -*-
"""属性级接口漂移审计（9/21 keep init_db/_init_db 取证回归）。"""
import json
from pathlib import Path

from app.utils.interface_attr_audit import (
    audit_attr_calls,
    module_symbols,
    audit_interface_drift,
    audit_interfaces_contract,
)


def _make_keep_shaped(tmp_path: Path) -> Path:
    """复刻 keep 事故形态：data_layer 包实现 _init_db，views 调 init_db。"""
    code = tmp_path / "code"
    dl = code / "data_layer"
    dl.mkdir(parents=True)
    views = code / "views"
    views.mkdir()
    (dl / "__init__.py").write_text(
        "from .data_layer import get_db, init_app\n", encoding="utf-8")
    (dl / "data_layer.py").write_text(
        "def get_db():\n"
        "    return {}\n"
        "\n"
        "\n"
        "def init_app(app):\n"
        "    pass\n"
        "\n"
        "\n"
        "def _init_db():\n"
        "    pass\n",
        encoding="utf-8")
    (views / "__init__.py").write_text("", encoding="utf-8")
    (views / "views.py").write_text(
        "import data_layer as _data_layer\n"
        "\n"
        "\n"
        "def boot(app):\n"
        "    _data_layer.init_app(app)\n"
        "    _data_layer.init_db()\n",
        encoding="utf-8")
    return tmp_path


def test_attr_call_flags_privacy_drift(tmp_path: Path):
    _make_keep_shaped(tmp_path)
    findings = audit_attr_calls(tmp_path / "code")
    assert any("views/views.py" in f and "init_db" in f for f in findings)
    assert any("_init_db" in f and "隐私错位" in f for f in findings)
    # 正确调用不误报
    assert not any("init_app" in f for f in findings)


def test_from_import_flags_hallucination(tmp_path: Path):
    code = tmp_path / "code"
    pkg = code / "store"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (code / "app_mod.py").write_text(
        "from store import load_seed_data\n", encoding="utf-8")
    findings = audit_attr_calls(code)
    assert any("load_seed_data" in f and "幻觉" in f for f in findings)


def test_interfaces_contract_two_way(tmp_path: Path):
    project = _make_keep_shaped(tmp_path)
    code = project / "code"
    (project / "interfaces.json").write_text(json.dumps({
        "data_layer": {"imports": [], "exports": ["get_db", "init_db"],
                       "public_api": [], "dependencies": []},
        "views": {"imports": ["load_seed_data"], "exports": ["boot"],
                  "public_api": [], "dependencies": []},
    }, ensure_ascii=False), encoding="utf-8")
    findings = audit_interfaces_contract(project)
    joined = "\n".join(findings)
    # exports 声明 init_db 但实现只有 _init_db → 契约/实现缺口
    assert any("data_layer" in f and "init_db" in f for f in findings)
    # imports 引用全仓不存在的符号 → 幻觉导入
    assert any("load_seed_data" in f and "幻觉" in f for f in findings)


def test_clean_project_silent(tmp_path: Path):
    project = _make_keep_shaped(tmp_path)
    # 修好：views 改调 _init_db，且包 __init__ 重导出该名（缺重导出时
    # data_layer._init_db 在真实 Python 里同样 AttributeError——审计器
    # 报得对，9/22 首轮运行实证）
    (project / "code" / "data_layer" / "__init__.py").write_text(
        "from .data_layer import get_db, init_app, _init_db\n",
        encoding="utf-8")
    v = project / "code" / "views" / "views.py"
    v.write_text(v.read_text(encoding="utf-8").replace(
        "_data_layer.init_db()", "_data_layer._init_db()"),
        encoding="utf-8")
    assert audit_attr_calls(project / "code") == []
    assert audit_interfaces_contract(project) == []
    assert audit_interface_drift(project / "code", project) == []


_SHIM_INIT = '''"""validator 包入口：包名即实现模块（属性读写与 validator.validator 同源）。"""
import sys as _sys

from . import validator as _impl

_impl.__path__ = __path__
_impl.validator = _impl
_sys.modules[__name__] = _impl
'''


def _pkg(tmp_path: Path, init_src: str) -> Path:
    """双形态包：实现模块有公开名 check，包入口按传入文本决定可见面。"""
    code = tmp_path / "code"
    pkg = code / "validator"
    pkg.mkdir(parents=True)
    (pkg / "validator.py").write_text(
        "def check(x):\n    return bool(x)\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(init_src, encoding="utf-8")
    return code


def test_pkg_shim_symbols_come_from_impl(tmp_path):
    """审计器认包名别名（file_manager _PKG_SHIM）：`from validator import
    check` 在运行时成立，报幻觉导入就是假红——与链接门禁同一族。"""
    assert "check" in module_symbols(_pkg(tmp_path, _SHIM_INIT))["validator"]


def test_plain_relative_import_still_hides_impl_symbols(tmp_path):
    """假绿防线：没有 sys.modules[__name__] 赋值时包名不等同实现模块，
    其内容不可见——可见面不许凭空放大。"""
    syms = module_symbols(
        _pkg(tmp_path, "from . import validator  # 只挂子模块名\n"))["validator"]
    assert "check" not in syms
    assert "validator" in syms
