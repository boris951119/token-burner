# -*- coding: utf-8 -*-
"""首页 surface 锚点消毒（v61 / run 5d05a462ce84 尸检）。

病灶：REQ 场景写「从首页进 → 登录页报错」，home_visible=True 时
unknown 行为串回落到『首页卡片须含』——冒烟要求 GET / 可见
「Invalid credentials」「Valid-password-123!」「session」等。
修复指令再误导成「index 卡片模板补字段」→ LLM 乱补/修坏（repos.environ）。

规则：
- 凭据输入值 / 提交后才出现的报错 / 抽象词 → 永不进 home 闸；
- 登录表单控件与账户入口金丝雀 → 从 home 挪到 login；
- home 只保留真正应在未登录首页出现的入口文案。
"""
from __future__ import annotations

import re
from typing import Mapping

# 永不作为「首屏 GET 必须可见」的串（home 与 login 都丢）
_NEVER_STATIC = re.compile(
    r"^(?:"
    r"session|Valid-password[\w\-!]*|"
    r"Invalid credentials|"
    r"Username format is invalid|"
    r"Email format is invalid|"
    r"Password requirements are not satisfied|"
    r"Agree to terms is required|"
    r"Username already exists|"
    r"Verification code is invalid|"
    r"Password updated|"
    r"Access denied|"
    r"Account is already a member|"
    r"Account not found|"
    r"Member menu"
    r")$",
    re.I,
)
# 含 @ 或明显口令形态 → 输入值，不是静态文案
_CREDENTIAL_VALUE = re.compile(
    r"@|Valid-password|password-\d|!\s*$", re.I)

# 应在登录/注册面，不应强塞进 GET / 首页卡片
_LOGIN_FORM_LABELS = frozenset({
    "Username or email",
    "Username",
    "Email",
    "Password",
    "Confirm password",
    "Agree to the terms",
    "Create account",
    "Create an account",
    "Sign in",
    "Forgot password",
    "Send reset link",
    "Reset password",
    "Verification code",
    "New password",
    "Invalid credentials",
    "Username format is invalid",
    "Email format is invalid",
    "Password requirements are not satisfied",
    "Agree to terms is required",
    "Username already exists",
    # 登录后才稳定出现；冷启动 GET / 强要会逼模型往首页塞假菜单
    "Account menu",
    "Sign out",
    "Your organizations",
})

# 未登录首页金丝雀（允许留在 home；也允许在 login）
_HOME_ENTRY_OK = frozenset({
    "Sign in",
    "Create an account",
    "Sign up",
    "Forgot password",
})


def is_never_static_anchor(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return True
    if _NEVER_STATIC.match(t):
        return True
    if _CREDENTIAL_VALUE.search(t) and t not in _HOME_ENTRY_OK:
        return True
    return False


def is_login_form_label(s: str) -> bool:
    return (s or "").strip() in _LOGIN_FORM_LABELS


def sanitize_surface_anchors(
    by_surf: Mapping[str, list[str]],
) -> dict[str, list[str]]:
    """消毒 {surface: [anchors]}：丢弃噪声，home→login 挪位。"""
    out: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}

    def _add(surf: str, anchor: str) -> None:
        if is_never_static_anchor(anchor):
            return
        bucket = out.setdefault(surf, [])
        sset = seen.setdefault(surf, set())
        if anchor in sset:
            return
        sset.add(anchor)
        bucket.append(anchor)

    home = list(by_surf.get("home") or [])
    login = list(by_surf.get("login") or [])
    for a in login:
        _add("login", a)
    for a in home:
        if is_login_form_label(a) and a not in _HOME_ENTRY_OK:
            _add("login", a)
        elif is_login_form_label(a) and a in _HOME_ENTRY_OK:
            # Sign in / Create an account：首页入口 + 登录页都合理
            _add("home", a)
            _add("login", a)
        else:
            _add("home", a)
    for surf, anchors in by_surf.items():
        if surf in ("home", "login"):
            continue
        for a in anchors or []:
            if is_never_static_anchor(a):
                continue
            _add(str(surf), a)
    return {k: v for k, v in out.items() if v}


def auth_entrance_missing_from_report(report: str) -> list[str]:
    """从冒烟/验收报告里抽出仍缺的账户入口金丝雀。"""
    text = report or ""
    canaries = (
        "Sign in",
        "Create an account",
        "Username or email",
        "Account menu",
    )
    return [c for c in canaries if c in text and (
        f"「{c}」" in text or f'"{c}"' in text or c in text)]


# 官方 Playwright：getByRole('link', { name: 'Sign in', exact: true })
# 要求恰好 1 个；Auth+Modules 各挂一条 → strict mode 30/30 全灭（5d05）。
_EXACT_NAMED_LINK = re.compile(
    r"(<a\b[^>]*>)\s*(Sign in|Create an account)\s*(</a>)",
    re.I,
)


def count_exact_named_links(html: str, name: str) -> int:
    """统计 HTML 里可见文案恰好为 name 的 <a> 数量（忽略大小写/两侧空白）。"""
    target = (name or "").strip().lower()
    if not target or not html:
        return 0
    n = 0
    for m in _EXACT_NAMED_LINK.finditer(html):
        if m.group(2).strip().lower() == target:
            n += 1
    return n


def collapse_exact_named_links(html: str, name: str = "Sign in") -> str:
    """保留第一个精确文案为 name 的 <a>，删掉后续重复（官方 strict 口径）。"""
    target = (name or "").strip().lower()
    if not target or not html:
        return html or ""
    seen = False

    def _keep(m: re.Match[str]) -> str:
        nonlocal seen
        if m.group(2).strip().lower() != target:
            return m.group(0)
        if not seen:
            seen = True
            return m.group(0)
        return ""

    return _EXACT_NAMED_LINK.sub(_keep, html)
