# -*- coding: utf-8 -*-
"""v61：首页锚点消毒 + 账户入口修复指令（5d05a462ce84 尸检）。"""
from __future__ import annotations

from app.utils.surface_anchor_sanitize import (
    sanitize_surface_anchors,
    is_never_static_anchor,
    is_login_form_label,
    count_exact_named_links,
    collapse_exact_named_links,
)
from app.utils.manifest_landing import collect_surface_anchors_from_texts
import app.arcbench_smoke as sm


def test_never_static_drops_credentials_and_errors():
    assert is_never_static_anchor("Valid-password-123!")
    assert is_never_static_anchor("Invalid credentials")
    assert is_never_static_anchor("session")
    assert is_never_static_anchor("Access denied")
    assert not is_never_static_anchor("Sign in")
    assert not is_never_static_anchor("Create an account")


def test_sanitize_moves_login_labels_off_home():
    cleaned = sanitize_surface_anchors({
        "home": [
            "Sign in",
            "Create an account",
            "Username or email",
            "Password",
            "Valid-password-123!",
            "Invalid credentials",
            "session",
            "Account menu",
            "Access denied",
        ],
        "login": [],
    })
    home = set(cleaned.get("home") or [])
    login = set(cleaned.get("login") or [])
    assert "Valid-password-123!" not in home
    assert "Invalid credentials" not in home
    assert "session" not in home
    assert "Access denied" not in home
    assert "Username or email" in login
    assert "Password" in login
    assert "Sign in" in home
    assert "Create an account" in home
    assert "Account menu" in login
    assert "Account menu" not in home


def test_collect_from_polluted_checklist_line():
    text = (
        "【验收节点逐字清单】\n"
        '- REQ-1-1-2｜首页卡片须含: "Sign in"、"Username or email"、'
        '"Valid-password-123!"、"Invalid credentials"、"session"\n'
        '- REQ-1-1-1｜登录页须含: "Create an account"\n'
    )
    by_s = collect_surface_anchors_from_texts([text])
    home = set(by_s.get("home") or [])
    login = set(by_s.get("login") or [])
    assert "Valid-password-123!" not in home
    assert "Invalid credentials" not in home
    assert "session" not in home
    assert "Username or email" in login
    assert "Create an account" in login
    assert "Sign in" in home or "Sign in" in login


def test_auth_entrance_priority_note_redirects_off_index():
    report = (
        "路由 HTML 闸（surface=home）：GET / 可见 HTML 缺 "
        "「Username or email」、「Password」、「Invalid credentials」"
        "——请在 index 卡片模板补字段（外科补丁，禁止整文件重写）"
    )
    note = sm._auth_entrance_priority_note(report)
    assert note.strip()
    assert "index 卡片" in note or "禁止改 index" in note
    assert "webui" in note or "/login" in note
    assert "repos" in note


def test_auth_entrance_priority_silent_on_unrelated():
    assert sm._auth_entrance_priority_note("GET /api/health -> 500") == ""


def test_sign_in_link_count_and_collapse_for_official_strict():
    """5d05：Auth+Modules 双 Sign in → Playwright strict 全灭。"""
    html = (
        '<nav aria-label="Auth"><a href="/login">Sign in</a></nav>'
        '<nav aria-label="Modules">'
        '<a href="/register">Create an account</a>'
        '<a href="/login">Sign in</a>'
        '</nav>'
        '<button>Sign in</button>'
    )
    assert count_exact_named_links(html, "Sign in") == 2
    fixed = collapse_exact_named_links(html, "Sign in")
    assert count_exact_named_links(fixed, "Sign in") == 1
    assert 'aria-label="Auth"' in fixed
    assert 'href="/login">Sign in</a>' in fixed
    # Modules 里第二份 <a> 被删；Create an account 与 button 保留
    assert "Create an account" in fixed
    assert "<button>Sign in</button>" in fixed
    assert fixed.count('<a href="/login">Sign in</a>') == 1
