# -*- coding: utf-8 -*-
"""活动护栏兜底：零散 ModelClient 接入管线登记的预算护栏。

取证（2026-09-20 平台双跑）：auto_repair 等自建 ModelClient 不经工厂
接线，整体绕过预算——Keep/BookStack 各超支 3 倍+（7.0M/6.2M vs 2M 帽）。
"""
import pytest

from app.config import Settings
from app.utils.budget import (
    BudgetExceededError,
    BudgetGuard,
    get_active_budget_guard,
    set_active_budget_guard,
)
from app.utils.model_client import ModelClient


def test_active_guard_slot_roundtrip():
    set_active_budget_guard(None)
    assert get_active_budget_guard() is None
    guard = BudgetGuard(budget_tokens=100)
    set_active_budget_guard(guard)
    assert get_active_budget_guard() is guard
    set_active_budget_guard(None)


def test_stray_client_inherits_active_guard():
    guard = BudgetGuard(budget_tokens=100)
    set_active_budget_guard(guard)
    try:
        mc = ModelClient(Settings(), completion_fn=lambda **kw: None)
        assert mc.budget_guard is guard
        # 显式接线优先于兜底
        explicit = BudgetGuard(budget_tokens=50)
        mc2 = ModelClient(Settings(), completion_fn=lambda **kw: None,
                          budget_guard=explicit)
        assert mc2.budget_guard is explicit
    finally:
        set_active_budget_guard(None)


def test_no_active_guard_keeps_none():
    set_active_budget_guard(None)
    mc = ModelClient(Settings(), completion_fn=lambda **kw: None)
    assert mc.budget_guard is None


def test_exhausted_active_guard_blocks_call():
    """耗尽的护栏在 chat 入口即拦截（ensure_allowed → BudgetExceeded）。"""
    guard = BudgetGuard(budget_tokens=1)
    guard.record(10)  # 已超限
    set_active_budget_guard(guard)
    try:
        mc = ModelClient(
            Settings(),
            completion_fn=lambda **kw: pytest.fail("超预算不应发起调用"),
        )
        assert mc.budget_guard is guard
        with pytest.raises(BudgetExceededError):
            mc.chat("gpt-4o", [{"role": "user", "content": "hi"}])
    finally:
        set_active_budget_guard(None)
