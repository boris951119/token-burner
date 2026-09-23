# -*- coding: utf-8 -*-
"""属性级接口漂移审计（零 LLM，AST 机械比对）。

9/21 keep 冷启动取证：interfaces.json 里 init_app×3 + init_db×1 并存
无人发现；实现侧写 _init_db（私有），views 按契约调 init_db → 每个
请求 before_request 里 AttributeError，全站 500。命名漂移整类缺陷靠
LLM 自省修不动（修复环两轮零提升实证）——本模块用确定性比对在生成
验收期直接点名：

- audit_attr_calls: 调用点 `X.attr(...)` 与 `from X import name` vs
  模块 X 实际顶层名——缺名报漂移，附最接近名（前导下划线隐私错位
  是最高频形态，keep 的 init_db/_init_db 即此类）；
- audit_interfaces_contract: interfaces.json 的 exports 须在实现模块
  中有同名 def/class/赋值；imports 须在任一模块中可解析——引用不
  存在的符号 = 幻觉导入，部署必死；
- audit_interface_drift: 两者合并，验收/修复指令直接引用。

静态比对看不见 setattr/动态属性；发现列表是「确定性缺口」而非全量
等价校验——空列表只代表未发现缺口。判据（Qoder 9/21）：换成任何域
该规则仍成立，是通用工程不变量。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from app.utils.link_check import pkg_self_alias

_TOP_DEF = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _top_names(src: str) -> set[str]:
    """单文件顶层 def/class/赋值名（不含嵌套）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, _TOP_DEF):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets
                         if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _init_names(init_src: str, pkg_dir: Path | None = None,
                pkg_name: str | None = None) -> set[str]:
    """包 __init__ 的可见名：自身 def/赋值 + 导入引入名。

    9/22 真项目取证两连：keep 的 __init__ 用【绝对路径】star 重导出
    （from data_layer.data_layer import *，level=0）——只处理相对导入
    会把 get_db 全家误报成幻觉导入。星号语义 = 兄弟模块的非下划线
    顶层名（无 __all__ 时）；非星号导入名一律纳入。
    """
    names = _top_names(init_src)
    try:
        tree = ast.parse(init_src)
    except SyntaxError:
        return names
    # 包入口别名到同级模块（file_manager _PKG_SHIM）：包名即实现模块，
    # 可见名与该模块同源。不认这个形会把 `from validator import check`
    # 误报成幻觉导入（与链接门禁同一假红族）。
    self_alias = pkg_self_alias(tree) if pkg_dir else None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level >= 1:
            rest = node.module or ""            # from .x.y → x.y
        elif pkg_name and node.module:
            mod = node.module
            if mod == pkg_name:
                rest = ""
            elif mod.startswith(pkg_name + "."):
                rest = mod[len(pkg_name) + 1:]
            else:
                continue                        # 外部模块，与包命名空间无关
        else:
            continue
        sibling_src: str | None = None
        if pkg_dir is not None and rest:
            rel = rest.replace(".", "/")
            for cand in (pkg_dir / f"{rel}.py",
                         pkg_dir / rel / "__init__.py"):
                if cand.is_file():
                    sibling_src = _read(cand)
                    break
        for a in node.names:
            if a.name == "*":
                if sibling_src:
                    names |= {n for n in _top_names(sibling_src)
                              if not n.startswith("_")}
            elif (self_alias and node.level >= 1
                    and (f"{node.module}.{a.name}" if node.module
                         else a.name) == self_alias
                    and pkg_dir is not None):
                sub = pkg_dir / f"{self_alias.replace('.', '/')}.py"
                if sub.is_file():
                    names |= {n for n in _top_names(_read(sub))
                              if not n.startswith("_")}
            else:
                names.add(a.asname or a.name)
    return names


def module_symbols(code_dir: Path) -> dict[str, set[str]]:
    """import 顶层名 → 该模块可见名集合（单文件/包两种形态）。"""
    out: dict[str, set[str]] = {}
    code_dir = Path(code_dir)
    for p in sorted(code_dir.glob("*.py")):
        if p.stem != "__init__":
            out[p.stem] = _top_names(_read(p))
    for pkg in sorted(code_dir.iterdir()):
        init = pkg / "__init__.py"
        if pkg.is_dir() and not pkg.name.startswith((".", "_")) and init.is_file():
            names = set(_init_names(_read(init), pkg_dir=pkg,
                                    pkg_name=pkg.name))
            for sub in pkg.glob("*.py"):
                if sub.stem != "__init__":
                    names.add(sub.stem)
            out[pkg.name] = names
    return out


def _near_miss(symbols: dict[str, set[str]], mod: str, attr: str,
               code_dir: Path) -> str | None:
    """最接近的实现名：下划线错位（init_db ↔ _init_db）优先。"""
    pool = set(symbols.get(mod, set()))
    pkg = Path(code_dir) / mod
    if pkg.is_dir():
        for sub in pkg.glob("*.py"):
            pool |= _top_names(_read(sub))
    for cand in sorted(pool):
        if cand.lstrip("_") == attr.lstrip("_") and cand != attr:
            return cand
    return None


