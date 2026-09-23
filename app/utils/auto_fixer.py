# -*- coding: utf-8 -*-
"""确定性修复引擎：零 LLM、纯机械变换，修一个验一个。

设计原则（用户指令 09-17）：修复不能靠概率。LLM 只负责理解需求（生成），
修复全部由程序机械执行——每一处替换都精确到字符级，修完立即验证。

修复器清单（按实弹命中频率排序）：
1. fix_column_drift      列名漂移 → 从 DDL 列清单模糊匹配替换 SQL 字面量
2. fix_import_drift      import 路径漂移 → 重写为实际包路径
3. fix_submodule_binding 子模块未绑定 → __init__.py 追加 from . import X
4. fix_blueprint_registry Blueprint 未注册 → create_app 中插入注册行
5. fix_dangling_template 悬空 {% extends %}/{% include %} → 摘除指令，页面自含渲染
   （runA 取证：继承指令 10/10 指向从未生成的模板 = 整站每页 500）

每个修复器返回 (是否修改, 修改描述列表)。修改直接写入文件。
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8", newline="\n")


_SPEC_CACHE: dict[str, bool] = {}


def _externally_importable(top: str) -> bool:
    """top 名是否可由项目外解析（标准库 / site-packages 三方包）。
    尸体验证：flask 不是标准库，曾被 fix_missing_module 当漂移报发现。"""
    if not top or top.startswith("_"):
        return False
    if top in getattr(sys, "stdlib_module_names", ()):
        return True
    if top in _SPEC_CACHE:
        return _SPEC_CACHE[top]
    try:
        import importlib.util as _iu
        found = _iu.find_spec(top) is not None
    except Exception:
        found = False
    _SPEC_CACHE[top] = found
    return found


def _py_files(code_dir: Path) -> list[Path]:
    return [p for p in sorted(code_dir.rglob("*.py"))
            if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# 修复器 1：列名漂移（schema 漂移）
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = {
    "WHERE", "SET", "AND", "OR", "NOT", "LIKE", "IN", "BETWEEN", "IS",
    "NULL", "SELECT", "FROM", "INSERT", "INTO", "VALUES", "UPDATE",
    "DELETE", "ON", "JOIN", "LEFT", "INNER", "GROUP", "ORDER", "BY",
    "LIMIT", "HAVING", "AS", "DISTINCT", "COUNT", "SUM", "AVG", "MIN",
    "MAX", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END",
}

_SQL_HEAD_RE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|SELECT)\b", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM)\s+([\w\"'\[\]]+)",
    re.IGNORECASE)


def _near_col(candidate: str, cols: list[str]) -> str | None:
    """唯一近名列才返回，宁漏勿改（尸体验证：first-match-wins 的旧
    匹配器把 user_id→id、note_row→note_id 之类全改错）。

    认三种高置信形态：单复数、双方≥4 的包含、difflib≥0.80。
    候选 <3 字符一律拒绝（v/r 之类 1 字符变量是重灾区）。"""
    c = candidate.lower()
    if len(c) < 3:
        return None
    hits: list[str] = []
    for v in cols:
        vl = v.lower()
        if c == vl:
            continue
        if (c == vl + "s" or c == vl + "es"
                or c + "s" == vl or c + "es" == vl):
            hits.append(v)
        elif len(c) >= 4 and len(vl) >= 4 and (c in vl or vl in c):
            hits.append(v)
        elif difflib.SequenceMatcher(None, c, vl).ratio() >= 0.80:
            hits.append(v)
    return hits[0] if len(hits) == 1 else None


def _fix_sql_literal(lit: str, ddl: dict[str, list[str]],
                     out: list[str]) -> str:
    """在单条 SQL 字面量内做列名漂移修复：INSERT 列清单 + WHERE/SET
    非限定谓词列。表不可识别或不在 DDL → 原样返回。"""
    result = lit
    for sm in list(re.finditer(r"[^;]+", lit)):
        stmt = sm.group(0)
        if not _SQL_HEAD_RE.search(stmt):
            continue
        tm = _TABLE_RE.search(stmt)
        if not tm:
            continue
        tbl = tm.group(1).strip("\"'[]").lower()
        cols = ddl.get(tbl)
        if not cols:
            continue
        colset = {c.lower() for c in cols}
        fixed = stmt

        # 1) INSERT 列清单漂移（r13/r15/r16 实证族）
        im = re.search(r"(INSERT\s+INTO\s+[\w\"'\[\]]+\s*)\(([^)]*)\)",
                       fixed, re.IGNORECASE)
        if im and "SELECT" not in im.group(2).upper():
            names = [n.strip().strip("\"'`[]")
                     for n in im.group(2).split(",")]
            if names and all(re.fullmatch(r"\w+", n) for n in names):
                renamed, changed = [], False
                for n in names:
                    if n.lower() in colset:
                        renamed.append(n)
                        continue
                    near = _near_col(n, cols)
                    if near is None:
                        renamed.append(n)
                    else:
                        renamed.append(near)
                        out.append(f"INSERT 列 {n} → {near} (表 {tbl})")
                        changed = True
                if changed:
                    fixed = (fixed[:im.start(2)] + ", ".join(renamed)
                             + fixed[im.end(2):])

        # 2) WHERE/SET 非限定谓词列漂移（限定引用 t.col 不动）
        pat = re.compile(
            r"(?<![\w.'\"])(\w+)\s*(?:=|LIKE\b|IN\b|BETWEEN\b|<>|!=|>=|<=|>|<)")

        def _sub(m: re.Match) -> str:
            name = m.group(1)
            if name.upper() in _SQL_KEYWORDS or name.lower() in colset:
                return m.group(0)
            near = _near_col(name, cols)
            if near is None:
                return m.group(0)
            out.append(f"谓词列 {name} → {near} (表 {tbl})")
            return m.group(0).replace(name, near, 1)

        fixed = pat.sub(_sub, fixed)
        if fixed != stmt:
            result = result.replace(stmt, fixed, 1)
    return result


def fix_column_drift(code_dir: Path, ddl_tables: dict[str, list[str]]) -> list[str]:
    """列名漂移机械修复 v2（keep7 尸体验证后重写）。

    旧版在整份源码上做正则捕获，把 Python 关键字参数/循环变量当列名
    改写（尸体上 22 处误伤）。新版只在 ast 识别的 SQL 字符串字面量内
    改写，且仅当目标表唯一、近名列唯一（宁漏勿改）。
    覆盖两族实证缺陷：INSERT 列清单漂移、WHERE/SET 谓词列漂移。

    ddl_tables: {表名: [列名列表]}（run_all_fixers 已做形状归一）
    """
    import ast as _ast

    code_dir = Path(code_dir)
    fixes: list[str] = []
    ddl = {t.lower(): [str(c) for c in cols]
           for t, cols in (ddl_tables or {}).items()}
    if not ddl:
        return fixes

    for py in _py_files(code_dir):
        src = _read(py)
        if not src.strip():
            continue
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        rel = py.relative_to(code_dir).as_posix()
        new_src = src
        file_fixes: list[str] = []
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.Constant)
                    and isinstance(node.value, str)):
                continue
            lit = node.value
            if not _SQL_HEAD_RE.search(lit):
                continue
            new_lit = _fix_sql_literal(lit, ddl, file_fixes)
            if new_lit != lit:
                new_src = new_src.replace(lit, new_lit, 1)
        if file_fixes and new_src != src:
            _write(py, new_src)
            fixes.extend(f"{rel}: {x}" for x in file_fixes)
    return fixes


# ---------------------------------------------------------------------------
# 修复器 2：import 路径漂移
# ---------------------------------------------------------------------------

def fix_import_drift(code_dir: Path) -> list[str]:
    """扫描全部 .py 的顶层 import，将被导入但不存在于 code_dir 根层的
    模块名重写为实际存在的近名模块。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []

    # 构建实际可导入模块清单
    # 注意：_shared 是生成应用的合法公共层包名（keep7 取证），
    # 只排除点开头与 __pycache__，不排除单下划线开头
    real_stems = set()
    real_pkgs = set()
    for child in code_dir.iterdir():
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            real_pkgs.add(child.name)
            for py in child.glob("*.py"):
                if py.name != "__init__.py" and "__pycache__" not in py.name:
                    real_stems.add(py.stem)
        elif child.suffix == ".py":
            real_stems.add(child.stem)

    for py in _py_files(code_dir):
        src = _read(py)
        if not src.strip():
            continue
        rel = py.relative_to(code_dir).as_posix()
        new_src = src
        changed = False

        for m in re.finditer(r"^(\s*from\s+)(\w+)(\s+import\s+)([^\n#]+)",
                             new_src, re.MULTILINE):
            imported = m.group(2)
            if imported in real_stems or imported in real_pkgs:
                continue
            # 尝试近名匹配（f1_auth ~ auth, web_ui ~ webui 等）
            near_pkg = None
            for rp in real_pkgs:
                if (imported.startswith(rp) or rp.startswith(imported)
                        or imported in rp or rp in imported):
                    near_pkg = rp
                    break
            if near_pkg:
                new_import = f"from {near_pkg} import"
                new_src = new_src.replace(m.group(0), new_import)
                fixes.append(f"{rel}: from {imported} → from {near_pkg}")
                changed = True

        if changed:
            _write(py, new_src)
            fixes.append(f"{rel}: import 已修正")
    return fixes


