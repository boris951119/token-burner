# -*- coding: utf-8 -*-
"""蓝图顶层惯例门禁（v53 刀D；v53.1 与装配同构放宽；v56-5 认 _bp 工厂）。

045fe：机械装配只认模块顶层 Blueprint 变量；20 个 API 模块仅 3 个导出
顶层 `_bp`，其余把路由藏在函数内 Flask() / create_*_blueprint()，
app_main 只挂上 3/20 → API 全 404。

v53.1（Cursor 对质修正）：装配扫描本就认**任意**顶层 `X = Blueprint(...)`
（按变量名收，不限 `_bp`），冻结存根也生成 `bp`——门禁若只认 `_bp` 会
误伤合法形态。本闸放宽为：有路由装饰但**无任何顶层 Blueprint 赋值** →
硬红；`_bp` 命名保留为软提示。入口工厂（create_app + register_blueprint）
除外。

v56-5：另认顶层 `def _bp(): ... return <Blueprint>` 可调用工厂
（webui 真 UI：`webui_bp = Blueprint` + `def _bp(): return webui_bp`），
避免接口/惯例门禁冻死合法工厂。
"""
from __future__ import annotations

import ast


_FIX_HINT = (
    "把路由挂到模块顶层导出的蓝图上：推荐 "
    "`_bp = Blueprint(\"<模块名>\", __name__)` + `@_bp.route(...)`"
    "（装配与门禁同口径）；也可用顶层 `_bp()` 工厂返回 Blueprint；"
    "最低要求是顶层 `任意名 = Blueprint(...)`——"
    "禁止把路由藏在函数内构建的 app / 别名蓝图里"
)


def _returns_blueprintish(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """启发式：函数体 return Blueprint(...) 或 return <Name>（由装配运行时验）。"""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        val = node.value
        if isinstance(val, ast.Call):
            fn_name = (getattr(val.func, "id", "")
                       or getattr(val.func, "attr", ""))
            if fn_name == "Blueprint":
                return True
        if isinstance(val, ast.Name):
            return True  # return webui_bp —— 运行时由装配认 Blueprint
    return False


def check_blueprint_convention(code: str, *, module: str = "") -> list[str]:
    """返回问题列表（空=通过）。"""
    if not (code or "").strip():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    has_top_bp = False
    has_bp_factory = False
    has_create_app = False
    has_register_bp = "register_blueprint" in code
    route_lines: list[int] = []

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and isinstance(node.value, ast.Call)
                ):
                    fn = (getattr(node.value.func, "id", "")
                          or getattr(node.value.func, "attr", ""))
                    if fn == "Blueprint":
                        has_top_bp = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "create_app":
                has_create_app = True
            if node.name == "_bp" and _returns_blueprintish(node):
                has_bp_factory = True

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
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
    if has_create_app and has_register_bp:
        return []
    if has_top_bp or has_bp_factory:
        return []
    where = f"模块 {module}" if module else "本模块"
    sample = f"L{route_lines[0]}" if route_lines[0] else "路由装饰"
    return [
        f"蓝图惯例硬红（{where} {sample}）：存在 @*.route 装饰但无顶层 "
        f"`Blueprint(...)` 赋值且无 `_bp` 可调用工厂——{_FIX_HINT}"
    ]
