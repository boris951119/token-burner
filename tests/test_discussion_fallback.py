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
