"""全局链接门禁（v1.0 M14-2，规格 v1.0.md）。

背景（v0.5 真实验收缺口）：`_shared` 被后续模块重写丢符号（或模块间
契约漂移）导致跨模块 import 断裂时，无任何确定性拦截——FROZEN 模块不再
重验、执行阶段才炸（安全模式则根本不执行），断裂静默流入交付物
（实测 validate_isbn 丢失未被发现）。

门禁语义（决策归 LLM：怎么写；校验归程序：不许断链）：
- 对**全部已落盘模块**（含 FROZEN——它们仍在交付物里被 import）与
  当前待验模块，解析项目内 import（`from <module> import <sym>` /
  `from _shared.<file> import <sym>` / `import <module>`）；
- 被引符号必须存在于来源文件的顶层符号集；缺失 → 阻断当前模块，
  输出「引用方文件 + 符号 + 来源文件」精确清单；
- 增量缓存：按 (路径, mtime, size) 缓存解析结果，仅变更文件重解析
  （AST 毫秒级，实测无需异步）。

零执行、零 LLM 调用——与接口门禁同类的确定性纪律执行器。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

# 项目内可被 import 的代码根
_CODE_DIRS = ("code",)
_SHARED_DIR = "_shared"
_INIT_PY = "__init__.py"


@dataclass
class LinkIssue:
    """一处断裂链接（引用方 → 被引符号 → 来源）。"""

    importer: str          # 引用方相对路径（code/<module>/<file>.py）
    symbol: str            # 被引符号（import 级为 "*"）
    source: str            # 来源模块名（module 或 _shared.<file>）


@dataclass
class LinkCheckResult:
    passed: bool
    issues: list[LinkIssue] = field(default_factory=list)
    files_checked: int = 0
    files_cached: int = 0


class _SymbolIndex:
    """项目符号索引：模块名 → 顶层符号集（带 mtime/size 增量缓存）。"""

    def __init__(self, code_root: Path) -> None:
        self._code_root = code_root
        # 缓存键：模块名；值：(mtime, size, symbols) —— mtime+size 双因子
        # 降低粒度风险（同秒改回同长度的场景由内容门禁兜底）
        self._cache: dict[str, tuple[float, int, frozenset[str]]] = {}

    @staticmethod
    def _top_names(source: str) -> frozenset[str] | None:
        """顶层符号集；语法错误返回 None（由静态门禁负责语法报错）。"""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        names.update(
                            elt.id for elt in target.elts
                            if isinstance(elt, ast.Name)
                        )
            elif isinstance(node, ast.ImportFrom):
                # 包级 __init__ 的重导出（file_manager 约定：
                # from <pkg>.<mod> import *）——符号 = 被引模块符号集
                for alias in node.names:
                    if alias.name == "*":
                        names.add(f"*{node.module}")   # 延迟展开标记
                    else:
                        names.add(alias.name)
        return frozenset(names)

    def _expand_stars(self, names: frozenset[str]) -> frozenset[str]:
        """展开 `*<pkg>.<mod>` 延迟标记为被引模块的符号集（一层）。"""
        expanded: set[str] = set()
        pending: set[str] = set()
        for name in names:
            if name.startswith("*"):
                pending.add(name[1:])
            else:
                expanded.add(name)
        for module in pending:
            sub = self.symbols_of(module)
            if sub:
                expanded |= {
                    s for s in sub if not s.startswith("*")
                } | {s for s in sub if s.startswith("*")}  # 保留嵌套标记
        return frozenset(expanded)

    def symbols_of(self, module_key: str) -> frozenset[str] | None:
        """模块顶层符号集（star-import 展开；缓存失效判定）。"""
        rel = module_key.replace(".", "/")
        py = self._code_root / (rel + ".py")
        if not py.is_file():
            init = self._code_root / rel.replace("/", "/") / _INIT_PY
            if "." not in module_key:
                init = self._code_root / module_key / _INIT_PY
            py = init if init.is_file() else py
        if not py.is_file():
            return None
        stat = py.stat()
        cached = self._cache.get(module_key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        names = self._top_names(
            py.read_text(encoding="utf-8", errors="replace")
        )
        if names is None:
            return None
        names = self._expand_stars(names)
        self._cache[module_key] = (stat.st_mtime, stat.st_size, names)
        return names

    def _module_key(self, py: Path) -> str:
        """文件 → 符号索引键：code/ 相对路径去 .py（_shared/utils → _shared.utils）。"""
        rel = py.relative_to(self._code_root).as_posix()[:-len(".py")]
        return rel.replace("/", ".")

    def project_module_keys(self) -> list[str]:
        """全部项目模块键：模块文件 + 包目录（__init__.py 的父目录名）。

        包键（如 `validator`）使 `from validator import X`（经包级
        __init__.py 重导出，file_manager 约定）也进入符号检查。
        """
        keys: list[str] = []
        if not self._code_root.is_dir():
            return keys
        for py in sorted(self._code_root.rglob("*.py")):
            if py.name == _INIT_PY:
                # 包目录键：code/<pkg>/__init__.py → <pkg>
                rel_dir = py.parent.relative_to(self._code_root).as_posix()
                if "/" not in rel_dir and rel_dir != ".":
                    keys.append(rel_dir.replace("/", "."))
                continue
            keys.append(self._module_key(py))
        return keys


def _project_imports(source: str) -> list[tuple[str, list[str], int]]:
    """提取项目内 import：(来源键, [符号], 行号)。非项目引用忽略。

    项目内引用判定（与交付物运行环境一致，conftest 把 code/ 入 sys.path）：
    - `from _shared.x import a, b` → ("_shared.x", [a, b])
    - `from <module> import a`     → ("<module>", [a])
    - `import <module>`            → ("<module>", ["*"])  存在性检查
    - 相对导入 `from . import x`   → 当前模块包（模块间约定为绝对导入，
      相对导入不在本项目契约内，忽略交由执行兜底）
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    imports: list[tuple[str, list[str], int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append((node.module, [a.name for a in node.names], node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, ["*"], node.lineno))
    return imports


def _is_project_key(key: str, known_keys: set[str]) -> bool:
    """import 目标是否落在项目内（精确键或其子模块前缀）。"""
    if key in known_keys:
        return True
    # `from _shared import utils` / `import <module>.<file>` 前缀形态
    head, _, rest = key.partition(".")
    if rest and head in known_keys:
        return True
    return False


def check_links(
    code_root: Path,
    pending_module: str | None = None,
    pending_code: str | None = None,
    index: _SymbolIndex | None = None,
) -> LinkCheckResult:
    """全项目链接门禁。

    Args:
        code_root: 交付物 code/ 目录
        pending_module: 当前待验模块名（其代码尚未落盘，内存态参与检查）
        pending_code: 待验模块代码
        index: 可复用符号索引（跨轮次增量；None 则新建）

    检查范围：全部已落盘模块（含 FROZEN——交付物仍会 import 它们）
    + 当前待验模块。任何文件里的项目内 import 符号缺失都阻断
    当前模块（断裂报告足以定位修复方向）。
    """
    idx = index or _SymbolIndex(code_root)
    result = LinkCheckResult(passed=True)

    # 待验模块的内存态符号（供他文件引用检查；无则空集）
    pending_symbols: frozenset[str] = frozenset()
    if pending_module and pending_code is not None:
        names = _SymbolIndex._top_names(pending_code)
        if names is not None:
            pending_symbols = names

    known_keys = set(idx.project_module_keys())
    if pending_module:
        known_keys.add(pending_module)

    # (文件标识, 源码) 清单：全部已落盘 + 待验内存态
    to_check: list[tuple[str, str]] = []
    for py in sorted(code_root.rglob("*.py")) if code_root.is_dir() else []:
        rel = py.relative_to(code_root.parent).as_posix()  # code/<mod>/<f>.py
        to_check.append((rel, py.read_text(encoding="utf-8", errors="replace")))
    if pending_module and pending_code is not None:
        to_check.append((f"code/{pending_module}/{pending_module}.py", pending_code))

    for importer, source in to_check:
        for module_key, symbols, _lineno in _project_imports(source):
            if not _is_project_key(module_key, known_keys):
                continue  # 外部依赖（stdlib/pip）：静态门禁的 declared_deps 管
            # 来源符号集：待验模块 → 内存态；否则走索引缓存
            if pending_module and module_key == pending_module:
                src_symbols = pending_symbols
            elif module_key.startswith(pending_module + ".") if pending_module else False:
                src_symbols = pending_symbols  # pending 子模块形态（保守同集）
            else:
                src_symbols = idx.symbols_of(module_key)
                # from <pkg> import <sub>：子模块名也算符号（import utils 形态）
            if src_symbols is None:
                # 来源文件缺失/语法错误：存在性由静态门禁报，这里不重复
                continue
            for sym in symbols:
                if sym == "*":
                    continue  # import 存在性已由 _is_project_key 保证
                if sym in src_symbols:
                    continue
                # bench_v1 round-2d 取证：`from _shared import log_config`
                # 是**子模块导入**（log_config.py 文件存在即合法，空
                # __init__.py 不影响运行时），不得按「符号缺失」误杀——
                # 该误报曾致 4 模块连续 5 轮不收敛全部冻结
                if (code_root / module_key.replace(".", "/")
                        / (sym + ".py")).is_file():
                    continue
                result.issues.append(LinkIssue(
                    importer=importer, symbol=sym, source=module_key,
                ))

    result.files_checked = len(to_check)
    result.passed = not result.issues
    return result


def format_link_issues(issues: list[LinkIssue]) -> str:
    """缺失清单 → 可读报告（修复 LLM 一看即知改哪里）。"""
    if not issues:
        return ""
    lines = ["链接门禁失败（跨模块 import 断裂，M14-2）："]
    for i in issues:
        lines.append(
            f"  [missing] {i.importer} 引用了 {i.source} 的「{i.symbol}」，"
            f"但该符号不存在——请补回 {i.source} 中的 {i.symbol}，"
            f"或修正 {i.importer} 的 import"
        )
    return "\n".join(lines)