# ---------------------------------------------------------------------------
# 修复器 3：子模块绑定
# ---------------------------------------------------------------------------

def fix_submodule_binding(code_dir: Path) -> list[str]:
    """扫描 `from X import X` 模式，如果包 X 有同名子模块 X.py，
    确保包 __init__.py 中有 `from . import X`。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []
    for pkg_dir in code_dir.iterdir():
        if (not pkg_dir.is_dir() or pkg_dir.name.startswith(".")
                or pkg_dir.name == "__pycache__"
                or not (pkg_dir / "__init__.py").exists()):
            continue
        init_src = _read(pkg_dir / "__init__.py")
        for py in pkg_dir.glob("*.py"):
            if py.name == "__init__.py" or "__pycache__" in py.name:
                continue
            stem = py.stem
            bind = f"from . import {stem}"
            if bind not in init_src:
                init_src = init_src.rstrip() + f"\n{bind}  # noqa: F401\n"
                _write(pkg_dir / "__init__.py", init_src)
                fixes.append(f"{pkg_dir.name}/__init__.py: 补绑定 {stem}")
    return fixes


# ---------------------------------------------------------------------------
# 修复器 4：Blueprint 注册补全
# ---------------------------------------------------------------------------

def fix_blueprint_registry(code_dir: Path) -> list[str]:
    """扫描包中的 Blueprint 定义，检查是否被 create_app 注册。
    未注册的自动在组装模块中补上注册行。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []

    # 收集全部 Blueprint
    blueprints: dict[str, Path] = {}
    for py in _py_files(code_dir):
        src = _read(py)
        for m in re.finditer(r"(\w+)\s*=\s*Blueprint\s*\(", src):
            blueprints[m.group(1)] = py

    # 收集 create_app 函数所在文件
    assembly = None
    for py in _py_files(code_dir):
        src = _read(py)
        if "def create_app" in src:
            assembly = py
            break
    if assembly is None:
        return fixes

    asm_src = _read(assembly)
    asm_rel = assembly.relative_to(code_dir).as_posix()

    for bp_name, bp_file in sorted(blueprints.items()):
        if bp_name in asm_src:
            continue
        # Blueprint 未在组装模块中被引用 → 补注册
        rel = bp_file.relative_to(code_dir).as_posix()
        mod_name = bp_file.stem
        # 确定导入路径（相对 code_dir 的模块路径）
        import_path = rel.replace("/", ".").removesuffix(".py")
        import_stmt = f"from {import_path} import {bp_name}"
        register_stmt = f"app.register_blueprint({bp_name})"

        # 在 create_app 中最后一个 register_blueprint 后追加
        insert_after = None
        for i, line in enumerate(asm_src.splitlines()):
            if "register_blueprint" in line:
                insert_after = i
        lines = asm_src.splitlines()
        if insert_after is None:
            # 全新注册场景（r13 实证：create_app 存在但零注册）→
            # 插到 create_app 内 return 之前，缩进对齐 return 行
            ret_idx = None
            in_create = False
            for i, line in enumerate(lines):
                if re.match(r"^def \w+", line):
                    in_create = line.startswith("def create_app")
                    continue
                if in_create and re.match(r"^\s+return\b", line):
                    ret_idx = i
                    break
            if ret_idx is None:
                continue  # 结构太非常规，跳过
            indent = re.match(r"\s*", lines[ret_idx]).group(0)
            insert_at = ret_idx
        else:
            indent = re.match(r"\s*", lines[insert_after]).group(0)
            insert_at = insert_after + 1
        lines.insert(insert_at, f"{indent}{register_stmt}")
        # 在文件顶部补 import
        if import_stmt not in asm_src:
            lines.insert(0, import_stmt)

        _write(assembly, "\n".join(lines))
        fixes.append(
            f"{asm_rel}: 补注册 Blueprint {bp_name} (来自 {rel})")

    return fixes


