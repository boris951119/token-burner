# -*- coding: utf-8 -*-
"""generation-2 取证：_chat_resilient 旧版备胎调用裸奔——备胎再超时
即崩穿管线（143 需求 2 小时工作量归零）。全链保护回归。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.dev_loop import DevLoopEngine


class _R:
    content = "ok"


class _FlakyLLM:
    def __init__(self, fail_models):
        self.fail_models = set(fail_models)
        self.calls = []

    def chat(self, model, messages):
        self.calls.append(model)
        if model in self.fail_models:
            from app.agents.dev_loop import ModelChainExhausted
            raise ModelChainExhausted(f"LLM 调用失败（{model}，已重试 3 次）")
        return _R()


def _engine(fail_models):
    engine = DevLoopEngine.__new__(DevLoopEngine)
    engine.llm = _FlakyLLM(fail_models)
    engine.main_model = "openai/deepseek-v4-pro"
    engine.dev_model = "openai/minimax-m3"
    engine.test_model = "openai/glm-5.3"
    return engine


def test_dev_fails_main_rescues():
    engine = _engine({"openai/minimax-m3"})
    out = engine._chat_resilient(engine.dev_model, "s", "u")
    assert out.content == "ok"
    assert engine.llm.calls == ["openai/minimax-m3", "openai/deepseek-v4-pro"]


def test_gen2_scenario_third_role_rescues():
    """generation-2 场景升级：dev 与 main 全超时——旧码从备胎裸抛崩穿；
    新全链保护由第三棒（test 模型）救场。"""
    engine = _engine({"openai/minimax-m3", "openai/deepseek-v4-pro"})
    out = engine._chat_resilient(engine.dev_model, "s", "u")
    assert out.content == "ok"
    assert engine.llm.calls == ["openai/minimax-m3",
                                "openai/deepseek-v4-pro",
                                "openai/glm-5.3"], "按链序接力且各一次"


def test_all_three_fail_raises():
    engine = _engine({"openai/minimax-m3", "openai/deepseek-v4-pro",
                      "openai/glm-5.3"})
    import pytest

    with pytest.raises(RuntimeError):
        engine._chat_resilient(engine.dev_model, "s", "u")
    assert len(engine.llm.calls) == 3


def test_no_duplicate_calls_to_healthy_model():
    engine = _engine(set())
    engine._chat_resilient(engine.dev_model, "s", "u")
    assert engine.llm.calls == ["openai/minimax-m3"]


class _GateLLM:
    """每次都抛同一异常的桩（总闸形态：异常源于 BudgetGuard 检查点，
    与模型无关，换腿只是换一条腿继续违反中止指令）。"""

    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    def chat(self, model, messages):
        self.calls.append(model)
        raise self.exc


def test_cancel_gate_is_not_a_dead_leg():
    """批次#24：TaskCancelledError 是 RuntimeError 子类，旧兜底分支把它
    一并吞成 ModelChainExhausted → pipeline 按「这条腿废了」冻结当前模块
    继续跑下一个，用户点停止后仍在烧钱（取消检查点彻底失效）。"""
    import pytest

    from app.utils.budget import BudgetExceededError, TaskCancelledError

    for exc in (TaskCancelledError("用户取消"), BudgetExceededError("总闸")):
        engine = _engine(set())
        engine.llm = _GateLLM(exc)
        with pytest.raises(type(exc)):
            engine._chat_resilient(engine.dev_model, "s", "u")
        assert engine.llm.calls == ["openai/minimax-m3"], "总闸不换腿续烧"
