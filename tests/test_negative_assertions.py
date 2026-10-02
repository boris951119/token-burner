# -*- coding: utf-8 -*-
"""负面断言抽取测试（TDD：用例先于实现）。

官方题面两类"不该出现"形态（10-01 图1 官方题面 anatomy + 题面实测）：
1. 值不预存在：`The username and email ... 'nora.demo@example.test'
   are not registered.` / `The team name 'mobile-team' is not yet used`
   → 语义：应用不得把这些值当作已存在数据（预置账号/预占名单）；
2. 信息不回显：`passwords must not be echoed on the page`
   → 语义：页面不得出现密码明文。
判分语义（acceptance_judge 侧消费）：
- not_preexisting 值 → 页面/API 不得将其呈现为已存在数据；
- not_echoed 字段 → 响应体不得出现该字段的敏感值。
"""
from __future__ import annotations

from app.utils.negative_assertions import extract_negative_assertions


def test_not_registered_values():
    txt = ("The visitor clicks the visible link 'Sign in'. "
           "The username `nora-demo` and email `nora.demo@example.test` "
           "are not registered. The team name `mobile-team` is not yet "
           "used in that organization.")
    out = extract_negative_assertions(txt)
    values = [v for kind, v in out]
    assert ("not_preexisting", "nora-demo") in [(k, v) for k, v in out]
    assert ("not_preexisting", "nora.demo@example.test") in out
    assert ("not_preexisting", "mobile-team") in out
    assert all(kind == "not_preexisting" for kind, v in out)


def test_not_echoed_password():
    txt = ("The username and email identify the account, while passwords "
           "must not be echoed on the page.")
    out = extract_negative_assertions(txt)
    assert ("not_echoed", "password") in out


def test_no_negatives_in_plain_text():
    out = extract_negative_assertions(
        "The user enters a valid password and clicks Create account.")
    assert out == []


def test_dedup_and_order_stable():
    txt = ("`nora-demo` is not registered. `nora-demo` is not registered.")
    out = extract_negative_assertions(txt)
    assert len(out) == 1
