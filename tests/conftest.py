# -*- coding: utf-8 -*-
"""全局测试夹具：隔离跨测试的全局状态。

活动预算护栏是进程级单例槽（pipeline 登记后零散 ModelClient 兜底接入），
测试间不重置会让"无护栏"断言被前序测试登记的护栏污染。
"""
import pytest

from app.utils.budget import set_active_budget_guard


@pytest.fixture(autouse=True)
def _reset_active_budget_guard():
    set_active_budget_guard(None)
    yield
    set_active_budget_guard(None)
