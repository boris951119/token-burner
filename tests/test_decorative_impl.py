# -*- coding: utf-8 -*-
"""刀K：装饰性实现门禁回归（批次#85 _GLOBAL_UI_COPY 同形）。"""
from __future__ import annotations

from app.utils.decorative_impl import (
    ast_string_literals,
    check_decorative_impl,
)


def test_knife_k_dead_global_ui_copy_reds():
    """#85 同形：_GLOBAL_UI_COPY 有串、渲染体无串 → 装饰性红。"""
    code = '''
_GLOBAL_UI_COPY = {
    "login": {
        "create": "Create an account",
        "title": "Sign in to GitHub",
    }
}
# 零引用——字典定义后从未读出
'''
    rendered = "<html><body><h1>Login</h1><button>Sign In</button></body></html>"
    issues = check_decorative_impl(
        anchors=["Create an account", "Sign in to GitHub"],
        code=code,
        rendered_html=rendered,
        module="web_git",
    )
    assert issues
    assert "装饰性" in issues[0]
    assert "Create an account" in issues[0]


def test_knife_k_greens_when_rendered():
    code = '''
COPY = "Create an account"
def page():
    return f"<a>{COPY}</a>"
'''
    rendered = '<html><body><a href="/r">Create an account</a></body></html>'
    assert check_decorative_impl(
        anchors=["Create an account"],
        code=code,
        rendered_html=rendered,
    ) == []


def test_knife_k_skips_when_not_in_source():
    """源码根本没有该字面量 → 不归装饰性（交给刀J'缺渲染红）。"""
    code = "def page():\n    return '<p>ok</p>'\n"
    assert check_decorative_impl(
        anchors=["Create an account"],
        code=code,
        rendered_html="<p>ok</p>",
    ) == []


def test_knife_k_hidden_render_counts_as_dead():
    """仅藏在 hidden 里 = 未进入可见响应 → 仍红。"""
    code = '_COPY = "Create an account"\n'
    rendered = '<div hidden>Create an account</div><p>Login</p>'
    issues = check_decorative_impl(
        anchors=["Create an account"],
        code=code,
        rendered_html=rendered,
    )
    assert issues


def test_ast_string_literals_reads_dict_values():
    lits = ast_string_literals(
        '_GLOBAL_UI_COPY = {"a": "Create an account"}\n')
    assert "Create an account" in lits
