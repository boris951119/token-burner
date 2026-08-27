"""生成代码静态验证（规格文档 17 章第三阶段、19 章代码质量门禁）。

ast.parse 语法门禁 + import / 引用核验：
- 语法错误（阻断级）：LLM 输出常见截断 / 括号缺失；
- 幽灵项目 import（阻断级）：import 了项目内不存在的模块；
- 第三方依赖（提示级）：不阻断，由 requirements.txt 管理。

安全模式下无执行反馈，静态门禁可提前拦截明显损坏的代码，
减少无意义修复轮数（省 token，11 章护栏精神）。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StaticCheckResult:
    """静态检查结果（阻断 issues + 提示 warnings）。"""

    passed: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_syntax(code: str) -> list[str]:
    """ast.parse 语法门禁。"""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return [f"语法错误（第 {exc.lineno or '?'} 行）: {exc.msg}"]
    return []


def check_imports(
    code: str,
    project_modules: set[str],
    declared_deps: set[str] | None = None,
) -> list[str]:
    """import / 引用核验（契约驱动）。

    - 契约声明依赖某模块但项目无此模块 → 幽灵引用（阻断）；
    - 代码 import 了项目模块但契约未声明 → 未声明跨模块依赖（阻断）；
    - 非 stdlib 非项目的未知 import → 第三方提示（不阻断，warning 层）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # 语法门禁先行，此处无从核验

    issues: list[str] = []
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imported_roots.add(node.module.split(".")[0])

    if declared_deps is not None:
        for dep in declared_deps:
            if dep not in project_modules:
                issues.append(
                    f"幽灵引用：契约声明依赖 {dep!r} 但项目中不存在该模块"
                )
        for root in imported_roots:
            if root in project_modules and root not in declared_deps:
                issues.append(
                    f"未声明的跨模块依赖：代码 import 了 {root!r} 但契约 dependencies 未声明"
                )
    return issues


def run_static_check(
    code: str,
    project_modules: set[str] | None = None,
    declared_deps: set[str] | None = None,
) -> StaticCheckResult:
    """完整静态门禁：语法（阻断）→ 幽灵/未声明 import（阻断）→ 第三方（提示）。"""
    project_modules = project_modules or set()
    issues: list[str] = []
    warnings: list[str] = []

    issues.extend(check_syntax(code))
    if issues:
        return StaticCheckResult(False, issues, warnings)

    issues.extend(check_imports(code, project_modules, declared_deps))

    # 第三方依赖提示（不阻断）
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in project_modules and root not in _stdlib_modules():
                        warnings.append(f"第三方依赖提示: {alias.name}（须在 requirements.txt 声明）")
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                root = node.module.split(".")[0]
                if root not in project_modules and root not in _stdlib_modules():
                    warnings.append(f"第三方依赖提示: {node.module}（须在 requirements.txt 声明）")
    except SyntaxError:
        pass

    return StaticCheckResult(not issues, issues, warnings)


def _stdlib_modules() -> frozenset[str]:
    return frozenset(sys.stdlib_module_names)


def is_syntax_ok(path: Path) -> bool:
    """文件级语法门禁（供批量扫描）。"""
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return False
    return True
