# -*- coding: utf-8 -*-
"""全局测试夹具：隔离跨测试的全局状态。

活动预算护栏是进程级单例槽（pipeline 登记后零散 ModelClient 兜底接入），
测试间不重置会让"无护栏"断言被前序测试登记的护栏污染。
"""
import os

import pytest

from app.utils.budget import set_active_budget_guard


@pytest.fixture(autouse=True)
def _reset_active_budget_guard():
    set_active_budget_guard(None)
    yield
    set_active_budget_guard(None)


@pytest.fixture(autouse=True)
def _selftest_gate_off(monkeypatch):
    """自测闸会真实起服+跑 Playwright+调 LLM 生成——测试默认关闭，
    专门测自测闸的用例自行 monkeypatch 打开。"""
    monkeypatch.setenv("ARCBENCH_SELFTEST", "off")
