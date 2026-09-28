"""接口契约校验（规格文档 12.2 节、17 章第三阶段）。

AST 抽取实际代码的公开接口（顶层函数 / 类 / 变量，下划线私有排除），
与 interfaces.json 契约做三类差异判定：
- missing（缺失实现）：契约声明导出但代码未实现；
- extra（多余实现）：代码实现但契约未声明；
- signature_mismatch（签名不一致）：函数名匹配但参数不一致。

接口地图自洽性校验（check_map）：
- dangling_import（悬空接口）：模块声明 import 的符号未被依赖模块导出；
- ghost_module（幽灵引用）：依赖了不存在的模块。

门禁接入：模块完成前置校验（12.2），失败进入修复循环。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass


@dataclass
class InterfaceIssue:
    """单条接口差异。"""

    kind: str      # missing / extra / signature_mismatch / dangling_import / ghost_module
    module: str
    detail: str
    # 14.2 严重度表：自创接口（extra）/缺失实现（missing）阻断；签名不匹配警告
    severity: str = "blocking"
    # M15-2：修改指导（修复 LLM 一看即知怎么改；空串 = 无额外指导）
    guidance: str = ""


# public_api 签名形如 "login(user_id, password) -> bool" 或裸名 "session_data"
_API_SIG = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(([^)]*)\))?")


def _is_blueprint_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
    return fn == "Blueprint"


def _bp_export_satisfied(code: str) -> bool:
    """v56-5：契约声明 `_bp` 时，认顶层 Blueprint 名或 `_bp` 可调用工厂。

    病灶（v55-sheet webui）：`webui_bp = Blueprint(...)` +
    `def _bp(): return webui_bp`——旧门禁按公开符号跳过 `_` 前缀 →
    missing `_bp` + extra `webui_bp` → 冻死真 UI 工厂。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    bp_names: set[str] = set()
    has_bp_factory = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if _is_blueprint_call(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        bp_names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None and _is_blueprint_call(node.value):
                bp_names.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "_bp":
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Return) or sub.value is None:
                    continue
                if _is_blueprint_call(sub.value):
                    has_bp_factory = True
                elif isinstance(sub.value, ast.Name):
                    has_bp_factory = True
            if bp_names:
                has_bp_factory = True
    return bool(bp_names) or has_bp_factory


