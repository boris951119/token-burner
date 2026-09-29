# -*- coding: utf-8 -*-
"""跨模块调用点实参 vs 真实 def 签名（v53 刀A / v57 超额+import-as）。

045fe 尸检：webui_app 写 `seed_db()`，db_seed 定义 `seed_db(conn)`——
模块内 interface_check 只对契约↔实现签名警告，跨模块调用点零检查，
TypeError 在 create_app 起服时才爆，探针假绿交 Stage3。

81bc 尸检：`import peer as alias` + `alias.fn(a,b,c,d)` 对
`def fn(workbook_id, name)`——缺参闸漏报，超额同样 TypeError。

本闸：
1. `from peer import fn` → 本模块 `fn(...)`
2. `import peer` / `import peer as alias` → `alias.fn(...)`
比对 peer 真实 FunctionDef 的必传个数与位置参数上限；
缺参或超额（且无 *args）→ 阻断。
零 LLM；宁漏报不误报（**kwargs / 动态 getattr 跳过）。
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
    maximum: int | None = None

    def text(self) -> str:
        if self.maximum is not None and self.given > self.maximum:
            return (
                f"调用签名硬红（L{self.lineno}）：{self.callee}() 实参 "
                f"{self.given} 个，但 {self.source} 最多接受 "
                f"{self.maximum} 个位置参数——会在运行时 TypeError"
            )
        return (
            f"调用签名硬红（L{self.lineno}）：{self.callee}() 实参 "
            f"{self.given} 个，但 {self.source} 定义需要至少 "
            f"{self.required} 个位置参数——会在运行时 TypeError"
        )


@dataclass
class _Sig:
    required: int
    maximum: int | None  # None = *args 敞开


def _sig_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> _Sig:
    """必传位置参数个数 + 位置参数上限（去掉 self/cls）。"""
    args = fn.args
    pos = list(args.args)
    if pos and pos[0].arg in ("self", "cls"):
        pos = pos[1:]
    defaults = list(args.defaults or [])
    n_required = max(0, len(pos) - len(defaults))
    maximum: int | None
    if args.vararg is not None:
        maximum = None
    else:
        maximum = len(pos)
    return _Sig(required=n_required, maximum=maximum)


def _load_defs(path: Path) -> dict[str, _Sig]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, _Sig] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out[node.name] = _sig_of(node)
    return out


def _resolve_peer_file(code_root: Path, mod: str) -> Path | None:
    """project 模块名 → 实现文件（包内同名 .py 或扁平 .py）。"""
    root = Path(code_root)
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


def _defs_for(code_root: Path, peer_mod: str, cache: dict[str, dict[str, _Sig]]) -> dict[str, _Sig]:
    if peer_mod in cache:
        return cache[peer_mod]
    path = _resolve_peer_file(code_root, peer_mod)
    if path is None:
        path = _resolve_peer_file(code_root, peer_mod.split(".")[0])
    cache[peer_mod] = _load_defs(path) if path else {}
    return cache[peer_mod]


def check_imported_call_arity(
    code: str,
    *,
    code_root: Path | None,
    module: str = "",
) -> list[ArityIssue]:
    """对 code 内跨模块调用做缺参/超额硬检查。"""
    if not code_root or not Path(code_root).is_dir():
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    root = Path(code_root)
    # local_name → (peer_module, symbol)  —— from peer import fn
    imported: dict[str, tuple[str, str]] = {}
    # local_alias → peer_module  —— import peer / import peer as alias
    mod_aliases: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            peer_path = _resolve_peer_file(root, node.module)
            if peer_path is None:
                peer_path = _resolve_peer_file(root, node.module.split(".")[0])
            if peer_path is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imported[local] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod_name = alias.name.split(".")[0]
                peer_path = _resolve_peer_file(root, alias.name)
                if peer_path is None:
                    peer_path = _resolve_peer_file(root, mod_name)
                if peer_path is None:
                    continue
                local = alias.asname or mod_name
                mod_aliases[local] = alias.name if peer_path else mod_name
                # 规范化到可 resolve 的模块名
                if _resolve_peer_file(root, alias.name):
                    mod_aliases[local] = alias.name
                else:
                    mod_aliases[local] = mod_name

    if not imported and not mod_aliases:
        return []

    cache: dict[str, dict[str, _Sig]] = {}
    issues: list[ArityIssue] = []

    def _check(callee: str, peer_mod: str, sym: str, given: int, lineno: int) -> None:
        defs = _defs_for(root, peer_mod, cache)
        if sym not in defs:
            return
        sig = defs[sym]
        if given < sig.required or (
            sig.maximum is not None and given > sig.maximum
        ):
            issues.append(
                ArityIssue(
                    callee=callee,
                    source=f"{peer_mod}.{sym}",
                    required=sig.required,
                    given=given,
                    lineno=lineno,
                    maximum=sig.maximum,
                )
            )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        given = len(node.args)
        lineno = getattr(node, "lineno", 0) or 0
        func = node.func
        if isinstance(func, ast.Name) and func.id in imported:
            peer_mod, sym = imported[func.id]
            _check(func.id, peer_mod, sym, given, lineno)
        elif (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in mod_aliases
        ):
            peer_mod = mod_aliases[func.value.id]
            sym = func.attr
            _check(f"{func.value.id}.{sym}", peer_mod, sym, given, lineno)
    return issues