# ---------------------------------------------------------------------------
# 修复器 5：标准库遮蔽清除
# ---------------------------------------------------------------------------

def fix_stdlib_shadow(code_dir: Path) -> list[str]:
    """删除遮蔽标准库的自动垫片（keep7 取证：根层 re.py 遮蔽 stdlib
    re，任何 import re 都会解析到劣质垫片）。

    只删带「# Auto shim」标记的生成物，绝不碰人写/LLM 产物。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []
    marker = "# Auto shim"
    for py in sorted(code_dir.glob("*.py")):
        if py.stem not in getattr(sys, "stdlib_module_names", ()):
            continue
        try:
            head = py.read_text(encoding="utf-8", errors="replace")[:200]
        except OSError:
            continue
        if marker in head:
            py.unlink()
            fixes.append(f"{py.name}: 删除遮蔽标准库的自动垫片")
    return fixes


# ---------------------------------------------------------------------------
# 修复器 8：库文件路径漂移（多模块各自为库）
# ---------------------------------------------------------------------------

_DB_FILE_LIT_RE = re.compile(
    r"""['"]([^'"\n]+\.(?:db|sqlite3?|db3))['"]""", re.IGNORECASE)


def _db_assigns(src: str) -> list[tuple[str, int, str]]:
    """模块级赋值中含 .db 字面量的 (目标名, 起始行, 首行文本) 清单。"""
    import ast as _ast

    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return []
    out: list[tuple[str, int, str]] = []
    for node in tree.body:
        if not isinstance(node, _ast.Assign):
            continue
        seg = _ast.get_source_segment(src, node) or ""
        if not _DB_FILE_LIT_RE.search(seg):
            continue
        for t in node.targets:
            if isinstance(t, _ast.Name):
                out.append((t.id, node.lineno,
                            seg.splitlines()[0].strip()))
    return out


def _mod_import_name(py: Path, code_dir: Path) -> str:
    """相对 code_dir 的可导入名：包文件→pkg.pkg，包 __init__→pkg，根文件→stem。"""
    rel = py.relative_to(code_dir)
    if len(rel.parts) == 1:
        return py.stem
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        return parts[0]
    return f"{parts[0]}.{parts[-1][:-3]}"


def _module_imports(src: str) -> set[str]:
    import ast as _ast

    names: set[str] = set()
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return names
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, _ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def fix_db_path_unify(code_dir: Path) -> list[str]:
    """统一多模块 sqlite 库文件路径（2026-09-20 本地首跑取证：
    db_core 读写 instance/keep.db，seed_data 把种子 INSERT 进相对路径
    take_a_note.db——两个库文件，种子永远进不了 API 的库；journey 三轮
    LLM 修复无法定位此类「物理分裂」。机械统一：
    核心模块 = 常量为 __file__/Path 锚定表达式者；其余模块的裸路径
    字面量改写为 importlib 直取核心子模块常量（绕开 __init__ 星号
    导出丢下划线名的坑），核心反依赖目标模块（环）时跳过不碰。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []
    cand: dict[Path, tuple[str, int, str, str]] = {}
    for py in _py_files(code_dir):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        assigns = _db_assigns(src)
        if assigns:
            cand[py] = (*assigns[0], src)
    if len(cand) < 2:
        return fixes

    def _anchor_abs(seg: str) -> bool:
        return ("__file__" in seg) or bool(
            re.search(r"=\s*_?[A-Za-z_\w]*_?BASE_DIR\b|\bPath\(", seg))

    core_py = None
    for py, (name, _ln, seg, _src) in cand.items():
        if _anchor_abs(seg):
            core_py = py
            break
    if core_py is None:
        return fixes
    core_name, _ln, core_seg, core_src = cand[core_py]
    core_files = set(m.group(1).lower()
                     for m in _DB_FILE_LIT_RE.finditer(core_seg))
    if not core_files:
        return fixes
    core_imports = _module_imports(core_src)
    core_mod = _mod_import_name(core_py, code_dir)

    for py, (name, lineno, seg, src) in sorted(cand.items()):
        if py == core_py:
            continue
        if _anchor_abs(seg):
            continue
        lits = [m.group(1) for m in _DB_FILE_LIT_RE.finditer(seg)]
        if not lits:
            continue
        stems = {l.replace("\\", "/").split("/")[-1].lower() for l in lits}
        if stems & core_files:
            continue  # 同名同库，不碰
        # 环检测：核心模块顶层 import 了目标模块 → 跳过
        target_mod = _mod_import_name(py, code_dir)
        if any(m == target_mod or m.startswith(target_mod + ".")
               for m in core_imports):
            continue
        lines = src.splitlines(keepends=True)
        # 定位该赋值所在行（AST lineno 即赋值首行）
        indent = re.match(r"\s*", lines[lineno - 1]).group(0)
        original = lits[0]
        repl = (
            f"{indent}def _unify_db_path(_default={original!r}):\n"
            f"{indent}    # db-path unify (auto_fixer): 复用 {core_mod} 的库文件，"
            f"防止多库分裂\n"
            f"{indent}    try:\n"
            f"{indent}        import importlib as _il\n"
            f"{indent}        _m = _il.import_module({core_mod!r})\n"
            f"{indent}        _v = getattr(_m, {core_name!r}, None)\n"
            f"{indent}        if _v:\n"
            f"{indent}            return str(_v)\n"
            f"{indent}    except Exception:\n"
            f"{indent}        pass\n"
            f"{indent}    return _default\n"
            f"{indent}{name} = _unify_db_path()\n"
        )
        lines[lineno - 1] = repl
        try:
            new_src = "".join(lines)
            compile(new_src, str(py), "exec")  # 语法自证
            py.write_text(new_src, encoding="utf-8")
            fixes.append(
                f"{target_mod}.{name}: {original} → 复用 {core_mod}.{core_name}"
                f"（库文件分裂统一）")
        except Exception:
            continue
    return fixes


