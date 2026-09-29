# -*- coding: utf-8 -*-
"""刀K：装饰性实现门禁（batches#85 decorative compliance）。

病灶（v55-github 9355c0065d57）：模型把契约文案抄进 `_GLOBAL_UI_COPY`
字典后全仓零引用；源码 grep（刀H）以为落地，实际 /login 渲染体零命中。

规则（AST + 运行时双查）：
1. AST：契约锚点作为字符串字面量出现在任意 .py 源码；
2. 运行时：起服后收集各路由可见 HTML；
3. 若锚点在源码字面量中出现，却不在**任何**被渲染的可见响应里 → 红
   （死常量 / 装饰性照抄）。

仅对 surface=home/login 的位置锚点生效（须在首屏 GET 出现的契约），
不对「动作后须出现」行为期望误伤。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from app.utils.manifest_landing import visible_html

MIN_LITERAL_LEN = 4


def ast_string_literals(code: str) -> set[str]:
    """抽出源码中的字符串字面量（含 JoinedStr 的常量子串）。"""
    out: set[str] = set()
    if not code or not code.strip():
        return out
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value.strip()
            if len(s) >= MIN_LITERAL_LEN:
                out.add(s)
        elif isinstance(node, ast.JoinedStr):
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    s = v.value.strip()
                    if len(s) >= MIN_LITERAL_LEN:
                        out.add(s)
    return out


def collect_source_literals(code_dir) -> set[str]:
    """扫交付树全部 .py 的字符串字面量并集。"""
    root = Path(code_dir)
    out: set[str] = set()
    if not root.is_dir():
        return out
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        out |= ast_string_literals(src)
    return out


def join_visible_bodies(bodies: Iterable[str]) -> str:
    """合并多页可见 HTML 为单一语料。"""
    parts: list[str] = []
    for b in bodies:
        if not b:
            continue
        parts.append(visible_html(b))
    return "\n".join(parts)


def check_decorative_impl(
    *,
    anchors: Iterable[str],
    source_literals: set[str] | None = None,
    code: str = "",
    code_dir=None,
    rendered_bodies: Iterable[str] = (),
    rendered_html: str = "",
    module: str = "",
) -> list[str]:
    """契约锚点在源码字面量出现但不在任何可见渲染响应 → 红。

    提供 code（单文件）或 code_dir（整树）或直接 source_literals；
    提供 rendered_bodies（多页）或 rendered_html（已合并）。
    """
    anchors_list = [
        a for a in (anchors or [])
        if isinstance(a, str) and len(a.strip()) >= MIN_LITERAL_LEN
    ]
    if not anchors_list:
        return []

    if source_literals is None:
        if code_dir is not None:
            source_literals = collect_source_literals(code_dir)
        else:
            source_literals = ast_string_literals(code or "")

    if rendered_html:
        corpus = visible_html(rendered_html)
    else:
        corpus = join_visible_bodies(rendered_bodies)

    dead: list[str] = []
    for a in anchors_list:
        # 字面量精确命中或字面量包含锚点（f-string 切片/字典值）
        in_src = a in source_literals or any(
            a in lit for lit in source_literals if len(lit) <= 200
        )
        if not in_src:
            continue
        if a not in corpus:
            dead.append(a)

    if not dead:
        return []
    where = f"模块 {module}" if module else "交付树"
    fields = "、".join(f'「{m}」' for m in dead[:8])
    if len(dead) > 8:
        fields += f" 等共 {len(dead)} 条"
    return [
        f"装饰性实现门禁（{where}）：契约字面量在源码出现但未进入任何"
        f"路由可见 HTML：{fields}——疑似死常量/未接线字典"
        f"（如 _GLOBAL_UI_COPY）；请接到对应路由模板并删除无引用抄写"
    ]
