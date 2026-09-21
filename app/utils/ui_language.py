# -*- coding: utf-8 -*-
"""UI 语言一致性审计（零 LLM，文字系别比对）。

9/22 stackoverflow 冷启动取证（全场最致命发现）：管线提示词是中文，
英文需求进来 LLM 照样写中文 UI（"知识问答平台"/"首页"/"问题列表"），
官方测试按英文 getByRole(/questions/i) 断言 → 66 题从第一步全灭。
UI 语言规则此前只有提示词约束、无机械执行——本模块补上：

需求为拉丁字母主导时，生成代码的字符串字面量（模板/HTML/文案）中
出现 CJK 即违规；反向（中文需求 + 拉丁 UI）同理。AST 解析天然排除
注释——生成代码的中文注释合法，中文文案不合法。

判据（Qoder 9/21）：把题目换成任何域仍成立——「UI 语言 = 需求语言」
是通用工程不变量。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN = re.compile(r"[A-Za-z]")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def requirement_language(requirement: str) -> str:
    """需求主导文字系别：'latin' | 'cjk' | 'unknown'（样本不足）。"""
    if not requirement:
        return "unknown"
    cjk = len(_CJK.findall(requirement))
    latin = len(_LATIN.findall(requirement))
    if cjk + latin < 200:            # 样本太少不下结论
        return "unknown"
    return "cjk" if cjk > latin else "latin"


def _cjk_in_string_literals(src: str) -> list[str]:
    """AST 抽取字符串字面量中的 CJK 片段（注释天然排除）。"""
    hits: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # 模板/HTML 文件非 Python——整文件按字面处理（HTML 无注释豁免）
        for m in _CJK.finditer(src):
            hits.append(src[max(0, m.start() - 10):m.start() + 10])
            if len(hits) >= 3:
                break
        return hits
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _CJK.search(node.value):
                hits.append(node.value.strip()[:40])
                if len(hits) >= 3:
                    break
    return hits


def audit_ui_language(code_dir: Path, requirement: str) -> list[str]:
    """需求语言 vs 代码 UI 字符串语言的一致性审计。

    返回违规清单（人类可读，供修复指令直接引用）；空 = 一致或无法
    判定。只对标字符串字面量与模板/HTML 文件——生成代码的中文注释
    合法（管线提示词语言所致），不构成违规。
    """
    lang = requirement_language(requirement)
    if lang != "latin":              # 目前只强制：英文需求 → 禁 CJK UI
        return []
    code_dir = Path(code_dir)
    bad: list[tuple[str, str]] = []
    for py in sorted(code_dir.rglob("*.py")):
        hits = _cjk_in_string_literals(_read(py))
        if hits:
            bad.append((py.relative_to(code_dir).as_posix(), hits[0]))
    for html in sorted(list(code_dir.rglob("*.html"))
                       + list(code_dir.rglob("*.htm"))):
        hits = _cjk_in_string_literals(_read(html))
        if hits:
            bad.append((html.relative_to(code_dir).as_posix(), hits[0]))
    if not bad:
        return []
    files = ", ".join(f for f, _ in bad[:8])
    return [
        f"需求为英文，但 {len(bad)} 个文件的 UI 字符串含中文（{files}"
        f"…）——评测按英文 ARIA 名定位，中文界面 = 全部用例落空。必须把"
        f"所有界面文案（导航/按钮/标题/表单标签/占位符/提示消息/页面"
        f"标题）改写为英文，语言以需求原文为唯一标准；代码注释不受限。"
    ]