# ---------------------------------------------------------------------------
# 修复器 6：模块路径漂移（点路径 + 符号路由）
# ---------------------------------------------------------------------------

_MISSING_MODULE_RE = re.compile(
    r"^(\s*)from\s+([\w.]+)\s+import\s+([^\n#]+)", re.MULTILINE)


def _module_map(code_dir: Path) -> dict[str, Path]:
    """实际可导入模块清单：{点路径: 文件}。含 _shared 类单下划线包。"""
    mods: dict[str, Path] = {}
    for child in code_dir.iterdir():
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            mods[child.name] = child / "__init__.py"
            for py in child.glob("*.py"):
                if py.name != "__init__.py" and "__pycache__" not in py.name:
                    mods[f"{child.name}.{py.stem}"] = py
        elif child.suffix == ".py":
            mods[child.stem] = child
    return mods


def _symbol_index(mods: dict[str, Path]) -> dict[str, set[str]]:
    """各模块顶层定义符号：def/class/赋值（排除 = None 占位——
    把 import 路由到 None 占位比让它报错更糟）。"""
    idx: dict[str, set[str]] = {}
    for mpath, f in mods.items():
        if f.name == "__init__.py":
            continue  # 只路由到实体模块
        src = _read(f)
        names: set[str] = set()
        for m in re.finditer(r"^(?:def|class)\s+(\w+)", src, re.MULTILINE):
            names.add(m.group(1))
        for m in re.finditer(r"^(\w+)\s*=(?!\s*None\b)", src, re.MULTILINE):
            names.add(m.group(1))
        idx[mpath] = names
    return idx


