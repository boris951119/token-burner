# -*- coding: utf-8 -*-
"""讨论阶段模型级回退（keep1 取证：32 需求规模 glm-5.3 单次推理超
600s 墙钟×3 全灭，讨论路径无备胎直接崩）。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.orchestrator import DiscussionEngine as ProposalOrchestrator


class _FlakyLLM:
    """按模型名决定是否失败的假 LLM。"""

    def __init__(self, fail_models: set[str]):
        self.fail_models = fail_models
        self.calls: list[str] = []

    def chat(self, model, messages, **kwargs):
        self.calls.append(model)
        if model in self.fail_models:
            raise RuntimeError(f"degraded: {model}")
        return type("R", (), {"content": "ok"})()


def _orch(fail_models):
    llm = _FlakyLLM(fail_models)
    settings = Settings(models=["openai/glm-5.3", "openai/deepseek-v4-pro",
                                "openai/minimax-m3"])
    orch = ProposalOrchestrator(
        llm, "openai/glm-5.3", "openai/deepseek-v4-pro",
        "openai/minimax-m3", settings)
    return orch, llm


def test_main_timeout_falls_back_to_next_model():
    orch, llm = _orch({"openai/glm-5.3"})
    out = orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}])
    assert out == "ok"
    assert llm.calls[0] == "openai/glm-5.3"
    assert llm.calls[-1] != "openai/glm-5.3", "必须换模型重试"


def test_all_degraded_raises():
    orch, llm = _orch({"openai/glm-5.3", "openai/deepseek-v4-pro",
                       "openai/minimax-m3"})
    with pytest.raises(RuntimeError):
        orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}])
    assert len(llm.calls) == 3, "三个模型都应被尝试"


def test_healthy_main_no_fallback():
    orch, llm = _orch(set())
    out = orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}])
    assert out == "ok"
    assert llm.calls == ["openai/glm-5.3"]


# ---------------------------------------------------------------------------
# shape-keep 彩排（9/23）：评审路径漏装了备胎链——讨论阶段当场夭折
# keep1 只给 _chat 补了接力，副 LLM 评审 _get_review 仍是裸 llm.chat：
# 测试模型一条腿网关超时 → RuntimeError 直穿 pipeline.run → rc=1、
# 165k token 空烧、零交付（零 config.json 形态 read timeout 120s ×4 重试）。
# ---------------------------------------------------------------------------


def _review(orch, model="openai/glm-5.3"):
    return orch._get_review("需求原文", "提案", model, "测试工程师", "边界覆盖")


def test_review_degraded_model_falls_back():
    orch, llm = _orch({"openai/glm-5.3"})
    assert _review(orch) == "ok"
    assert llm.calls[0] == "openai/glm-5.3"
    assert llm.calls[-1] != "openai/glm-5.3", "评审腿废了必须换模型，不能拖死整跑"


def test_review_all_degraded_raises():
    """三腿全废仍须上抛：讨论缺评审＝spec 无据收敛，不如如实崩给看门狗。"""
    orch, llm = _orch({"openai/glm-5.3", "openai/deepseek-v4-pro",
                       "openai/minimax-m3"})
    with pytest.raises(RuntimeError):
        _review(orch)
    assert len(llm.calls) == 3


def test_review_requests_json_mode_on_fallback_too():
    """换腿不得丢掉 json_mode：评审契约（8.2）与模型无关。"""
    seen = []

    class _Spy:
        def __init__(self):
            self.calls = []

        def chat(self, model, messages, **kwargs):
            self.calls.append(model)
            seen.append(kwargs.get("json_mode"))
            if len(self.calls) == 1:
                raise RuntimeError("degraded")
            return type("R", (), {"content": "ok"})()

    from app.config import Settings as _S

    from app.orchestrator import DiscussionEngine

    spy = _Spy()
    orch = DiscussionEngine(
        spy, "openai/glm-5.3", "openai/deepseek-v4-pro",
        "openai/minimax-m3",
        _S(models=["openai/glm-5.3", "openai/deepseek-v4-pro",
                   "openai/minimax-m3"]))
    _review(orch)
    assert seen == [True, True]


def test_plain_chat_keeps_two_arg_call_shape():
    """文本路径不得平白多出 json_mode 关键字：注入的假 LLM 只认
    chat(model, messages)（接力改的是腿，不是调用签名）。"""
    class _Strict:
        def chat(self, model, messages):
            return type("R", (), {"content": "ok"})()

    from app.config import Settings as _S

    from app.orchestrator import DiscussionEngine

    orch = DiscussionEngine(
        _Strict(), "openai/glm-5.3", "openai/deepseek-v4-pro",
        "openai/minimax-m3", _S(models=["openai/glm-5.3"]))
    assert orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}]) == "ok"


def test_budget_exhausted_never_switches_model():
    """预算总闸/取消是 RuntimeError 的子类：接力若照单捕获＝把「立即中止」
    改成「再烧两腿」（11.0 取证过的 ¥210 失血方向）。"""
    from app.utils.budget import BudgetExceededError

    class _BudgetLLM:
        def __init__(self):
            self.calls = []

        def chat(self, model, messages, **kwargs):
            self.calls.append(model)
            raise BudgetExceededError("预算耗尽")

    from app.config import Settings as _S

    from app.orchestrator import DiscussionEngine

    llm = _BudgetLLM()
    orch = DiscussionEngine(
        llm, "openai/glm-5.3", "openai/deepseek-v4-pro",
        "openai/minimax-m3",
        _S(models=["openai/glm-5.3", "openai/deepseek-v4-pro",
                   "openai/minimax-m3"]))
    with pytest.raises(BudgetExceededError):
        _review(orch)
    assert llm.calls == ["openai/glm-5.3"], "超预算必须当场中止，不得换腿续烧"


# ---------------------------------------------------------------------------
# 彩排 A（2026-09-23 mini）：空内容不是异常，但同样是「这条腿废了」
# 推理模型吃满 max_tokens → HTTP 200 + content 空。旧 _relay 只看见异常，
# 于是评审拿到空文本静默降级（parse_json 失败 → return content 空串），
# 而这一刻 ModelClient 内部的扩容阶梯已经把这腿的预算烧完了。
# ---------------------------------------------------------------------------


class _EmptyForLLM:
    """指定模型返回空 content（其余正常），不抛异常。"""

    MODELS = ["openai/glm-5.3", "openai/deepseek-v4-pro", "openai/minimax-m3"]

    def __init__(self, empty_models: set[str]):
        self.empty_models = empty_models
        self.calls: list[str] = []

    def chat(self, model, messages, **kwargs):
        self.calls.append(model)
        text = "" if model in self.empty_models else "ok"
        return type("R", (), {"content": text})()


def _orch2(empty_models: set[str]):
    from app.config import Settings as _S

    from app.orchestrator import DiscussionEngine

    llm = _EmptyForLLM(empty_models)
    orch = DiscussionEngine(
        llm, "openai/glm-5.3", "openai/deepseek-v4-pro", "openai/minimax-m3",
        _S(models=list(_EmptyForLLM.MODELS)))
    return orch, llm


def test_empty_review_leg_hops_to_next_model():
    orch, llm = _orch2({"openai/glm-5.3"})
    out = orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}])
    assert out == "ok"
    assert llm.calls == ["openai/glm-5.3", "openai/deepseek-v4-pro"]


def test_all_legs_empty_returns_empty_instead_of_crashing():
    """全链皆空：保持既有降级形状（调用方拿到空串自行处理），不新增崩溃面。"""
    orch, llm = _orch2(set(_EmptyForLLM.MODELS))
    out = orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}])
    assert out == ""
    assert len(llm.calls) == 3, "三腿都该被试过"


def test_whitespace_only_content_counts_as_empty():
    orch, llm = _orch2({"openai/glm-5.3"})
    llm.empty_models = {"openai/glm-5.3"}

    def _blank(model, messages, **kwargs):
        llm.calls.append(model)
        return type("R", (), {"content": "   \n" if model == "openai/glm-5.3"
                              else "ok"})()

    llm.chat = _blank                      # type: ignore[method-assign]
    assert orch._chat("openai/glm-5.3", [{"role": "user", "content": "x"}]) == "ok"
    assert llm.calls[-1] == "openai/deepseek-v4-pro"
