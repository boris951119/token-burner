"""M15-6 测试侧绑定门禁：契约符号被测试裸引用但未绑定 → 可执行性阻断。

依据：bench_v1 round-3 取证（logs/bench_v1/pilot_r3/T2_bench.json）——
glm-4.5-flash 写的测试只 import pytest/mock 等第三方库，裸调用被测函数
（NameError: name 'monthly_revenue_statistics' is not defined），而修复
循环只修代码不修测试，代码侧永远无从修复，5 轮震荡后冻结。T2 六模块中
三个（analytics/cli/export）同签名。

门禁策略（校验归程序）：AST 解析测试文件，收集全部绑定名（import /
def / class / 赋值 / 参数等，保守超集防误报），契约导出符号若被引用
却未绑定 → 阻断并给出精确修复指令（from <module> import <name>）。
测试文件语法错误同样阻断。无契约时门禁空转（行为兼容）。
"""

from __future__ import annotations

import ast
import builtins


def _contract_names(contract: dict | None) -> set[str]:
    """契约要求测试可调用的符号名：exports ∪ public_api 首名。"""
    if not contract:
        return set()
    names: set[str] = set()
    for item in contract.get("public_api") or []:
        head = str(item).split("(", 1)[0].strip()
        head = head.split()[-1] if head.split() else ""
        if head.isidentifier():
            names.add(head)
    for item in contract.get("exports") or []:
        if str(item).isidentifier():
            names.add(str(item))
    return names


def _bound_names(tree: ast.AST, module: str) -> tuple[set[str], bool]:
    """收集测试文件中所有绑定名（保守超集）；返回 (绑定名, 是否 star-import 被测模块)。"""
    bound: set[str] = set()
    star_from_module = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module == module and any(a.name == "*" for a in node.names):
                star_from_module = True
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            args = node.args
            for a in (*args.args, *args.kwonlyargs, *args.posonlyargs):
                bound.add(a.arg)
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            bound.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound, star_from_module


def check_test_bindings(tests: str, module: str, contract: dict | None) -> list[str]:
    """测试侧绑定校验：返回阻断 issue 列表（空 = 通过）。

    只拦「实际引用却未绑定」的契约符号（round-3 精确场景：裸调用必
    NameError）；测试只覆盖契约子集属合法，不强制全量绑定。
    """
    try:
        tree = ast.parse(tests)
    except SyntaxError as exc:
        return [f"测试代码语法错误（第 {exc.lineno or '?'} 行）: {exc.msg}"]

    required = _contract_names(contract)
    if not required:
        return []

    bound, star_from_module = _bound_names(tree, module)
    referenced = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    builtins_set = set(dir(builtins))
    issues: list[str] = []
    for name in sorted(required & referenced):
        if name in bound or name in builtins_set or star_from_module:
            continue
        issues.append(
            f"测试引用 '{name}' 但未绑定（裸名称运行必 NameError）——"
            f"请在测试文件头部添加: from {module} import {name}"
        )
    return issues