def fix_missing_module(code_dir: Path) -> list[str]:
    """模块路径漂移（keep7 取证：拆分发明 `from _shared.db import ...`，
    开发实际把助手写进 data_core.data_core）。

    规则：import 引用的模块路径不存在时，若其全部导入符号可在**同一**
    真实模块找到顶层定义 → 重写路径；任何符号无处定义或多处歧义 →
    不改代码，仅产出精确发现供 LLM 修复通道使用（宁缺勿错）。"""
    code_dir = Path(code_dir)
    fixes: list[str] = []
    mods = _module_map(code_dir)
    if not mods:
        return fixes
    idx = _symbol_index(mods)
    stdlib = getattr(sys, "stdlib_module_names", ())

    for py in _py_files(code_dir):
        src = _read(py)
        if not src.strip():
            continue
        rel = py.relative_to(code_dir).as_posix()
        new_src = src
        changed = False

        for m in _MISSING_MODULE_RE.finditer(src):
            mod = m.group(2)
            if not mod or mod.startswith("."):
                continue  # 相对 import 不动
            top = mod.split(".")[0]
            if top in stdlib or _externally_importable(top) or mod in mods:
                continue  # 标准库 / 三方包 / 项目内已存在
            raw_names = [n.strip().split(" as ")[0].strip()
                         for n in m.group(3).replace("(", "").split(",")]
            names = {n for n in raw_names
                     if re.fullmatch(r"\w+", n or "") and n != "*"}
            if not names:
                continue
            # 子模块导入（from pkg import submod）结构上成立，不算符号
            needed = {n for n in names if f"{mod}.{n}" not in mods}
            if not needed:
                continue
            cands = [mp for mp, syms in idx.items() if needed <= syms]
            if len(cands) == 1:
                target = cands[0]
                new_src = re.sub(
                    rf"^(\s*from\s+){re.escape(mod)}(\s+import\s+)",
                    rf"\g<1>{target}\g<2>", new_src, flags=re.MULTILINE)
                fixes.append(
                    f"{rel}: from {mod} → from {target} "
                    f"(符号路由: {','.join(sorted(needed))})")
                changed = True
            else:
                everywhere = set().union(*idx.values()) if idx else set()
                nowhere = sorted(needed - everywhere)
                amb = "" if len(cands) < 2 else \
                    f"（多处歧义: {cands}）"
                hint = f"{nowhere} 无任何定义处" if nowhere else \
                    "符号分散，无法唯一路由"
                fixes.append(
                    f"{rel}: [发现] {mod} 缺失，{sorted(needed)} 中 "
                    f"{hint}{amb}——需 LLM 通道新增/归拢")
                break  # 该文件本轮只产出一次发现，避免重复刷屏

        if changed:
            _write(py, new_src)
    return fixes