def _where(src: str, offset: int, rel: str) -> str:
    return f"{rel}:{src.count(chr(10), 0, offset) + 1}"


def audit_attr_calls(code_dir: Path) -> list[str]:
    """跨模块属性调用/导入 与 实现顶层名 的确定性比对。"""
    code_dir = Path(code_dir)
    symbols = module_symbols(code_dir)
    if not symbols:
        return []
    findings: list[str] = []
    seen: set[str] = set()

    def _flag(msg: str) -> None:
        if msg not in seen:
            seen.add(msg)
            findings.append(msg)

    for py in sorted(code_dir.rglob("*.py")):
        src = _read(py)
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = py.relative_to(code_dir).as_posix()
        alias2mod: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    root = a.name.split(".")[0]
                    if root in symbols:
                        alias2mod[a.asname or root] = root
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    if root in symbols:
                        for a in node.names:
                            if a.name == "*":
                                continue
                            if a.name not in symbols[root] and \
                                    a.name not in symbols:
                                near = _near_miss(symbols, root, a.name,
                                                  code_dir)
                                _flag(
                                    f"{_where(src, node.lineno - 1, rel)}: "
                                    f"from {root} import {a.name!r} —— "
                                    f"{root} 未提供该符号"
                                    + (f"（最接近: {near}，疑前导下划线"
                                       f"隐私错位）" if near else "（幻觉"
                                       f"导入，部署必死）"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)):
                mod = alias2mod.get(node.func.value.id)
                if not mod:
                    continue
                attr = node.func.attr
                if attr in symbols[mod]:
                    continue
                near = _near_miss(symbols, mod, attr, code_dir)
                _flag(
                    f"{_where(src, node.lineno - 1, rel)}: 调用 "
                    f"{mod}.{attr}() 不存在"
                    + (f"（最接近: {mod}.{near}，疑前导下划线隐私错位——"
                       f"对齐命名或加公共别名）" if near else
                       f"（{mod} 现有: {', '.join(sorted(symbols[mod])[:8])}）"))
    return findings


def audit_interfaces_contract(project_dir: Path) -> list[str]:
    """interfaces.json 契约 vs 实现的双向比对。

    exports → 实现模块文件里必须有同名 def/class/赋值；
    imports → 全仓任一模块必须能解析该符号（幻觉导入检测）。
    """
    project_dir = Path(project_dir)
    iface = project_dir / "interfaces.json"
    code_dir = project_dir / "code"
    if not iface.is_file() or not code_dir.is_dir():
        return []
    try:
        data = json.loads(iface.read_text(encoding="utf-8"))
    except Exception:
        return ["interfaces.json 解析失败——契约文件损坏"]
    symbols = module_symbols(code_dir)
    # 全仓可用名（供 imports 解析）
    universe: set[str] = set()
    pkg_files: dict[str, list[Path]] = {}
    for name in symbols:
        universe |= symbols[name]
    for py in sorted(code_dir.rglob("*.py")):
        universe |= _top_names(_read(py))
        top = py.relative_to(code_dir).parts[0]
        pkg_files.setdefault(top, []).append(py)

    findings: list[str] = []
    import re as _re

    def _base(name: str) -> str:
        """契约条目可能带签名 query(sql, params)——取裸标识符。"""
        return _re.match(r"[A-Za-z_]\w*", name).group(0)

    for mod, spec in data.items():
        impl_files = pkg_files.get(mod, [])
        impl_names: set[str] = set()
        for f in impl_files:
            impl_names |= _top_names(_read(f))
        for name in spec.get("exports", []) or []:
            bare = _base(name)
            if impl_names and bare not in impl_names:
                findings.append(
                    f"契约 exports 声明 {mod}.{bare} 但实现模块未定义"
                    f"（实现现有: {', '.join(sorted(impl_names)[:8])}）")
        for name in spec.get("imports", []) or []:
            bare = _base(name)
            if "." in bare:
                # 模块.符号 形态（home.bp / data_layer.init_app）
                base_mod, attr = bare.split(".", 1)
                if (base_mod in symbols and attr in symbols[base_mod]) \
                        or attr in universe:
                    continue
                findings.append(
                    f"契约 imports 引用 {name!r}（{mod}）但 {base_mod} 未"
                    f"提供 {attr!r} 且全仓无此符号——幻觉导入，部署必死，"
                    f"须改用真实 API 或补实现")
            elif bare in universe:
                continue
            else:
                findings.append(
                    f"契约 imports 引用 {name!r}（{mod}）但全仓无任何模块"
                    f"提供该符号——幻觉导入，部署必死，须改用真实 API 或补"
                    f"实现")
    return findings


def audit_interface_drift(code_dir: Path,
                          project_dir: Path | None = None) -> list[str]:
    """合并入口：调用点漂移 + 契约自洽（project_dir 缺省取 code_dir 上一层）。"""
    findings = list(audit_attr_calls(code_dir))
    project = Path(project_dir) if project_dir else Path(code_dir).parent
    findings += audit_interfaces_contract(project)
    return findings
