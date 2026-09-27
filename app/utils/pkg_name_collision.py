# -*- coding: utf-8 -*-
"""包/子模块同名被当函数调用的门禁（v53 刀E）。

d462：`from seed_accounts import seed_accounts` 在旧 `_PKG_SHIM` 下绑定到
模块对象，`seed_accounts()` → TypeError。shim 已修；本闸拦两类残留：

1. 包 `__init__` 仍是无条件 `_impl.X = _impl`（旧 shim / 手写回退）；
2. 无包名别名时 `from X import Y` 本就导入子模块，再 `Y()` 必炸。

`from X import Y` + 调用 Y，且 Y 可解析为 X 的子模块 → 按上列判红。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


_UNCONDITIONAL_SELF_REF = re.compile(
    r"_impl\.(?P<name>\w+)\s*=\s*_impl\b"
)
_HAS_CALLABLE_GUARD = re.compile(
    r"callable\s*\(\s*_existing\s*\)|not callable\s*\("
)


def _is_submodule(code_root: Path, pkg: str, name: str) -> bool:
    root = Path(code_root)
    if (root / pkg / f"{name}.py").is_file():
        return True
    if (root / pkg / name / "__init__.py").is_file():
        return True
    return False


def _pkg_init(code_root: Path, pkg: str) -> str | None:
    p = Path(code_root) / pkg / "__init__.py"
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _dangerous_shim(init_src: str | None, name: str) -> bool:
    """旧无条件自引用，或根本没有 sys.modules 包名别名。"""
    if not init_src:
        return True  # 无别名：from pkg import name → 子模块
    if _HAS_CALLABLE_GUARD.search(init_src):
        # 新 shim：同名函数可安全 from pkg import name
        return False
    if f"_sys.modules[__name__]" not in init_src and "sys.modules[__name__]" not in init_src:
        return True
    for m in _UNCONDITIONAL_SELF_REF.finditer(init_src):
        if m.group("name") == name:
            return True
    return False


def check_pkg_name_call_collision(
    code: str,
    *,
    code_root: Path | None,
    module: str = "",
) -> list[str]:
    """返回问题列表（空=通过）。"""
    if not code_root or not Path(code_root).is_dir() or not (code or "").strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    # local_name → (pkg, imported_name)
    imported: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.level:
            continue
        pkg = node.module.split(".")[0]
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            imported[local] = (pkg, alias.name)

    if not imported:
        return []

    issues: list[str] = []
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    for local, (pkg, name) in imported.items():
        if local not in called:
            continue
        if not _is_submodule(Path(code_root), pkg, name):
            continue
        init_src = _pkg_init(Path(code_root), pkg)
        if not _dangerous_shim(init_src, name):
            continue
        where = f"模块 {module} " if module else ""
        issues.append(
            f"函数与包同名冲突（{where}from {pkg} import {name} 后调用）："
            f"{name} 可解析为 {pkg} 的子模块，当前包入口会把它绑成 "
            f"module 对象 → TypeError: 'module' object is not callable。"
            f"修复：包 shim 不得覆盖同名 callable，或把函数改成非包名"
            f"（如 seed/run）并用 from {pkg} import <新名>"
        )
    return issues