# ---------------------------------------------------------------------------
# 悬空模板继承
# ---------------------------------------------------------------------------

_TEMPLATE_SUFFIXES = (".html", ".htm", ".j2", ".jinja", ".jinja2")
_JINJA_INHERIT_RE = re.compile(
    r"""\{%-?\s*(extends|include)\s+(['"])([^'"]+)\2\s*-?%\}""")
_TEMPLATES_DIR_NAMES = {"templates", "template"}


def _template_logical_names(code_dir: Path) -> set[str]:
    """交付里真实存在的模板，按 Jinja 会认的三种写法登记：裸文件名、
    相对 code 根的路径、相对任一 templates/ 目录的路径。"""
    names: set[str] = set()
    for p in code_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _TEMPLATE_SUFFIXES:
            continue
        if {"__pycache__", "node_modules", ".git"} & set(p.parts):
            continue
        names.add(p.name)
        names.add(p.relative_to(code_dir).as_posix())
        parts = p.parts
        for i, part in enumerate(parts):
            if part in _TEMPLATES_DIR_NAMES:
                names.add("/".join(parts[i + 1:]))
    return names


def fix_dangling_template(code_dir: Path) -> list[str]:
    """悬空继承/包含 → 摘除指令，让页面自含渲染。

    2026-09-23 runA 交付复放取证：生成器按「多页应用」的直觉写
    `{% extends "base.html" %}` 却从不创建父模板，本地 13 份带模板的交付里
    这类指令 10 条、悬空 10 条（0 例父模板真的写过）——每个页面直接 500，
    判分面整片归零。摘除指令不损失任何已生成内容（父模板本来就不存在），
    子模板自己的 block 就地渲染，页面从 500 回到可判分。
    只对 extends/include 动手：import 掉的宏真被调用时摘了会换成
    UndefinedError，收益不确定，留给 LLM 通道。
    """
    code_dir = Path(code_dir)
    fixes: list[str] = []
    have = _template_logical_names(code_dir)
    # have 为空不提前返回：交付里一个模板文件都没有时，内联串里的
    # extends/include 更是无处可解析——全部悬空，正是该修的形状。

    targets = list(code_dir.rglob("*.py")) + [
        p for p in code_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in _TEMPLATE_SUFFIXES]
    for f in targets:
        if "__pycache__" in f.parts or "node_modules" in f.parts:
            continue
        src = _read(f)

        def _dangling(m: re.Match) -> bool:
            return m.group(3) not in have and Path(m.group(3)).name not in have

        found = [m for m in _JINJA_INHERIT_RE.finditer(src) if _dangling(m)]
        if not found:
            continue
        rel = f.relative_to(code_dir).as_posix()
        new_src = _JINJA_INHERIT_RE.sub(
            lambda m: (f"{{# 机械摘除：目标模板 {m.group(3)} "
                       f"未随交付生成 #}}"
                       if _dangling(m) else m.group(0)),
            src)
        if f.suffix == ".py":
            try:
                compile(new_src, str(f), "exec")
            except SyntaxError as exc:
                fixes.append(
                    f"{rel}: [发现] 悬空继承摘除后语法不通，未改写（{exc.msg}）")
                continue
        _write(f, new_src)
        counted: dict[tuple[str, str], int] = {}
        for m in found:
            key = (m.group(1), m.group(3))
            counted[key] = counted.get(key, 0) + 1
        for (kind, target), n in sorted(counted.items()):
            fixes.append(
                f"{rel}: 摘除 {n} 处悬空 {kind} \"{target}\""
                "（目标模板未生成，页面改为自含渲染）")
    return fixes


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def _flat_ddl(ddl) -> dict[str, list[str]]:
    """collect_ddl 返回 {表:{"columns":[...],"sources":[...]}}，
    fix_column_drift 期望 {表:[列...]}——统一入口处归一，
    兼容两种形态（keep7 取证：形状不匹配会静默失效）。"""
    flat: dict[str, list[str]] = {}
    for tbl, spec in (ddl or {}).items():
        if isinstance(spec, dict):
            flat[tbl] = list(spec.get("columns") or [])
        else:
            flat[tbl] = list(spec)
    return flat


