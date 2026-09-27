# -*- coding: utf-8 -*-
"""跨模块调用点实参 vs 真实 def 签名（v53 刀A）。

045fe 尸检：webui_app 写 `seed_db()`，db_seed 定义 `seed_db(conn)`——
模块内 interface_check 只对契约↔实现签名警告，跨模块调用点零检查，
TypeError 在 create_app 起服时才爆，探针假绿交 Stage3。

本闸：解析 `from peer import fn` 后对本模块内 `fn(...)` 调用比对
peer 文件真实 FunctionDef 的「必传位置参数」个数；缺参 → 阻断。
零 LLM；宁漏报不误报（*args/**kwargs/属性调用/动态 getattr 跳过）。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ArityIssue:
    callee: str
    source: str
    required: int
    given: int
    lineno: int

    def text(self) -> str:
        return (
            f"调用签名硬红（L{self.lineno}）：{self.callee}() 实参 "
            f"{self.given} 个，但 {self.source} 定义需要至少 "
            f"{self.required} 个位置参数——会在运行时 TypeError"
        )


def _required_positional(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """必传位置参数个数（去掉 self/cls，去掉有默认值的）。"""
    args = fn.args
    pos = list(args.args)
    if pos and pos[0].arg in ("self", "cls"):
        pos = pos[1:]
    defaults = list(args.defaults or [])
    n_required = len(pos) - len(defaults)
    return max(0, n_required)


def _load_defs(path: Path) -> dict[str, int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out[node.name] = _required_positional(node)
    return out


def _resolve_peer_file(code_root: Path, mod: str) -> Path | None:
    """project 模块名 → 实现文件（包内同名 .py 或扁平 .py）。"""
    root = Path(code_root)
    # _shared.x
    if mod.startswith("_shared."):
        stem = mod.split(".", 1)[1]
        p = root / "_shared" / f"{stem}.py"
        return p if p.is_file() else None
    if mod == "_shared":
        return None
    pkg = root / mod / f"{mod}.py"
    if pkg.is_file():
        return pkg
    flat = root / f"{mod}.py"
    if flat.is_file():
        return flat
    init = root / mod / "__init__.py"
    if init.is_file():
        return init
    return None


def check_imported_call_arity(
    code: str,
    *,
    code_root: Path | None,
    module: str = "",
) -> list[ArityIssue]:
    """对 code 内「从项目 peer import 的名字」的调用做缺参硬检查。"""
    if not code_root or not Path(code_root).is_dir():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    # local_name → (peer_module, symbol)
    imported: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.level:
            continue  # 相对导入：同包，通常已有单测覆盖
        root = node.module.split(".")[0]
        # 仅项目 peer / _shared
        peer_path = _resolve_peer_file(Path(code_root), node.module)
        if peer_path is None and root != module:
            # 再试根名
            peer_path = _resolve_peer_file(Path(code_root), root)
        if peer_path is None:
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            imported[local] = (node.module, alias.name)

    if not imported:
        return []

    # peer → symbol → required
    cache: dict[str, dict[str, int]] = {}
    issues: list[ArityIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name not in imported:
            continue
        peer_mod, sym = imported[name]
        if peer_mod not in cache:
            path = _resolve_peer_file(Path(code_root), peer_mod)
            if path is None:
                path = _resolve_peer_file(
                    Path(code_root), peer_mod.split(".")[0])
            cache[peer_mod] = _load_defs(path) if path else {}
        defs = cache[peer_mod]
        if sym not in defs:
            continue
        required = defs[sym]
        # 只数位置实参；关键字不计入「已满足必传」的保守策略：
        # 若全用关键字传必传参，可能误报——045 形态是零位置，宁抓。
        given = len(node.args)
        if given < required:
            issues.append(
                ArityIssue(
                    callee=name,
                    source=f"{peer_mod}.{sym}",
                    required=required,
                    given=given,
                    lineno=getattr(node, "lineno", 0) or 0,
                )
            )
    return issues
