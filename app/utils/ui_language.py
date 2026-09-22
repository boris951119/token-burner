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
_WS = re.compile(r"\s+")
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_JS_BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_JS_LINE_COMMENT = re.compile(r"//[^\n]*")
# 界面文案可能只存在于前端资产里，扫描面必须覆盖前后端
_HTML_SUFFIX = {".html", ".htm"}
_JS_SUFFIX = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue"}
_UI_SUFFIX = {".py"} | _HTML_SUFFIX
# 第三方/构建产物不参与审计（体积大且非本次生成的文案）
_SKIP_DIR = {"node_modules", "dist", "build", "__pycache__", "site-packages",
             ".venv", "venv", ".git", "vendor"}
_MAX_FILES = 400


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


def _snippet(s: str) -> str:
    return _WS.sub(" ", s).strip()[:40]


def _cjk_in_literals(src: str) -> list[str]:
    """Python 源码里 UI 文案位（字符串字面量）的 CJK 片段。

    注释天然排除（AST），**文档字符串也排除**（9/23 取证：导出的官方
    runner 入口模板自带中文 docstring → 每个交付应用都被判违规，而这条
    在修复指令里标着「最高优先级」，等于把修复环支去改注释）。
    """
    hits: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            body = getattr(n, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in doc_ids and _CJK.search(node.value)):
            hits.append(_snippet(node.value))
            if len(hits) >= 3:
                break
    return hits


def _cjk_in_markup(src: str, *, html: bool = False) -> list[str]:
    """非 Python 前端资产（HTML/JS/TS/Vue）的 CJK 文案位。

    整段界面文案可以只活在 home.js 的模板串里——只扫 .py/.html 等于放行。
    注释按 /* */ 与 // 剔除；`//` 一并截掉字符串里的协议头（宁漏不误，
    假阳性的代价是把「最高优先级」指令支去改注释，比漏检贵得多）。
    """
    if html:
        src = _HTML_COMMENT.sub(" ", src)
    else:
        src = _JS_BLOCK_COMMENT.sub(" ", src)
        src = _JS_LINE_COMMENT.sub(" ", src)
    hits = [_snippet(src[max(0, m.start() - 12):m.start() + 12])
            for m in list(_CJK.finditer(src))[:3]]
    return hits


def audit_ui_language(code_dir: Path, requirement: str) -> list[str]:
    """需求语言 vs 交付界面文案语言的一致性审计（前后端全资产）。

    返回违规清单（人类可读，供修复指令直接引用）；空 = 一致或无法
    判定。字符串字面量与模板/HTML 正文对标——注释与文档字符串合法
    （管线提示词语言所致），不构成违规。
    """
    lang = requirement_language(requirement)
    if lang != "latin":              # 目前只强制：英文需求 → 禁 CJK UI
        return []
    code_dir = Path(code_dir)
    bad: list[tuple[str, str]] = []
    scanned = 0
    for p in sorted(code_dir.rglob("*")):
        if scanned >= _MAX_FILES:
            break
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in _UI_SUFFIX and suf not in _JS_SUFFIX:
            continue
        if any(part in _SKIP_DIR for part in p.parts):
            continue
        scanned += 1
        src = _read(p)
        hits = (_cjk_in_literals(src) if suf == ".py"
                else _cjk_in_markup(src, html=suf in _HTML_SUFFIX))
        if hits:
            bad.append((p.relative_to(code_dir).as_posix(), hits[0]))
    if not bad:
        return []
    detail = "；".join(f"{f} 如 {s!r}" for f, s in bad[:3])
    more = "…" if len(bad) > 3 else ""
    return [
        f"需求为英文，但 {len(bad)} 个文件的界面文案含中文（{detail}{more}）"
        f"——评测按英文 ARIA 名定位，中文界面 = 全部用例落空。必须把"
        f"所有界面文案（导航/按钮/标题/表单标签/占位符/提示消息/页面"
        f"标题）改写为英文，语言以需求原文为唯一标准；代码注释与"
        f"文档字符串不受限。"
    ]