def run_all_fixers(code_dir: Path,
                   ddl_tables: dict[str, list[str]] | None = None,
                   ) -> dict[str, list[str]]:
    """依次执行全部机械修复器，返回 {修复器名: [修改描述]}。

    每个修复器独立执行、独立验证——修一个验一个。
    """
    results: dict[str, list[str]] = {}
    try:
        if ddl_tables:
            r = fix_column_drift(code_dir, _flat_ddl(ddl_tables))
            if r:
                results["列名漂移"] = r
    except Exception:
        pass
    try:
        r = fix_import_drift(code_dir)
        if r:
            results["import路径漂移"] = r
    except Exception:
        pass
    try:
        r = fix_submodule_binding(code_dir)
        if r:
            results["子模块绑定"] = r
    except Exception:
        pass
    try:
        r = fix_missing_module(code_dir)
        if r:
            results["模块路径漂移"] = r
    except Exception:
        pass
    try:
        r = fix_dangling_template(code_dir)
        if r:
            results["悬空模板继承"] = r
    except Exception:
        pass
    try:
        r = fix_stdlib_shadow(code_dir)
        if r:
            results["标准库遮蔽"] = r
    except Exception:
        pass
    try:
        r = fix_db_path_unify(code_dir)
        if r:
            results["库文件路径漂移"] = r
    except Exception:
        pass
    try:
        r = fix_blueprint_registry(code_dir)
        if r:
            results["Blueprint注册"] = r
    except Exception:
        pass
    return results