def _blueprint_var_names(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_blueprint_call(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
            and _is_blueprint_call(node.value)
        ):
            names.add(node.target.id)
    return names


def extract_public_defs(code: str) -> dict[str, tuple[str, ...]]:
    """AST 抽取顶层公开定义：函数 / 类 / 变量（_private 排除）。

    Returns: 名称 → 参数元组（变量为空元组）。
    v56-5：特例收录 `_bp`（变量或可调用工厂）——装配约定公开面。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}

    defs: dict[str, tuple[str, ...]] = {}
    for node in tree.body:  # 仅顶层（公开面）
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_bp" or not node.name.startswith("_"):
                defs[node.name] = tuple(
                    a.arg for a in node.args.args
                )
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                init = next(
                    (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                    None,
                )
                params = tuple(a.arg for a in init.args.args) if init else ()
                # M15-3：类契约口径去 self（self 是实现器物非 API 面，
                # class 风格契约「ClassName(root)」与代码签名才能对齐比对）
                if params and params[0] == "self":
                    params = params[1:]
                defs[node.name] = params
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and (
                        target.id == "_bp" or not target.id.startswith("_")):
                    defs[target.id] = ()
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_bp" or not node.target.id.startswith("_"):
                defs[node.target.id] = ()
    return defs


def parse_api_signature(api: str) -> tuple[str, tuple[str, ...] | None] | None:
    """解析契约导出声明：返回 (名称, 参数元组或 None)。

    裸名（无括号）返回 None 参数——变量导出不做签名比对。
    """
    m = _API_SIG.match(api.strip())
    if not m:
        return None
    name = m.group(1)
    raw_params = m.group(2)
    if raw_params is None:
        return name, None
    params = tuple(p.strip() for p in raw_params.split(",") if p.strip())
    return name, params


def check_implementation(
    module: str,
    code: str,
    contract: dict | None,
    style: str = "function",
) -> list[InterfaceIssue]:
    """三类差异判定：实际代码 vs 模块契约。

    style（M15-3）：契约风格——决定 missing 指导措辞（function 补顶层
    函数 / class 补顶层类 / auto 中性）；差异判定本身与风格无关
    （extract_public_defs 对函数/类统一抽取）。
    """
    if contract is None:
        return []

    issues: list[InterfaceIssue] = []
    defs = extract_public_defs(code)

    declared: dict[str, tuple[str, ...] | None] = {}
    api_sigs: dict[str, str] = {}
    for api in contract.get("public_api", []):
        parsed = parse_api_signature(str(api))
        if parsed:
            api_sigs[parsed[0]] = str(api).strip()
    for export in contract.get("exports", []):
        parsed = parse_api_signature(str(export))
        if parsed is None:
            issues.append(InterfaceIssue("missing", module, f"无法解析导出声明: {export!r}"))
            continue
        declared[parsed[0]] = parsed[1]

    bp_ok = "_bp" in declared and _bp_export_satisfied(code)
    bp_aliases = _blueprint_var_names(code) if bp_ok else set()

    for name, declared_params in declared.items():
        # v56-5：`_bp` 契约可由顶层 Blueprint 名或 _bp 工厂满足
        if name == "_bp" and bp_ok:
            continue
        if name not in defs:
            # M15-2：missing 附签名模板（优先 public_api 原文，含返回标注）；
            # M15-3：class 风格指导补类（防「def 类名」误导），auto 中性
            template = api_sigs.get(name)
            if style == "class":
                sig = template or (
                    f"{name}({', '.join(declared_params)})"
                    if declared_params is not None else name
                )
                guide = (
                    f"请在模块顶层补上：class {sig}（契约 API 实现为该类的"
                    f"公开方法，不要以顶层函数替代——门禁按顶层类符号校验）"
                )
            elif style == "auto":
                guide = (
                    f"请在模块顶层补上契约声明的 {name}"
                    f"（函数或类按契约签名对齐）"
                )
            elif template:
                guide = (
                    f"请在模块顶层补上：def {template}（实现体自行补全）；"
                    f"禁止封装成类或类方法——门禁按顶层符号校验"
                )
            elif declared_params is not None:
                params = ", ".join(declared_params)
                guide = (
                    f"请在模块顶层补上：def {name}({params}): ...；"
                    f"禁止封装成类或类方法——门禁按顶层符号校验"
                )
            else:
                guide = f"请在模块顶层定义常量 {name} = ..."
            issues.append(
                InterfaceIssue(
                    "missing", module,
                    f"契约声明导出 {name!r} 但代码未实现",
                    guidance=guide,
                )
            )
        elif declared_params is not None and defs[name] != declared_params:
            issues.append(
                InterfaceIssue(
                    "signature_mismatch",
                    module,
                    f"{name} 签名不一致：契约 {declared_params} vs 代码 {defs[name]}",
                    severity="warning",  # 14.2：签名不符为警告，不阻断门禁
                    guidance=f"建议对齐契约签名：def {api_sigs.get(name, name + str(declared_params))}",
                )
            )

    for name, params in defs.items():
        if name not in declared:
            # v56-5：契约要 _bp 且本符号是 Blueprint 别名 → 非 extras
            if bp_ok and name in bp_aliases:
                continue
            # M15-2：extra 附处置指引（二选一：补声明或删实现）；
            # factory26 演练取证：修复 LLM 选中 ② 私有化而测试已按原名
            # import → ImportError，与门禁来回震荡（db_layer 连修 2 轮）。
            # 指导必须显式禁止「测试已引用时私有化」这条死路。
            kind_hint = "函数" if params else "常量/类"
            issues.append(
                InterfaceIssue(
                    "extra", module,
                    f"代码实现 {name!r} 但契约未声明导出",
                    guidance=(
                        f"处置二选一：① 若 {name}（{kind_hint}）是对外能力，"
                        f"请将其加入契约 exports/public_api；"
                        f"② 若只是内部辅助，请重命名为 _{name}（下划线私有，"
                        f"门禁只校验公开符号）或删除。"
                        f"注意：若模块测试或其他模块已按 {name!r} 调用，"
                        f"禁止选 ②——私有化必然导致测试 ImportError，"
                        f"此时只能选 ①"
                    ),
                )
            )
    return issues


def check_map(interfaces: dict[str, dict]) -> list[InterfaceIssue]:
    """接口地图自洽性校验（悬空接口 / 幽灵引用）。"""
    issues: list[InterfaceIssue] = []
    module_names = set(interfaces.keys())

    exported_symbols: dict[str, set[str]] = {}
    for name, contract in interfaces.items():
        exported_symbols[name] = {
            (parse_api_signature(str(e)) or ("", None))[0] for e in contract.get("exports", [])
        }

    for name, contract in interfaces.items():
        # 幽灵引用：依赖不存在的模块
        for dep in contract.get("dependencies", []):
            if dep not in module_names:
                issues.append(
                    InterfaceIssue("ghost_module", name, f"依赖了不存在的模块 {dep!r}")
                )

        # 悬空接口：import 的符号未被（唯一）依赖模块导出
        deps = [d for d in contract.get("dependencies", []) if d in module_names]
        for symbol in contract.get("imports", []):
            symbol = str(symbol)
            bare = symbol.split(".")[-1]
            if deps and not any(bare in exported_symbols[d] for d in deps):
                issues.append(
                    InterfaceIssue(
                        "dangling_import",
                        name,
                        f"import 的符号 {symbol!r} 未被任何依赖模块 {deps} 导出",
                    )
                )
    return issues


def sync_extra_exports(code: str, contract: dict) -> list[str]:
    """接口门禁 extra 类失配的机械同步（平台 v6 取证：page_detail
    5 轮 LLM 修复未对齐冻结——「实现 X 但契约未声明」是纯机械失配，
    实现即权威，把实现中的公开符号补进契约，零 LLM）。

    只补 extra（实现有、契约无）；missing（契约有、实现无）属内容
    缺失，留 LLM 修复通道。幂等：已声明的符号不重复追加。
    返回新增声明（签名串）列表。
    """
    if contract is None:
        return []
    defs = extract_public_defs(code)
    if not defs:
        return []
    declared: set[str] = set()
    for entry in list(contract.get("exports", [])) + list(
            contract.get("public_api", [])):
        parsed = parse_api_signature(str(entry))
        if parsed:
            declared.add(parsed[0])
    added: list[str] = []
    for name, params in defs.items():
        if name in declared:
            continue
        sig = f"{name}({', '.join(params)})" if params else name
        contract.setdefault("exports", []).append(sig)
        contract.setdefault("public_api", []).append(sig)
        added.append(sig)
    return added
