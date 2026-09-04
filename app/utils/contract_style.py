"""M15-3 契约风格配置（function | class | auto，v1.0 V2 批次）。

背景（v0.5 实测）：M15-1 将函数式风格硬编码进提示词——对默认路径
正确，但用户交付类式代码库时（契约天然是类），门禁与提示词强迫
LLM 改写为函数式，反而制造收敛冲突。风格是工程约束而非语义决策：
应可配置，且 auto 档把「风格事实权」交给首轮实现代码。

三态语义：
- function（缺省）：契约导出 = 顶层可调用函数/常量（M15-1 原文约束）；
- class：契约导出 = 顶层公开类（方法属类内部；门禁按顶层类符号校验，
  extract_public_defs 天然取 __init__ 参数做签名比对）；
- auto：拆分/接口/写码阶段不预设风格（LLM 按能力形态自然选择），
  首轮实现到达接口门禁时按实际代码顶层符号**一次性反推回写契约**
  （确定性 extract_public_defs，零 LLM），审计落盘 sessions/。

与「决策归 LLM」哲学的边界（workplan 风险表）：风格=工程约束，
回写确定性 + 一次性 + 审计可查；function/class 锁定即完全关闭自适应。
"""

from __future__ import annotations

import ast

VALID_CONTRACT_STYLES = ("function", "class", "auto")

# ---------------------------------------------------------------------------
# 风格约束段（运行时拼接：接口生成侧 / 代码编写侧各一套）
# ---------------------------------------------------------------------------

_INTERFACE_FUNCTION = """

API 风格约定（v1.0 M15-1/M15-3，接口门禁将按此校验，风格不符会导致模块反复冻结）：
exports 与 public_api 中的每一项必须是**模块顶层可直接调用的函数或常量**，
不是类、不是需实例化后才能用的方法。
✅ 正确："read_file", "write_file", "get_file_hash(path) -> str"
❌ 错误："FileManager"（类名——调用方还得自己实例化，契约无法静态校验）、
   "FileManager.read_file"（方法路径——不是顶层符号）
若能力天然需要状态，用模块级函数 + 显式参数表达（如
load(path) -> Config / read(config, key)），不要封装成类。"""

_INTERFACE_CLASS = """

API 风格约定（v1.0 M15-3，接口门禁将按此校验，风格不符会导致模块反复冻结）：
exports 与 public_api 中的每一项必须是**模块顶层的公开类**（类名或
「类名(__init__ 参数)」形式），方法属于类内部、不作为顶层导出项。
✅ 正确："FileManager", "FileManager(root)"
❌ 错误："FileManager.read_file"（方法路径——不是顶层符号）、
   "read_file"（裸函数——class 风格下应封装为类的方法）
有状态的封装能力优先用类表达（门禁按顶层类符号静态校验）。"""

_INTERFACE_AUTO = """

API 风格（v1.0 M15-3 auto）：顶层函数或顶层类皆可，按能力形态自然选择——
首轮实现后系统将按实际代码顶层符号对齐契约（一次性回写，审计落盘）。"""

_CODE_FUNCTION = """

接口契约风格（v1.0 M15-1/M15-3）：契约中声明的每个导出项必须是本文件**顶层的
函数或常量**（def read_file(...) / MAX_SIZE = ...），禁止把契约 API 实现
为类或类方法——接口门禁按顶层符号校验，类式实现会被判定 missing 而反复
冻结。需要状态就用函数参数显式传递。"""

_CODE_CLASS = """

接口契约风格（v1.0 M15-3）：契约中声明的每个导出项必须是本文件**顶层的
公开类**（class FileManager(...)），契约 API 实现为该类的公开方法——
接口门禁按顶层类符号校验，裸函数实现会被判定 missing 而反复冻结。"""

_CODE_AUTO = """

接口契约风格（v1.0 M15-3 auto）：顶层函数或顶层类皆可，按能力形态自然
选择——系统将按本文件实际顶层符号对齐契约（一次性回写，审计落盘）。"""


def interface_style_prompt(style: str) -> str:
    """接口生成阶段的风格约束段（拼接到 INTERFACE_SYSTEM 尾部）。"""
    if style == "class":
        return _INTERFACE_CLASS
    if style == "auto":
        return _INTERFACE_AUTO
    return _INTERFACE_FUNCTION


def code_style_prompt(style: str) -> str:
    """代码编写/修复阶段的风格约束段（拼接到 WRITE_CODE/FIX_CODE_SYSTEM 尾部）。"""
    if style == "class":
        return _CODE_CLASS
    if style == "auto":
        return _CODE_AUTO
    return _CODE_FUNCTION


# ---------------------------------------------------------------------------
# auto 反推（确定性，零 LLM）
# ---------------------------------------------------------------------------

def infer_style(code: str) -> str:
    """按实际代码顶层符号推断契约风格。

    存在任一顶层公开类 → class；否则 function（函数/常量同归函数面）。
    语法错误 → function（缺省保守，回写步骤自会跳过）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "function"
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            return "class"
    return "function"


def rewrite_contract(code: str, contract: dict) -> dict | None:
    """按实际代码顶层公开符号重写契约 exports/public_api（auto 回写核心）。

    对齐判定按符号集语义（名称 + 参数元组），不受返回标注/文案差异
    干扰——符号集一致即视为已对齐（零回写，幂等）；不一致时重写，
    其中 (name, params) 未变的条目保留契约原文（保住「-> str」等标注）。
    imports/dependencies 不动（拆分拓扑与跨模块依赖仍由程序校验）。

    Returns:
        重写后的契约浅副本（仅替换 exports/public_api）；
        None = 无公开符号或已对齐。
    """
    from app.utils.interface_check import extract_public_defs, parse_api_signature

    defs = extract_public_defs(code)
    if not defs:
        return None

    export_names: set[str] = set()
    for export in contract.get("exports", []):
        parsed = parse_api_signature(str(export))
        if parsed:
            export_names.add(parsed[0])
    api_parsed: dict[str, tuple[str, ...] | None] = {}
    api_text: dict[str, str] = {}
    for api in contract.get("public_api", []):
        parsed = parse_api_signature(str(api))
        if parsed:
            api_parsed[parsed[0]] = parsed[1]
            api_text[parsed[0]] = str(api).strip()

    new_names = set(defs.keys())
    aligned = export_names == new_names and all(
        name in defs and (params is None or defs[name] == params)
        for name, params in api_parsed.items()
    )
    if aligned:
        return None

    new_exports = list(defs.keys())
    new_api = []
    for name, params in defs.items():
        old = api_text.get(name)
        if old is not None and api_parsed.get(name) == (params or None):
            new_api.append(old)  # (name, params) 未变 → 保留原文（含返回标注）
        else:
            new_api.append(
                f"{name}({', '.join(params)})" if params else name
            )
    rewritten = dict(contract)
    rewritten["exports"] = new_exports
    rewritten["public_api"] = new_api
    return rewritten
