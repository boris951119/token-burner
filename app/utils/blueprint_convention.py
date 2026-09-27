# -*- coding: utf-8 -*-
"""蓝图顶层 `_bp` 惯例门禁（v53 刀D）。

045fe：机械装配只认模块顶层 Blueprint 变量；20 个 API 模块仅 3 个导出
顶层 `_bp`，其余把路由藏在函数内 Flask() / create_*_blueprint()，
app_main 只挂上 3/20 → API 全 404。

本闸：模块内存在 `@*.route(` 装饰却无顶层 `_bp = Blueprint(...)` →
硬红；入口工厂（含 `create_app` + `register_blueprint`）除外。
"""
from __future__ import annotations

import ast


_FIX_HINT = (
    "把路由迁到模块顶层 `_bp = Blueprint(\"<模块名>\", __name__)`，"
    "用 `@_bp.route(...)` 注册；装配层只认顶层 `_bp`，"
    "禁止把路由藏在函数内构建的 app / 别名蓝图里"
)


def check_blueprint_convention(code: str, *, module: str = "") -> list[str]:
    """返回问题列表（空=通过）。"""
    if not (code or "").strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    has_top_bp = False
    has_create_app = False
    has_register_bp = "register_blueprint" in code
    route_lines: list[int] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id == "_bp"
                    and isinstance(node.value, ast.Call)
                ):
                    fn = (getattr(node.value.func, "id", "")
                          or getattr(node.value.func, "attr", ""))
                    if fn == "Blueprint":
                        has_top_bp = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "create_app":
                has_create_app = True

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # @x.route(...) / @x.get(...) 等
            call = dec if isinstance(dec, ast.Call) else None
            attr = None
            if call is not None and isinstance(call.func, ast.Attribute):
                attr = call.func
            elif isinstance(dec, ast.Attribute):
                attr = dec
            if attr is None:
                continue
            if attr.attr in ("route", "get", "post", "put", "patch",
                             "delete", "head", "options"):
                route_lines.append(getattr(node, "lineno", 0) or 0)

    if not route_lines:
        return []
    # 入口工厂负责组装，路由可在 create_app 内挂载
    if has_create_app and has_register_bp:
        return []
    if has_top_bp:
        return []
    where = f"模块 {module}" if module else "本模块"
    sample = f"L{route_lines[0]}" if route_lines[0] else "路由装饰"
    return [
        f"蓝图惯例硬红（{where} {sample}）：存在 @*.route 装饰但无顶层 "
        f"`_bp = Blueprint(...)`——{_FIX_HINT}"
    ]
