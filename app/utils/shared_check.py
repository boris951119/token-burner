"""_shared/ 公共层依赖判定与变更回归（规格文档 12.7 节、14.4 节、14.5 节）。

依赖判定（14.2 AST 零执行）：扫描模块代码 import 语句，检测
`from _shared... import` / `import _shared...` → 判定该模块依赖公共层。

整包回归触发（14.4 / 14.5）：
- _shared/ 内容变更时，对其全部依赖模块触发整包回归（重跑门禁+执行）；
- 普通模块修复不触发全量回归（仅重验本模块，13.4）。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SHARED_ROOT = "_shared"


def uses_shared(code: str) -> bool:
    """AST 检测代码是否引用 _shared/ 公共层（import 语句级）。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == _SHARED_ROOT for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == _SHARED_ROOT:
                return True
    return False


def find_shared_dependents(project_root: Path, modules: list[str]) -> list[str]:
    """扫描落盘代码，返回依赖 _shared/ 的模块列表（build_order 顺序）。

    仅统计已有代码落盘的模块（未开发模块无从判定依赖）。
    """
    dependents: list[str] = []
    for name in modules:
        module_dir = project_root / "code" / name
        if not module_dir.is_dir():
            continue
        for py in sorted(module_dir.glob("*.py")):
            try:
                if uses_shared(py.read_text(encoding="utf-8")):
                    dependents.append(name)
                    break
            except OSError:
                continue
    return dependents
