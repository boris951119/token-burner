# -*- coding: utf-8 -*-
"""入门表单×路由静态闸（v56 刀2）：不启应用也能抓住「POST 登录没注册」。

v55 GitHub 尸检：login 页 `<form method=post action=/login>`，但 POST 只写在
`if __name__ == "__main__"` 演示块里；create_app 未挂。表单探针若超时假绿，
这条静态闸仍能在快车道守卫里 demote。
"""
from __future__ import annotations

import re
from pathlib import Path

# 表单 action 目标（登录/注册常见路径）
_FORM_ACTION = re.compile(
    r"""<form\b[^>]*\baction\s*=\s*['"](/[\w\-./]*)['"][^>]*>""",
    re.I | re.S,
)
_FORM_METHOD_POST = re.compile(
    r"""<form\b[^>]*\bmethod\s*=\s*['"]post['"]""",
    re.I | re.S,
)
# 路由装饰器：methods 含 POST，或未写 methods 时 Flask 默认 GET-only
_ROUTE_DECO = re.compile(
    r"""@(?:\w+\.)?route\(\s*['"](/[\w\-./]*)['"]([^)]*)\)""",
    re.I,
)
_METHODS_POST = re.compile(r"methods\s*=\s*\[[^\]]*'POST'[^\]]*\]", re.I)
_METHODS_POST_DQ = re.compile(r'methods\s*=\s*\[[^\]]*"POST"[^\]]*\]', re.I)
_METHODS_ANY = re.compile(r"methods\s*=", re.I)

# 只盯身份入门路径——全站所有 form 仍由表单探针覆盖
_AUTH_PATHS = frozenset({
    "/login", "/signin", "/sign-in", "/sign_in",
    "/signup", "/sign-up", "/sign_up", "/register",
    "/forgot-password", "/forgot_password", "/password/reset",
})


def _post_routes(code: str) -> set[str]:
    """源码里明确声明 POST 的路径集合（含 methods 列表含 POST）。"""
    out: set[str] = set()
    for m in _ROUTE_DECO.finditer(code or ""):
        path, rest = m.group(1), m.group(2) or ""
        if _METHODS_POST.search(rest) or _METHODS_POST_DQ.search(rest):
            out.add(path)
        # methods=["GET", "POST"] 已覆盖；裸 @route("/x") 只有 GET，不算
    return out


def _auth_post_forms(code: str) -> set[str]:
    """模板/字符串里 method=POST 且 action 落在身份路径的集合。"""
    out: set[str] = set()
    for m in _FORM_ACTION.finditer(code or ""):
        # 回看该 form 开标签是否声明 post（同 match 起点附近）
        start = m.start()
        window = (code or "")[max(0, start - 20): m.end()]
        # action 匹配的 form 标签本身
        tag = m.group(0)
        if not (_FORM_METHOD_POST.search(tag)
                or _FORM_METHOD_POST.search(window)):
            # 默认 method=GET 的登录表单少见；要求显式 post
            if "method" in tag.lower():
                continue
            # 无 method 属性时浏览器默认 GET——登录场景通常写了 post
            continue
        path = m.group(1).split("?")[0]
        if path in _AUTH_PATHS:
            out.add(path)
    return out


def _is_skipped_py(path: Path, root: Path) -> bool:
    """只按相对 root 的路径段过滤隐藏目录——绝对路径里的 `.tmp` 不得误杀整树。"""
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        rel_parts = path.parts
    return any(part.startswith(".") or part == "__pycache__" for part in rel_parts)


def check_auth_form_routes(code_dir: Path) -> list[str]:
    """返回问题列表（空=通过）。"""
    root = Path(code_dir)
    if not root.is_dir():
        return []
    form_targets: set[str] = set()
    post_routes: set[str] = set()
    for p in root.rglob("*.py"):
        if _is_skipped_py(p, root):
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # 演示块里的 POST 不算正式装配——剥掉 if __name__ 之后再收路由
        main_at = src.find('if __name__ == "__main__"')
        if main_at < 0:
            main_at = src.find("if __name__ == '__main__'")
        body = src if main_at < 0 else src[:main_at]
        form_targets |= _auth_post_forms(src)  # 表单文案可在 __main__ 外的字符串
        post_routes |= _post_routes(body)
    missing = sorted(form_targets - post_routes)
    if not missing:
        return []
    return [
        "入门表单×路由硬闸：页面有 POST 表单提交到 "
        + ", ".join(missing)
        + "，但模块顶层（非 __main__ 演示块）未注册对应 POST 路由——"
        "评测填表提交会 404/405，身份链全灭。请在 create_app / register_routes "
        "挂载的 Blueprint 上注册 POST，禁止只写在 if __name__ == '__main__' 里"
    ]
