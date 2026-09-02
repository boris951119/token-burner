"""_shared 公共层符号级合并守卫（v1.0 M14-1，规格 v1.0.md）。

背景（v0.5 真实验收缺口）：`write_shared_file` 原为整文件覆盖写入——后续
模块的 LLM 输出只含自己上下文的函数，直接冲掉先前模块写入的符号
（实测 validate_isbn 丢失 → 跨模块 import 断裂）。

守卫语义（决策归 LLM：写什么；校验归程序：不许丢符号）：
- **丢失保留**：新版缺失的既有顶层符号（函数/类/常量）自动从旧版保留合并；
- **同名变更**：同名符号内容变更 → 采用新版（LLM 的显式修改意图优先）；
- **显式删除**：LLM 以 `# DELETED: <name>` 注释标记的符号才允许从旧版移除
  （未标记的「静默消失」一律视为覆盖事故，保留）；
- **语法回退**：新旧任一版本 AST 解析失败 → 整文件覆盖（保持旧行为，
  接口门禁兜底，不让守卫本身阻塞流程）。

纯函数模块：不落盘、不依赖 FileManager，便于单测与复用。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# DELETED 标记：LLM 显式删除某符号的约定注释（提示词同步约定）
# 形如 `# DELETED: validate_isbn` / `# deleted: validate_isbn`
_DELETED_PREFIX = "# deleted:"

# 参与合并的顶层符号节点类型（函数/类/异步函数/赋值常量）
_ASSIGNABLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass
class MergeReport:
    """一次合并的结果摘要（供审计日志与单测断言）。"""

    kept_symbols: list[str] = field(default_factory=list)   # 新版缺失→从旧版保留
    updated_symbols: list[str] = field(default_factory=list)  # 同名内容变更→采用新版
    deleted_symbols: list[str] = field(default_factory=list)  # 显式标记→从旧版移除
    fallback_overwrite: bool = False                        # 语法失败→整文件覆盖

    @property
    def merged(self) -> bool:
        """是否发生了符号级合并（True = 守卫改写了 LLM 输出）。"""
        return bool(self.kept_symbols or self.updated_symbols or self.deleted_symbols)


def _top_symbols(source: str) -> dict[str, ast.AST]:
    """提取顶层符号名 → 节点映射（函数/类/async 函数/常量赋值）。

    多目标赋值（a = b = 1）取全部名字；解包赋值（a, b = 1, 2）的
    Name 目标也计入（常量契约常见形态）。
    """
    tree = ast.parse(source)
    symbols: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, _ASSIGNABLE):
            symbols[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = node
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            symbols[elt.id] = node
    return symbols


def _explicit_deletes(source: str) -> set[str]:
    """提取 `# DELETED: <name>` 显式删除标记（大小写不敏感，可多个）。"""
    deleted: set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(_DELETED_PREFIX):
            # `# DELETED: a, b` 逗号分隔批量标记
            names = stripped[len(_DELETED_PREFIX):].strip()
            for name in names.split(","):
                name = name.strip()
                if name:
                    deleted.add(name)
    return deleted


def _dedent(node: ast.AST, source: str) -> str:
    """取节点源码段（ast 已带行号；end_lineno 需 Python 3.8+）。"""
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = getattr(node, "end_lineno", None) or node.lineno
    # 顶层节点无缩进，直接切片
    return "".join(lines[start:end])


def merge_shared_source(old: str, new: str) -> tuple[str, MergeReport]:
    """符号级合并：new 为主体，补回 old 中被静默丢失的符号。

    Returns:
        (合并后源码, 合并报告)。任一版本语法解析失败 → (new, fallback报告)。

    合并输出结构：new 全文在前，保留的旧符号以标记注释分隔追加在后——
    保留符号保持旧版原文（含 docstring/装饰器），不做语法拼装，
    可读性与可审计性优先。
    """
    report = MergeReport()
    try:
        old_syms = _top_symbols(old)
        new_syms = _top_symbols(new)
    except SyntaxError:
        report.fallback_overwrite = True
        return new, report

    deletes = _explicit_deletes(new)

    for name, node in old_syms.items():
        if name in new_syms:
            if not ast.dump(new_syms[name]) == ast.dump(node):
                report.updated_symbols.append(name)
            continue
        if name in deletes:
            report.deleted_symbols.append(name)
            continue
        # 新版缺失且未显式删除 → 静默丢失，保留旧符号
        report.kept_symbols.append(name)

    if not report.kept_symbols:
        # 无需补回：新版即终稿（变更与删除仅记录审计）
        return new, report

    kept_blocks = []
    for name in sorted(report.kept_symbols):
        block = _dedent(old_syms[name], old).rstrip("\n")
        kept_blocks.append(
            f"# ---- 以下符号由合并守卫保留（新版缺失且未标记 DELETED）：{name} ----\n"
            f"{block}\n"
        )

    merged = (
        new.rstrip("\n")
        + "\n\n\n# ============ 合并守卫：自动保留的既有符号（M14-1） ============\n"
        + "\n".join(kept_blocks)
    )
    return merged, report
